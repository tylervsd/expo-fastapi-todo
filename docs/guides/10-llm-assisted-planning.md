# Phase 10: LLM-assisted planning with Python and OpenRouter

Phase 10 adds one bounded model call to the existing guided todo workflow. A
signed-in user can ask for a proposal of todo titles for a goal such as
`birthday party`, edit that proposal, and submit the reviewed titles through
the existing workflow. The existing `confirm` action remains the only boundary
that creates todos.

This guide describes the implementation on
`codex/phase-10-llm-assisted-planning`. It is not a checkpoint claim: the
automated suites and provider smoke are recorded below, while the interactive
web and iOS acceptance rows remain incomplete for this pass.

## 1. Configuration stays in Python

The API reads two required variables when a fresh provider call is needed:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`

Neither has a default, and neither is exposed to Expo. The repository includes
only blank names in [`apps/api/.env.example`](../../apps/api/.env.example).
Keep the local `.env` ignored and untracked. Load it explicitly into the
backend process, for example:

```bash
set -a
. apps/api/.env
set +a
uv run --directory apps/api uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Do not print the file or its values. Automated tests inject a fake suggestion
callable or use an HTTPX mock transport; they do not need credentials or
provider network access.

## 2. The provider boundary is small and bounded

Only the Python service calls OpenRouter. For a fresh request it sends the
canonical workflow goal and a fixed system instruction. It does not send an
authentication token, user identity, workflow history, or the local draft.
The request uses the configured model and the following OpenRouter options:

- `provider.require_parameters: true`;
- `response_format.type: json_schema` with `strict: true`;
- an exact object containing only `titles`, an array of 2–10 strings;
- at most 120 Unicode code points per title;
- `max_tokens: 400`.

The API streams and rejects a response over 16 KiB before parsing it. The
HTTPX connect, write, and pool timeouts are 5 seconds, read timeout is 25
seconds, and the complete coroutine has a hard 30-second deadline. The mobile
suggestion POST has its existing client request timeout overridden to 35
seconds; ordinary requests retain their 5-second default.

The provider treats non-success HTTP responses and an OpenRouter top-level
`error` object as provider failures, including when the HTTP status is 200.
It parses the response JSON, validates the structured object with Pydantic,
then reuses the workflow's `create_submit_tasks` title validator. Invalid
output is never exposed as a proposal. Failure messages contain no provider
body, prompt, credentials, or generated titles, and there is no automatic
paid retry.

## 3. Request identity and short transactions

Suggestions are a separate resource from the workflow snapshot because the
workflow remains in `COLLECT_TASKS` until the user submits reviewed titles.
The request journal stores an owner-scoped request identity, SHA-256
fingerprint, base revision, step ID, status, validated titles when ready, and
a safe failure code. It stores no timestamp, prompt copy, or raw model output.

The request contract is exact:

```json
{
  "request_id": "00000000-0000-0000-0000-000000000002",
  "expected_revision": 2,
  "step_id": "00000000-0000-0000-0000-000000000001:COLLECT_TASKS"
}
```

Reservation locks only the owner-scoped workflow, validates the definition,
state, revision, and step, and commits a `pending` row. The transaction ends
before the provider is called. Finalization uses a second short transaction
and publishes titles only if the same owner, workflow, request, revision,
step, and newest-request identity still match. A newer request supersedes an
older pending request; a late older response is discarded as
`stale_suggestion`. No workflow revision, workflow context, or todo changes
when a suggestion is reserved or finalized.

An identical ready or failed request replays its saved result without checking
current provider configuration or making another call. An active pending
request reports `suggestion_in_progress`; an older request reports
`stale_suggestion`; reusing a retained request ID with a different fingerprint
reports `request_id_reused`. `GET /todo-workflows/{id}/suggestions` is
owner-scoped and returns the current record only while its revision and step
still match the workflow. Missing and other-owner workflows remain
indistinguishable 404 responses.

The response has its own strict `contract_version: 1`:

```json
{
  "contract_version": 1,
  "workflow_id": "00000000-0000-0000-0000-000000000001",
  "request_id": "00000000-0000-0000-0000-000000000002",
  "base_revision": 2,
  "step_id": "00000000-0000-0000-0000-000000000001:COLLECT_TASKS",
  "status": "ready",
  "proposed_titles": ["Choose a date", "Invite guests"],
  "error_code": null
}
```

The mobile transport rejects unknown versions, malformed fields, invalid title
counts, and cross-workflow identities before updating local state.

## 4. Review before persistence and confirmation

