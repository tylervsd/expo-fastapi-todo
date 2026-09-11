# Phase 11: Agentic UI with assistant-ui and AG-UI

Phase 11 adds one authenticated assistant-ui/AG-UI clarification-and-review
flow to the existing guided todo workflow. At the **Break it into smaller
todos** step, a signed-in user can ask an OpenRouter-backed Python agent for
help. The agent chooses one relevant question from a fixed clarification
catalog, assistant-ui renders that question as a native form, and the
submitted answer produces a durable Phase 10 suggestion request. A later
AG-UI run renders the saved titles as an editable checklist. Accepting the
edits uses the existing `submit_tasks` transition; only the existing explicit
`confirm` transition creates todos.

Phase 11 was merged in PR #8 (`e99eca0`). This revision includes the acceptance fix (`61fb30c`), developed on
`codex/phase-11-acceptance`. Interactive web and iOS checks and live model
calls were observed on 2026-09-10. The record below separates live results,
controlled interruption checks, and automated coverage; it is not a claim
of production reliability or a completed accessibility audit.

## 1. Topology: one direct agent connection, no second service

Expo mounts one workflow-scoped assistant-ui runtime around an authenticated
`HttpAgent` that calls the existing FastAPI server directly at
`${EXPO_PUBLIC_API_URL}/agent` with `threadId` set to the workflow UUID.
Node remains Expo tooling only. There is no runtime service, proxy, second
port, new public URL, client-selected agent URL, hosted assistant-ui
dependency, CopilotKit registration, A2UI renderer, or frontend model call.
The same direct path is available in development and production builds.

FastAPI exposes authenticated `POST /agent`. It accepts standard AG-UI
`RunAgentInput`, requires `threadId` to equal the workflow UUID and `runId`
to be a 1–128 character ASCII URL-safe identifier (`A-Z`, `a-z`, `0-9`,
`_`, `-`), loads that owner-scoped workflow, and validates the current
definition, revision, step, and expected `COLLECT_TASKS` or
review-acknowledgement state before emitting events. Client tool schemas and
arbitrary message instructions are never authority. The server owns exactly
two tool names and constructs every tool argument. The route caps the
encoded body at 32 KiB, accepts at most 12 messages, caps each text item at
1,000 code points and each tool result at 4 KiB (UTF-8 bytes), and rejects
unknown state fields before any provider call.

## 2. Pinned compatibility

The [compatibility spike](../../spikes/assistant-ui-ag-ui/README.md)
validated this exact release set, and the app pins the same versions —
no unrelated upgrades were taken with them:

| Package | Version | Published license |
| --- | --- | --- |
| `@assistant-ui/react-native` | 0.1.40 | MIT |
| `@assistant-ui/react-ag-ui` | 0.0.58 | MIT |
| `@ag-ui/client` | 0.0.59 | MIT |
| Python `ag-ui-protocol` | 0.1.22 | (provides `RunAgentInput`, core events, `EventEncoder`) |

The app runs Expo SDK 57.0.19, React Native 0.86.3, and React 19.2.3.
Native startup requires `crypto.getRandomValues`, so
[`apps/mobile/src/polyfills.ts`](../../apps/mobile/src/polyfills.ts)
supplies it from the app's existing `expo-crypto` dependency and is
imported first in [`apps/mobile/index.ts`](../../apps/mobile/index.ts),
before `App`. There is no `Math.random` fallback. The pinned public
surface is `AssistantRuntimeProvider`, `ThreadPrimitive`
(`MessagesFlatList`), `MessagePrimitive.Parts`, `useAgUiRuntime`,
`useAgUiSetState`, `HttpAgent`, and the tool-part `addToolResult`. No
fetch/TextEncoder polyfill, Metro change, package patch, private import,
compiler, or toolkit was needed: the only test-infrastructure change is a
`transformIgnorePatterns` allowlist for the pinned ESM packages in the
mobile Jest config, added after reproducing the
`Cannot use import statement outside a module` failure.

The spike's fixture token, localhost URL, and simplified validation were
not copied into application code. Tests use non-routable fixture values
such as `https://api.example.test/agent` inside test files only.

## 3. Authentication and state ownership

`AuthProvider` keeps the bearer token private in a ref that never enters
props, query keys, agent state, pending storage, or logs. Its signed-in
branch exposes an opaque agent factory keyed by session epoch; the token
remains inside that closure. For the selected workflow the screen creates
one stable `HttpAgent` with the current `Authorization: Bearer` header and
`threadId` set to the workflow UUID, then mounts one `useAgUiRuntime`
inside `AssistantRuntimeProvider`. Switching workflow IDs remounts the
runtime, clears its messages and state, and aborts the old agent. Token
replacement, logout, or unmount does the same. One runtime never carries
messages or state between workflows or sessions, and no new environment
variable was added.

