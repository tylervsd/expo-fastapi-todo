# Phase 9: Reliable, resumable workflows

Phase 8 made the backend pick the screen. Phase 9 makes the workflow safe
to resume and retry: a signed-in user can discover every unfinished plan,
resume one on web or iOS, and retry a start or action whose response was
lost without creating a second draft, advancing twice, or creating
duplicate todos. If another device already advanced the plan, the client
reloads the authoritative current step and explains that the submitted
answer was stale.

The backend stays authoritative. PostgreSQL owns revisions, idempotency
records, accepted outcomes, workflow state, and todo creation. The client
keeps only the latest server snapshot, unsubmitted form state, and one
narrowly scoped durable recovery record for a write whose result is
unknown. There is no offline queue, no background retry, and no external
side effect.

## 1. Three identifiers that are not interchangeable

Every workflow write carries three different identifiers with three
different jobs:

- `step_id` (`"{workflow_id}:{state}"`, e.g. `b1fff6…:OFFER_BREAKDOWN`)
  identifies the rendered interaction state. A same-step fetch keeps its
  identity; every accepted transition reaches a different state. It is a
  rendering tool only: never stored in PostgreSQL, never a cache key, never
  concurrency control.
- `revision` (integer `0..2147483647`) is the concurrency token. Start
  returns revision `0`; every accepted action — including cancel and
  confirm — increments by exactly one. Fetches and replays never increment
  it. Two devices racing one revision serialize: the first commits, the
  second gets `stale_step`.
- `request_id` (client-generated UUID, one per intended mutation)
  identifies the *intent*. Retrying the same request ID replays the one
  accepted outcome; a new request ID is a new intent and must supply the
  current revision.

Mixing them up is the classic bug this phase prevents: step identity
detects "you answered an old screen", revision detects "someone else wrote
first", and request identity detects "this exact write already happened".

## 2. Canonical payload equality

Idempotency compares *what was asked*, not just the request ID. Each
operation hashes a canonical JSON payload with stdlib SHA-256 over
sorted-key, compact-separator, UTF-8 bytes:

- start: `{"operation":"start","title":<canonical title>}`
- advance: `{"operation":"advance","workflow_id":…,"expected_revision":…,
  "step_id":…,"action":…}` with significant array order and duplicates