The task-breakdown template exposes **Suggest todos** based on the supported
`task_breakdown` view. It does not duplicate the backend state machine. A
ready proposal seeds an untouched empty multiline draft. Every title remains
editable and removable; a changed draft is never replaced automatically.
When a saved proposal conflicts with local text, the user must explicitly
choose **Apply saved suggestions** and confirm replacement.

A pending record offers **Check status** and an explicit warning before
**Start another request**. A failed record offers a new-ID retry. A retained
local request offers **Retry saved request** or **Discard saved request**; the
request is never submitted automatically after restart or re-login. The
component captures the owner, session epoch, workflow, revision, step, request
identity, and a local draft edit counter before applying asynchronous results.
Late results after typing, navigation, sign-out, same-owner re-login, a newer
request, or unmount therefore leave the current draft and session alone.

Submitting the edited multiline draft still uses Phase 9's durable `advance`
request and its 2–10 title bound. Suggestion persistence does not advance the
workflow. Only the existing explicit **Confirm** action creates todos, inside
Phase 9's transactional action boundary.

## 5. Verification performed

The following checks were run on 2026-09-10 (America/Los_Angeles):

```bash
TEST_DATABASE_URL='postgresql+psycopg://todo_test:todo_test@127.0.0.1:5433/todo_test' \
  uv run --directory apps/api python -m pytest tests -v
pnpm --dir apps/mobile test --runInBand
pnpm quality
```

The PostgreSQL-backed API suite passed **398/398** tests. The mobile suite
passed **375/375** tests. `pnpm quality` passed its Markdown/link, shell,
contract, doctor, mobile lint/typecheck/tests, API lint/tests, and web-export
steps. The test output included 14 pre-existing dependency deprecation
warnings (Starlette/httpx, AnyIO, and Alembic); they were not test failures.
The requested test database was already provided by the Phase 9 container on
port 5433; starting a second `db-test` container was skipped because that port
was occupied. The suite still verified the isolated `todo_test` database.

One additional live provider request was made from Python on 2026-09-10. The
configured model identifier was `openrouter/free`. The structured-output
request was accepted and returned valid JSON with 9 titles, demonstrating
required-parameter/schema compatibility for that configured model on that
observation date. This was a provider smoke, not a full application journey;
no key, prompt, raw response, or title text was recorded.

## 6. Acceptance record

Automated tests use deterministic fake providers and deferred promises. They
prove provider validation and bounds, database ownership/replay/supersession,
stale-result protection, transport parsing, editable-draft preservation,
recovery controls, accessibility labels/announcements, and zero todos before
confirmation. Those results do not substitute for manually observing both
platform UIs.

| Target | Date/runtime | Birthday suggestion and edit/remove | Refresh without regeneration | Failure/lost-response recovery | Superseded result and isolation | Accessibility and confirmation |
| --- | --- | --- | --- | --- | --- | --- |
| Provider smoke | 2026-09-10, Python 3.14, configured `openrouter/free` | ☑ provider returned valid structured JSON (9 titles); full UI review unobserved | — | — | — | — |
| Backend/API tests | 2026-09-10, PostgreSQL `todo_test`, pytest 9.1.1 | ☑ mocked ready proposal; edited titles are submitted through the existing action path | ☑ ready records are returned without generation; replay does not call provider twice | ☑ timeout, invalid output, pending, failed replay, and saved request recovery covered | ☑ owner isolation, revision/step checks, newer-request supersession, and late-result discard covered | ☑ confirmation-only todo creation and zero-todo suggestion states covered |
| Web UI | — | ☐ unobserved in this pass; no interactive browser session was available | ☐ unobserved | ☐ unobserved | ☐ unobserved | ☐ unobserved |
| iOS Simulator UI | — | ☐ unobserved in this pass; available devices were shutdown and no interactive Maestro run was completed | ☐ unobserved | ☐ unobserved | ☐ unobserved | ☐ unobserved |

The web static export completed during `pnpm quality`, but a successful export
is not evidence of interactive browser behavior. An iPhone 17 Pro simulator
was available through `xcrun simctl` but was shutdown; no UI acceptance claim
is made for it. The remaining rows require a running API/mobile session and
interactive browser or simulator automation. In particular, this pass does
not claim observed focus movement, live announcements, sign-out isolation,
manual fallback, invalid-output/timeout screens, lost response retry, or
late superseded-result behavior in a real UI.

## 7. Honest limits

This is intentionally a synchronous request/response teaching flow. A server
restart can leave a journal row pending until the user explicitly starts a new
request; no worker resumes it. Different request IDs can trigger concurrent
provider calls, and recovery after an uncertain provider failure can duplicate
billing. The request journal has no Phase 10 pruning policy. Quotas,
retention, cancellation propagation, and production diagnostics belong to a
later hardening phase.