`RunAgentInput.state` is the exact object
`{contract_version: 1, expected_revision, step_id,
suggestion_request_id: string | null}`; `threadId` carries the workflow
UUID. A non-null suggestion ID that is not the current ready
owner/workflow/revision/step proposal fails closed and never falls through
to a new model call. The client installs this state with the public
`useAgUiSetState` setter synchronously before calling the tool part's
public `addToolResult` exactly once; `addToolResult` automatically starts
a second AG-UI POST after the first run has settled, and that POST
observes the updated state. (The inspected adapter does not copy an
`HttpAgent.initialState` into runtime state, so the initial-state gate —
not constructor options — is what enables the first agent action.)

PostgreSQL workflow/suggestion records are durable authority. TanStack
Query holds authoritative snapshots; assistant-ui messages hold only the
current UI conversation. Agent events may propose rendering but never patch
workflow cache directly. After form or checklist work, the client
refetches/reconciles through the existing Phase 9/10 paths before enabling
another write. No HTTP stream or database transaction waits for a person:
each tool request ends with `RUN_FINISHED`, and submitting a tool result
starts a separate run. Read transactions are rolled back before terminal
events on every path, including error paths.

## 4. Bounded clarification on Phase 10 suggestions

Phase 10 suggestion requests accept one optional exact field,
`clarification`, an object with a catalog `field` (`date`, `location`,
`people`, `budget`, or `constraints`) and a `value` of 1–200 trimmed code
points with no NUL byte. Omission retains the Phase 10 fingerprint
byte-for-byte, so old retries keep their exact hash and behavior; when
supplied, the canonical object joins the fingerprint, and reusing a
request ID with a different clarification reports `request_id_reused`.
Normalization lives in one service function shared by the API model, the
service, and the provider. The provider prompt gains exactly one short
labeled line carrying the field and value; the server stores only the
request fingerprint, never clarification text or raw provider output. The
answer exists only in the owner-scoped local pending write until its exact
suggestion retry resolves or is discarded.

The first agent run asks OpenRouter for one strict structured decision
containing only the catalog field (for example `{"field":"date"}`), chosen
from the canonical workflow goal through the shared bounded/redacted
transport: 400 requested output tokens, a 16 KiB response cap, a hard
30-second deadline, 5-second connect/write/pool timeouts, and a 25-second
read timeout. Python maps the field to fixed local prompt/label copy and
emits `clarify_plan`. Invalid or failed decisions end with a safe AG-UI
error and leave the manual Phase 10 path available. OpenRouter calls and
all authorization and business validation stay in Python.

The clarification form submits one 1–200-code-point answer. While that
pending tool card is submitting, the client creates the Phase 10
suggestion request with the current workflow identity and `{field,
value}` through the single screen-owned pending-write path, so agent
writes share the existing save/read-back, retry, discard, and reconcile
machinery. After suggestion success the client sets agent state with the
current revision/step and returned request ID, then adds the tool result
with that same ID. Its automatic continuation therefore runs against the
updated state and starts no workflow transition. An uncertain failure
retains the saved request and sends neither a result nor a new request ID.

## 5. Editable review with confirm-only creation

On every later AG-UI request Python first checks the state-provided
request ID against the owner-scoped current ready Phase 10 proposal. A
match emits `review_todo_suggestions` from persisted titles without prior
conversation history or another model call, so reload can recover a ready
proposal. Without a current ready ID, structurally matching clarification
call/result messages may continue, but client history never authorizes a
write. Tool-call IDs are `{runId}:{tool}:0`; a repeated ID within a run
fails closed, and tool results must structurally match the immediately
preceding call.

The checklist's **Use these suggestions** submits edited titles through the
existing `advance` API with `submit_tasks`. The client then sets agent
state to the returned `REVIEW` revision/step before adding the review tool
result. Its automatic continuation runs against `REVIEW`; Python validates
the result against the authoritative snapshot — latest READY suggestion,
matching request ID, accepted revision equal to the snapshot revision,
and call titles equal to the saved pre-submit proposal (so user edits,
which become the authoritative snapshot, still acknowledge cleanly) — and
emits only `RUN_STARTED` then `RUN_FINISHED`. It neither regenerates
suggestions nor performs a write. Other non-`COLLECT_TASKS` invocations
fail closed. Rendering, replay, reconnection, and completion events never
create or confirm todos; todos remain zero until the unchanged explicit
**Confirm** button succeeds.

## 6. Event and tool contract (as implemented)