The request ID itself and the auth token are excluded. Replaying the same
request ID with the same payload returns the recorded outcome byte-for-byte
(verified: start replay `201`, action replay `200`, identical bodies).
Replaying the same request ID with a *different* payload returns `409
request_id_reused` ("This request ID was already used with different
details.") — the server refuses to guess which intent you meant.

## 3. Transactional replay ordering

### Start (one transaction)

1. Validate and canonicalize before opening the transaction. Build the
   workflow UUID and its complete initial snapshot (revision 0,
   definition 1) in memory.
2. Claim the request with `INSERT … ON CONFLICT DO NOTHING RETURNING` on
   `(owner_id, request_id)`. The workflow foreign key is deferred, so the
   workflow row can be inserted later in the same transaction.
3. On a win, insert the workflow and commit both. No placeholder is ever
   committed.
4. On a loss, `SELECT` the winner in a *separate* statement (never folded
   into the same CTE — under `READ COMMITTED` a waiting insert can observe
   a row its original snapshot could not see), compare fingerprints, and
   return the saved snapshot or `request_id_reused`.

### Advance (one transaction)

1. Lock the owner-scoped workflow row (`FOR UPDATE`). Absence is `404`
   before any idempotency record exists.
2. Read the existing `(owner_id, workflow_id, request_id)` record
   **first**: fingerprint match returns the saved snapshot, mismatch
   raises `request_id_reused`. Replay therefore precedes stale and
   terminal checks, so a lost successful response stays replayable after
   its action changed the workflow.
3. For a new request, validate stored definition, exact step ID, expected
   revision, terminal rules, the revision ceiling (`409
   revision_exhausted` at `2147483647`), and the domain action.
4. Insert todos when confirming, then update with one conditional
   statement (`WHERE public_id, owner_id, revision = expected_revision`,
   `revision = revision + 1`), requiring exactly one returned row —
   otherwise `409 stale_step` ("This plan changed. Reload it and try
   again."). Refresh the row, insert the full accepted outcome, commit
   once. Any error rolls back todos, workflow state, revision, and the
   request outcome together.

Confirmation, todos, revision, terminal state, and the idempotency outcome
commit or roll back atomically: an injected failure after todo insertion
leaves no todos, no state change, no revision bump, and no claim, and a
retry succeeds. Two distinct requests racing one revision produce one
advance and one recoverable stale conflict with exactly one revision
increment (verified with bounded thread barriers, no sleeps).

## 4. Discovery, fetch, and resume

`GET /todo-workflows` (omitted `status` defaults to `active`; any other
value is `422`) returns `{"items": […]}` — full snapshots, newest database
identity first, only the four nonterminal states owned by the caller.
Completed, cancelled, missing, and other-owned workflows are absent. The
list is deliberately unpaginated for this tutorial (see section 9).
`GET /todo-workflows/{id}` returns the current snapshot with no side
effect and stays owner-hidden as `404` ("Todo workflow not found.").

The todo screen shows **Resume plans** when discovery has active items;
each item is an accessible button labelled with its plan title and current
prompt. Selecting one passes its ID into the existing template host, which
fetches the authoritative snapshot and renders it without advancing.
Resuming the same plan on a second session returns the identical revision —
observed at runtime across two login tokens and across an API restart.

## 5. Saved context versus unsent text

Only *accepted* workflow context survives a reload: state, revision,
title, answers, proposed titles, and completion results. Unsubmitted title
and breakdown text remain local component state and are lost on reload —
stable React keys preserve drafts across re-renders and same-step refetches
(see the Guide 08 clarification), but an actual reload or unmount destroys
component state. A changed step ID clears the draft; a same-step refetch
preserves it. Design copy and recovery flows around this boundary: never
promise the user their half-typed text is safe.

## 6. Durable unknown writes

Before sending a start or action, the client freezes a UUID request ID and
persists exactly one owner-bound record (`todo.pending-workflow-write.<ownerUuid>` in `localStorage` on web, Expo SecureStore on native —
verified against the Expo SDK 57 Crypto and SecureStore docs; UUIDs come
from `Crypto.randomUUID()`, no custom generator). The record holds no
token, username, password, or server response. The network mutation does
not begin unless the exact payload reads back successfully; otherwise the
UI reports **"This device could not save a safe retry. The plan was not
sent. Try again."** All valid maximum-size Unicode inputs round-trip
exactly, including a ten-title payload.

Only one workflow write can be pending per owner per installation —
records for different owners coexist under separate owner-scoped keys, but
a second write for the same owner is refused with "Another workflow write
is still pending. Retry or discard it before sending a new one." Two tabs
sharing one installation are not coordinated: each tab reads and writes the
same owner-scoped key, so concurrent tabs can overwrite each other's pending
record — a deliberate non-target (see section 9). On validated success the matching
owner/request record is cleared and the response applied; a storage-clear
failure keeps the record with "The plan was saved, but recovery is still
pending. Retry or discard the saved request." A timeout, network failure,
or app termination keeps the record and locks new writes.

After authentication, a matching record is offered as **Retry saved
request** / **Discard saved request** and is never sent automatically.
Retry sends the stored body unchanged under the current token, recovers the
historical outcome, then performs a current GET and renders the newest
revision. Discard warns: "The saved request was discarded locally, but the
server may already have applied it. Refresh the list to check." Definitive
rejections (`422`, `404`, `invalid_action`, `terminal_workflow`,
`revision_exhausted`, unsupported definition) clear the record because
they prove the request did not commit — except `request_id_reused`, which
stays visible until explicitly discarded since its identity is unsafe to
replace. `401` requires re-authentication without replaying under another
owner. Observed in a real browser: an aborted advance left **Retry saved
request**, and retrying advanced the plan exactly once. Likewise, an
aborted start left **Retry saved request**, and retrying started the plan
once — discovery shows exactly one draft. A fresh browser context logging
in as the same user sees the plan under **Resume plans** and resumes its
authoritative current step.

## 7. Version migration

`definition_version` records which transition rules interpret a saved
workflow; new rows use constant `CURRENT_WORKFLOW_DEFINITION_VERSION = 1`
(the unchanged Phase 8 graph). Migration `2026090901` backfills existing
rows to revision `0` / definition `1` (a concurrency token needs no
history), then enforces non-null, defaults, range checks, a unique
`(public_id, owner_id)`, and the two request tables. Downgrade drops only
the new tables/constraints/columns — never workflows or todos.

Rows with an unknown definition are readable only far enough to identify
owner and workflow: discovery and fetch return `409
unsupported_workflow_definition` without recording an outcome or changing
data (verified at runtime by setting a row to definition 2: fetch and
discovery both failed closed, and reverting restored normal reads).
`view_contract_version` is separate and unpersisted — it describes the
response encoding. Every snapshot response carries `view_contract_version:
1`; the client parses version 1 strictly, renders any other positive
version as metadata-only **Unsupported saved plan** (never submitting, never
inventing fields), and treats malformed metadata as `invalid-data`.

## 8. Stale-cache reconciliation

One shared rule decides every cache write: `keepLatestWorkflow` keeps the
higher revision (ties keep incoming; identities must match first) and is
also wired as TanStack Query `structuralSharing` with runtime validation,
so even the cache layer itself cannot regress revision 4 with a late
revision 3 — pinned by a deferred-GET regression test. Discovery seeds
per-workflow entries only forward; mutation responses are recovery evidence
only. After every mutation success or replay, the client performs a current
GET and renders that result; `stale_step` does the same GET before
enabling another write. A failed reconciliation GET keeps controls
disabled with a visible reload.

Responses are accepted only when the captured authentication-session epoch
is still current — the epoch changes on restore, login, logout, and
replacement, including signing out and back in as the same user. A stale
callback cannot populate cache, select a plan, or clear a newer recovery
record; a matching pending record survives same-owner re-login and is
offered, never auto-sent. Cross-user records are never loaded, displayed,
or submitted (verified: a second user discovers nothing and fetches
`404`).

Recovery, stale, and lock messages use `accessibilityRole="alert"`; retry
and discard have distinct accessible names; controls stay disabled while
storage, mutation, or reconciliation work is pending. Unsupported views
never expose action controls.

## 9. Deliberate limitations

- **Single-instance journal.** The recovery record covers one pending
  workflow write per owner per installation. Multiple browser tabs sharing
  one installation are not a coordination target: they share the same
  owner-scoped key without locking, so one tab can overwrite another's
  pending record. Independent devices are covered by backend idempotency,
  not by shared client state.
- **Unpaginated tutorial list.** Discovery performs one owner-indexed
  active-row query with no pagination. Add pagination only when a measured
  number of abandoned drafts makes the bounded owner scan material — never
  silently limit discoverability.
- **No offline queue.** Unsubmitted text is local and losable; only
  accepted context is resumable. There is no automatic retry, background
  sync, expiration, or deletion policy for abandoned workflows.

## 10. Focused commands that were actually verified

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest tests/test_workflow_domain.py tests/test_workflow_presentation.py tests/test_workflow_persistence.py tests/test_workflow_reliability.py tests/test_workflows.py tests/test_validation.py
pnpm --dir apps/mobile test --runInBand src/todoWorkflows src/TodoExperience.test.tsx src/todos/todoApi.test.ts src/auth/authenticatedApi.test.ts src/auth/AuthProvider.test.tsx
pnpm quality
```

Backend suites run against the real guarded `todo_test` database
(including barrier-synchronized race tests with `future.result(timeout=10)`
instead of sleeps); component tests use injected fakes with deferred
promises and deterministic gates. During implementation the focused
backend suite passed 258/258, the focused client suite 263/263, and the
full `pnpm quality` gate exited 0 (mobile 337/337, API 328/328, lint,
typecheck, and web export clean). Rerun all three before any further
change.

## 11. Manual recovery exercises

With the API and web app running locally (see the setup guide), try these
against the UI and confirm each behavior:

1. Start "Plan birthday party", answer Yes, Yes, enter two titles, review,
   confirm — exactly two todos appear in order, and the plan leaves
   **Resume plans**.
2. Start a second plan, answer Yes, Yes to reach **Break it into smaller
   todos**, type two titles without pressing **Save tasks**, then reload
   the page — the plan reappears under **Resume plans** at the same
   `COLLECT_TASKS` step, but the typed titles are gone (verified: the
   titles field is empty after reload; expected, only accepted context
   resumes).
3. With devtools blocking the advance request, answer a question, then
   unblock and press **Retry saved request** — the plan advances exactly
   once with no duplicate draft.
4. Answer from two sessions at once (two browsers or a reload mid-flight)
   — one answer wins (DB shows a single revision increment); the loser
   auto-reconciles to the current step and keeps the explanation
   "This plan changed. Reload it and try again." visible alongside it
   (re-observed 2026-09-08 after the sticky-notice fix: the message
   persists post-settle with zero page errors).
5. Sign out and back in with a pending retry outstanding — the retry is
   offered, never auto-sent, and works under the new session.

## 12. Phase 9 acceptance record

Web rows below were observed 2026-09-08 (America/Los_Angeles) in headless
Chrome 140 driving Expo web (Metro on `127.0.0.1:8089`) against a local
API (uvicorn on `127.0.0.1:8000`, PostgreSQL 18.6 scratch database
migrated to head `2026090901`). The Backend row records direct HTTP
checks of the same server; it is not a UI claim. Browser cross-origin
POSTs required launching Chrome with `--disable-web-security` because the
API defines no CORS policy (mobile targets are unaffected; no repo change
was made for this). A second web pass the same day (fresh users) observed
the storage-failure, unsupported-contract, focus/alert, and competing-revision
rows below; the competing-revision pass surfaced one finding (the
stale explanation never painted), which was fixed (sticky stale notice)
and re-observed the same day — see the Web competing-revisions cell).

| Target | Date/runtime | Quick add | Birthday branches | Discovery after restart | Another-device resume | Lost-start retry | Lost-confirmation retry | Competing revisions | Cancel | Storage failure-before-send | Sign-out/re-login | Unsupported UI | Focus/alerts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Web | 2026-09-08, Chrome 140 headless driving Expo web | ☑ observed ("Web milk" appears) | ☑ observed (No→1 todo COMPLETED rev 2; Yes/No→1 todo COMPLETED rev 3; Yes/Yes→2 todos; DB-verified) | ☑ observed (browser reload relists draft; API kill+restart then fresh login relists draft) | ☑ observed (fresh browser context login → Resume plans → renders OFFER rev 1) | ☑ observed (aborted start POST → Retry saved request UI → retry → ASSESS; discovery count 1, no duplicate) | ☑ observed (aborted action POST → app retry advanced exactly once, no dup todos) | ☑ observed (two contexts raced one revision 2026-09-08: winner advanced once, loser POST→409, auto-reconciled to the current OFFER step with "This plan changed. Reload it and try again." visible and persisting post-settle, 0 page errors; mechanism confirmed: the lock:true message had been hidden while cache stayed fresh plus keepMessage:false cleared it — now a sticky notice) | ☑ observed ("Plan cancelled"; plan leaves Resume plans, other draft stays) | ☑ observed (`localStorage.setItem` forced to throw → "This device could not save a safe retry. The plan was not sent. Try again.", 0 advance POSTs, stays at ASSESS, no page errors) | ☑ observed (todos + draft survive) | ☑ observed (discovery rewritten to `view_contract_version: 2` → "Unsupported step" + newer-app copy with Reload/Back controls, zero submit controls, 0 action POSTs, no page errors) | ☑ observed (Tab order reaches Yes; Enter advances ASSESS→OFFER; storage-failure copy renders in `role=alert`; no page errors) |
| Backend (HTTP) | 2026-09-08, curl against the same local API | ☑ observed | ☑ covered end-to-end via browser + DB rows above; HTTP advanced every transition incl. race | ☑ observed (post-API-restart rediscovery; terminal completion discovers `[]`) | ☑ observed (2nd login token fetches rev 0) | ☑ observed (start replay 201 byte-identical; mismatch → `request_id_reused`) | ☑ observed (confirm replay 200 byte-identical, no dup todos) | ☑ observed (one 200 rev+1, one 409 stale with spec copy; single advance) | ☑ observed (CANCELLED rev 1) | — (client-only) | — (client-only) | ☑ observed (definition 2 → fetch+discovery 409, no mutation; reverted after) | — (client-only) |
| iOS Simulator | 2026-09-08, iPhone 17 Pro (0781311B), Maestro-driven, post-SecureStore-key fix and post-auth-autocorrect fix (users i2lost1; screenshots /tmp/iosr2/shots/) | ☑ observed ("iOS milk" as ioswave6, DB-verified row) | ◐ partial — No-branch full walk observed (OFFER No→REVIEW rev 2→Confirm→COMPLETED rev 3 with exactly 1 todo, DB-verified); Yes→OFFER observed twice; Yes/Yes collect-tasks walk not exercised | ◐ partial — terminate+relaunch relists the draft in Resume plans after sign-in and resume opens it without advancing (0 workflow POSTs); cold relaunch with dead API lands on the sign-in form (restore needs a reachable API) | ☐ blocked — same-device restart only; covered by web row + tests | ◐ partial — lost-ACTION retry observed (Yes with dead API → "Could not update the plan." + Retry/Discard, step unchanged; API up → Retry → OFFER rev 1 with exactly 1 POST, no duplicates); lost-START (pre-first-response) not exercised on iOS | ☐ blocked — not exercised on iOS; covered by web row + tests | ☐ blocked — not exercised on iOS; covered by web + Backend rows | ☑ observed ("Plan cancelled"; CANCELLED rev 1, DB-verified) | ☑ observed pre-fix (fail-closed copy with 0 workflow POSTs; `:` key root cause fixed to `.`) | ◐ partial — pending Yes survived terminate+relaunch+fresh sign-in with Retry offered and 0 auto-sends; explicit in-app Sign-out button flow not exercised | ☐ blocked — not exercised on iOS; covered by web row + tests | ☐ blocked — keyboard/focus pass not yet run on iOS; covered by web row + tests |

iOS acceptance is interactive via Maestro (installed this pass; needed
Homebrew `openjdk` for its JVM): `expo run:ios` with `EXPO_PUBLIC_API_URL`
built with 0 errors, installed, and launched on a booted iPhone 17 simulator
where signup (API 201 + "Account created. Please sign in."), sign-in
("Signed in as ioswave6"), and quick-add (DB-verified) were all observed
with screenshots and no crash (one pre-existing SafeAreaView deprecation
LogBox warning, unrelated to Phase 9). The earlier all-writes-fail-closed
behavior was a code defect, not a sick simulator: the pending-write key
used `:` (`todo.pending-workflow-write:`), which native SecureStore
rejects (web localStorage accepts it, and the Jest mock had allowed it).
The prefix now uses `.`, the mock rejects illegal keys like the native
module, and a fresh iPhone 17 Pro pass observed start→201/ASSESS rev 0
and Yes→200/OFFER rev 1 with screenshots, DB-verified rows, and zero
errors. Round 2 additionally observed the No-branch walk, cancel,
restart discovery/resume, lost-action retry, and sign-out/re-login
(partial) on iOS (see row). The remaining plan-dependent iOS rows
(Yes/Yes walk, lost-start, lost-confirmation, competing revisions,
unsupported UI, focus, explicit sign-out, another-device) are still
unexercised on iOS (see row) — covered by the web row and automated tests.
Revision-exhaustion at `2147483647` is
covered by integration tests, not by manual exercise.