Every run emits `RUN_STARTED`, balanced message/tool-call events, then
exactly one `RUN_FINISHED` or `RUN_ERROR`. Tool calls stream as the
subsequence `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`, so a
clarification run observes exactly `RUN_STARTED`, `TOOL_CALL_START`,
`TOOL_CALL_ARGS`, `TOOL_CALL_END`, `RUN_FINISHED`. Tool-call IDs are
`{runId}:clarify_plan:0` or `{runId}:review_todo_suggestions:0`; a
repeated ID within a run fails closed. Text events are optional status
copy and never carry workflow state. This ordering and the single-terminal
rule are proven by the protocol encoder test and the agent order test;
the client continuation test proves the second POST carries the installed
state and the tool result.

`clarify_plan` arguments are an exact object:

```json
{"contract_version":1,"workflow_id":"uuid","expected_revision":2,
 "step_id":"uuid:COLLECT_TASKS","field":"date"}
```

Its result is exact and bounded:

```json
{"contract_version":1,"suggestion_request_id":"uuid"}
```

`review_todo_suggestions` repeats `contract_version`, workflow identity,
revision, step, and suggestion request ID, and adds `titles` with Phase
10's 2–10 canonical-title bounds:

```json
{"contract_version":1,"workflow_id":"uuid","expected_revision":2,
 "step_id":"uuid:COLLECT_TASKS","suggestion_request_id":"uuid",
 "titles":["Choose a date","Invite guests"]}
```

Its exact result is
`{"contract_version":1,"request_id":"uuid","accepted_revision":3}`.
Unknown names, versions, extra keys, malformed arguments, mismatched IDs,
stale revisions/steps, and unsupported fields render a safe recovery
message and cannot call `advance`. The client renderer accepts only these
canonical server-owned names and exact argument shapes.

## 7. Manual fallback and accessibility

Both allowlisted components use native controls with visible labels,
44-point targets, focus movement (arrival and completion, including after
a card resolves and unmounts), alert/live announcements, disabled
duplicate-submit states, and non-color status. Manual title entry and the
Phase 10 suggestion button remain usable whenever the agent layer fails,
and unknown names, versions, extra keys, malformed arguments, mismatched
IDs, or stale revisions render a safe recovery message. Competing
workflow/suggestion writes are disabled only while the panel owns an
unresolved write. The client captures owner, session epoch, workflow,
revision, step, run, tool, and suggestion request identities around
asynchronous work; sign-out, replacement login, unmount, cancellation, or
a newer snapshot discards late events and results.

## 8. Verification performed

The following checks were run on 2026-09-10 (America/Los_Angeles) at the
PR review-fix revision. The API suite ran against the isolated PostgreSQL
`todo_test` database on 127.0.0.1:5433 (the existing `db-test` compose
container):

```bash
uv run --directory apps/api python -m pytest tests -q
pnpm --dir apps/mobile test --runInBand
pnpm --dir apps/mobile typecheck
uv run --directory apps/api ruff check .
git diff --check
pnpm lint:markdown
pnpm lint:links
pnpm --dir apps/mobile export:web
npx --prefix apps/mobile expo export --platform ios --output-dir dist-ios-verify
```

After the acceptance run-ID fix, the PostgreSQL-backed API suite passed
**501/501** tests and the mobile
suite passed **522/522** tests across 17 suites. Ruff and whitespace checks
passed for the fix. The earlier PR verification also passed typecheck,
`git diff --check`, Markdown lint (0 issues across 47 files), and
local-link checks were clean. Web and iOS bundle exports completed
successfully; a successful export is not evidence of interactive behavior
(see the acceptance record). The agent/provider suites (114 tests) were
additionally re-run with `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`
removed from the environment to prove normal tests use deterministic
provider/event fixtures and make no paid or network calls. Test output
carries only pre-existing dependency deprecation warnings (Alembic,
Starlette/httpx, AnyIO); they are not failures.

Before the acceptance follow-up, the full `pnpm quality` gate passed (root
Markdown/link/shell checks, root tests, API suite at 498 passed, mobile
lint at 0 errors with 45 warnings, mobile suite at 522 passed, typecheck,
and web export). An earlier fix round found 15 mobile-lint errors in
Phase 11 files; the quality-fix wave (`acfc1c9`) resolved all 15 with no
behavior change and a clean re-review, leaving the warning count
untouched.

The PR review fixes add a chunked-body regression proving `/agent` stops
reading immediately after exceeding 32 KiB, and two pending-to-terminal
status-check regressions for failed and superseded suggestions. The latter
prove the agent card releases its submitting state, manual controls recover,
and no tool continuation or workflow transition is sent. Waiters settle before
the saved pending record is cleared, including the reload ordering path.

## 9. Acceptance record

Automated tests use deterministic provider/event fixtures and deferred
promises. They prove decision validation, owner hiding, authorization,
argument allowlists, run/tool identities, stale state, replay, unknown
tools, cancellation, duplicate-write prevention, per-workflow isolation,
session teardown, streamed/incomplete arguments, editing/removal, stale
and session guards, recovery, accessibility attributes, and zero todos
before existing confirmation. Those results do not substitute for
manually observing the platform UIs or the live model.

| Target | Date/runtime | Question selection and form response | Editable/removable suggestions | Interruption/replay | Malformed/unknown fallback | Sign-out isolation, accessibility, explicit confirm |
| --- | --- | --- | --- | --- | --- | --- |
| Automated API and mobile tests | 2026-09-10, PostgreSQL `todo_test` with Python 3.14 (501 API tests) and Jest with `jest-expo` (522 mobile tests, 17 suites) | ☑ catalog-only choice, fixed local copy, 1–200 answer bounds, fingerprint behavior | ☑ edited titles through `submit_tasks`; edited-title ack emits no-write finish without regeneration | ☑ cancellation closes provider work; interrupted clarification restarts explicitly; `Retry saved request` reuses the stored ID | ☑ unknown names/versions/extra keys, mismatched IDs, stale revisions fail closed with safe errors | ☑ owner-hidden lookup, session teardown, parser-level a11y attributes, zero todos before `confirm` |
| Live model | 2026-09-10, `openrouter/free`, 14 calls of 500 authorized | ☑ five valid choices: four date, one location; three choice failures | ☑ three valid proposals (5, 5, 8 titles); three suggestion failures; explicit retry recovered the hiking flow | No automatic retries; recovery was user-driven | Invalid outputs failed safely; not all failure causes were captured | Web birthday/hiking and native birthday flows completed |
| Web UI | 2026-09-10, Expo 57, in-app browser | ☑ live date/location forms submitted | ☑ live titles edited/removed, then reviewed and confirmed | ☑ reload restored saved proposal without another provider call; controlled delayed run cancelled and unlocked manual controls | Automated coverage only | ☑ double-click confirmation created one set; sign-out during delayed run stayed signed out; labels/focus observed, full screen-reader audit pending |
| iOS Simulator UI | 2026-09-10, iPhone 17 Pro, iOS 26.5, Expo Go 57 | ☑ live date form submitted | ☑ live proposal edited from 8 to 7 titles; separate fixture proposal reduced from 3 to 2 | ☑ controlled delayed run cancelled and unlocked manual controls | Automated coverage only | ☑ explicit confirmation created seven live todos; sign-out during delayed run stayed signed out; accessible labels observed, full VoiceOver audit pending |

Acceptance exposed a real SDK integration mismatch: assistant-ui generates
opaque run IDs, not necessarily UUIDs. The API now accepts bounded URL-safe
run IDs while retaining UUID workflow ownership checks and unambiguous tool
correlation. The fix has regression coverage for an actual SDK-style ID,
continuation, and invalid IDs. The full API suite passed **501 tests** and
the mobile suite passed **522 tests across 17 suites** after the fix.

Live requests used the existing ignored API environment file, without
copying or logging the key. Eight clarification calls yielded five valid
choices; six suggestion calls yielded three valid proposals. Two earlier
acceptance-wrapper configuration failures made no external calls and are
excluded from those totals. At least two suggestion failures and one
choice failure were classified as invalid output; other failures are not
assigned an unobserved cause. These small-sample results demonstrate
successful integration and safe failure, not dependable model availability.

The synthetic local acceptance account ended with exactly 17 todos:
15 from three live-model plans and two from a fixture plan. Read-only API
checks confirmed the native live proposal added nothing before confirmation
and exactly seven afterward. Cancellation/sign-out added nothing. Controlled
20-second fixture delays made interruption checks repeatable on both UIs;
they are not counted as live provider checks. No malformed/unknown tool was
manually injected into a platform UI; that remains automated coverage.

## 10. Honest limits

There is deliberately no durable agent-run journal. Run and tool IDs
correlate one request and reject duplicates within it; they are not
model-call idempotency keys. Retrying even the same run ID after an
interrupted clarification or process restart can repeat the decision call
and its cost. Recovery is always an explicit user action (**Try agent
again** starts a new paid choice request; **Retry saved request** first
recovers the exact saved outcome and never silently creates a new provider
request) and the UI says so. There is no automatic retry after timeout,
malformed output, cancellation, disconnect, or uncertain completion, no
persisted conversation, and no background run resumer. Reload between
clarification and its result restarts the agent interaction, while the
durable workflow and any reserved/saved suggestion remain recoverable
through the existing screen.

No production quota, pruning, telemetry, or exactly-once provider billing
is claimed; Phase 13 owns that measured hardening. Android, physical
devices, production deployment, token refresh during a run, reconnection,
and a full assistive-technology audit remain unobserved; package support
claims are not evidence for them. Phase 12 owns
full cross-platform E2E.
