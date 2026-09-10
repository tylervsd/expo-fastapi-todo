# Phase 10: LLM-Assisted Planning Design

**Status:** Draft for review  
**Base:** Phase 9 at `12cd7f5`  
**Checkpoint:** `phase-10-llm-assisted-planning` only after implementation, verification, acceptance, integration, and CI

## Goal

A signed-in user can start the existing guided workflow with a goal such as “birthday party,” reach **Break it into smaller todos**, and request 2–10 suggested todo titles from OpenRouter. The suggestions remain an untrusted, editable proposal. The user may edit or remove them, the existing `submit_tasks` action saves the reviewed draft, and only the existing explicit `confirm` action creates todos.

This phase teaches one bounded model call inside the Python service while retaining the deterministic Phase 9 workflow and screen templates.

## Non-goals

- Agents, tool calling, streaming, workers, queues, Temporal, or a general AI framework.
- Model-generated layouts, autonomous todo creation, automatic provider retries, or provider calls from clients.
- Replacing Phase 9 revisions, action idempotency, pending-write recovery, discovery, or confirmation transactions.
- Rate limits, quotas, prompt retention controls, or complete cost telemetry; Phase 13 owns production hardening.

## Chosen design

Keep workflow definition version 1 unchanged. Suggestions are a separate resource for the existing `COLLECT_TASKS` step because that definition requires `proposed_todo_titles` to stay empty until `submit_tasks`. A narrow `todo_workflow_suggestion_requests` journal records each request identity and outcome. Its newest internal row for an owner/workflow is the active proposal. This preserves retry evidence without copying Phase 9’s full workflow-action machinery into the model boundary.

The API reserves a suggestion request in a short transaction, releases all database locks, calls OpenRouter, then conditionally records the outcome in another short transaction. Finalization succeeds only when the owner, workflow definition, `COLLECT_TASKS` state, revision, step ID, and active suggestion request still match. A newer request supersedes an older request; a late older result is discarded.

The existing task-breakdown component gains **Suggest todos**, selected from the supported `view.type` rather than by branching on backend business state. Ready titles seed its multiline draft only while that exact step’s local draft remains pristine. Typing, removing text, navigating, signing out, or changing steps prevents a late response or background refetch from replacing local text. Provider work disables suggestion and workflow actions in that mounted screen, but server guards remain authoritative across devices.

## Data model and compatibility

Create `todo_workflow_suggestion_requests` with:

- internal identity for ordering plus unique `(owner_id, workflow_id, request_id)`, and an owner-preserving workflow foreign key with cascade;
- `request_id` UUID and SHA-256 `request_fingerprint` retained for every request;
- `base_revision` integer and `step_id` text;
- `status` constrained to `pending`, `ready`, `failed`, or `superseded`;
- `proposed_titles` JSONB, empty unless ready, with Python validation on every read;
- nullable safe `error_code`, constrained to `not_configured`, `timeout`, `provider_unavailable`, or `invalid_output` when failed.

No timestamps, prompt copies, or raw model output are stored. A new row supersedes older pending rows; prior identities remain available for replay/reuse checks. Existing workflows and definition version 1 remain readable without backfill. Existing web/iOS clients keep working because workflow envelopes and templates do not change.

The suggestion response has its own `contract_version: 1` and exact fields:

```json
{
  "contract_version": 1,
  "workflow_id": "00000000-0000-0000-0000-000000000001",
  "request_id": "00000000-0000-0000-0000-000000000002",
  "base_revision": 2,
  "step_id": "00000000-0000-0000-0000-000000000001:COLLECT_TASKS",
  "status": "ready",
  "proposed_titles": ["Choose a date", "Invite guests", "Order a cake"],
  "error_code": null
}
```

Unknown suggestion contract versions fail closed in the transport and leave the local draft unchanged. Phase 9’s unsupported workflow-definition and unsupported-view behavior remains unchanged.

## API and request lifecycle

`POST /todo-workflows/{workflow_id}/suggestions` accepts an exact object:

```json
{
  "request_id": "00000000-0000-0000-0000-000000000002",
  "expected_revision": 2,
  "step_id": "00000000-0000-0000-0000-000000000001:COLLECT_TASKS"
}
```

The canonical fingerprint includes operation, workflow ID, expected revision, step ID, and the workflow’s canonical goal title. It excludes credentials and request ID. Request IDs are owner/workflow scoped.

Reservation locks the owner-scoped workflow, validates definition/state/revision/step, and inspects the unique request identity. An identical ready or failed request replays its saved outcome without checking live provider configuration or making a call. An identical active pending request returns `409 suggestion_in_progress`; an older pending or superseded request returns `409 stale_suggestion`. Reusing any retained ID with another fingerprint returns `409 request_id_reused`. A new ID at the same valid step inserts `pending`, becomes active by internal ordering, supersedes older pending work, and may begin a paid call.

`GET /todo-workflows/{workflow_id}/suggestions` is owner-scoped. It returns the current record only when its base revision and step still match the current `COLLECT_TASKS` workflow; otherwise it returns `404`. A ready record restores suggestions after refresh without generation. A pending record explains that the original call may still finish. A failed record supports manual entry or an explicit retry with a new request ID.

Fresh successful POSTs return `201` with the proposal; ready replays return the same body with `200`. Failed outcomes and replays use FastAPI’s exact `detail: {code, message}` envelope with `502` (`provider_unavailable`, `invalid_output`), `504` (`timeout`), or `503` (`suggestions_not_configured`). Provider configuration is checked only after reservation says a call is needed; a missing key/model records `not_configured`, while replay remains available without live configuration. Stale state before reservation returns Phase 9’s existing conflict; stale/superseded state after the paid call returns `409 stale_suggestion` and never publishes titles. Missing or other-owner workflows remain indistinguishable `404`.

There are no automatic paid retries. After a known failed outcome the user may create a new request ID. After a timeout or lost response, retrying the same ID first recovers a ready/failed result or reports pending. A process can fail after OpenRouter accepts/bills a call but before the result is stored. Database idempotency therefore cannot promise exactly-once provider execution or billing; an explicit new request can pay twice.

## OpenRouter boundary

Promote `httpx` from the dev group to the runtime dependencies and implement one thin asynchronous client. Do not add an OpenRouter SDK. Live use requires both `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`; neither has a default and neither is exposed to Expo. Document names only in `apps/api/.env.example`. Phase 10 begins the rule that secrets, complete prompts, raw responses, and generated titles are not logged by default; later retention policy work does not defer that baseline.

Send only the canonical workflow goal plus a short fixed instruction. Do not log the key, full prompt, raw response, or generated titles by default. The request uses the configured model, `provider.require_parameters: true`, and `response_format.type: json_schema` with `strict: true`. Its schema is an exact object with one `titles` array of 2–10 strings and no additional properties. Python still parses and validates the body with Pydantic and the existing title validator. A top-level OpenRouter `error` body is an error even with HTTP 200.

Cap the goal at the existing 120 Unicode code-point title limit, output at 10 titles, each title at the same limit, response bytes at 16 KiB, and requested output at 400 tokens. Use a hard 30-second coroutine deadline around the asynchronous request plus 5-second connect/write/pool and 25-second read timeouts. The mobile suggestion call alone uses 35 seconds; all existing requests retain their 5-second default.

The configured model must be verified manually against the structured-output endpoint before acceptance. The repository never invents a fixed model name because availability and structured-output support can change.

## Client behavior and recovery

The task-breakdown screen starts with its existing editable multiline field. The client offers **Suggest todos** for the supported `task_breakdown` view; the server alone enforces `COLLECT_TASKS`. The request uses a UUID and the current revision/step. Extend the existing owner-scoped pending-write store with a `suggest` variant so restart or a lost response preserves the exact request identity; it is never submitted automatically.

On mount or explicit retry, fetch the authoritative workflow first, then fetch its suggestion record. A ready proposal seeds an untouched empty draft and moves focus to the field. A failed or pending record announces a concise status and offers manual entry. Pending offers **Check status** plus an explicit **Start another request** warning that the earlier call may still be billed; failed offers **Try suggestions again** with a new UUID. A retained local suggestion request offers **Retry saved request**. To submit a manual draft while that record is unresolved, the user explicitly discards it after the same warning. The following `submit_tasks` revision advance makes late finalization stale; the edit counter also prevents a response arriving before submission from replacing text.

The component tracks a monotonically increasing local draft edit counter and captures it when generation or GET starts. It applies returned titles only if session epoch, owner, workflow ID, step ID, revision, and edit counter still match and the draft is empty. Otherwise it keeps the user’s text and offers **Apply saved suggestions**; replacing an edited draft requires an explicit replacement confirmation. No response from a previous user/session writes cache or local state.

Submitting edited titles continues through Phase 9’s durable `advance` request and still requires 2–10 titles after edits/removals; Phase 10 does not add a one-title breakdown path. The suggestion row does not create todos, populate workflow context, or advance a revision. Confirmation remains the sole todo-creation boundary and retains Phase 9’s transactional replay behavior.

## Testing and acceptance

Normal CI injects a fake provider; it never requires credentials, network access, paid calls, or exact generated wording. Unit tests cover exact OpenRouter payloads, strict Python validation, HTTP-200 error bodies, size limits, timeout, and redacted errors. PostgreSQL/API tests cover owner isolation, reservation replay, pending conflict, failed replay, supersession, stale revision/state, late-result discard, refresh recovery, and zero todos before confirmation.

Mobile transport/component tests use deterministic deferred promises for the 35-second override, pending-record recovery, pristine-draft seeding, edit/remove preservation, stale session/result rejection, explicit retry, manual fallback, accessibility labels/live announcements, and confirmation-only writes. Existing Phase 9 workflow and quick-add tests remain green.

Manual acceptance on web and iOS Simulator uses a deliberately configured supported model and records the model identifier and observation date. Verify the birthday-party journey, edits/removals, refresh without regeneration, invalid output/timeout recovery, lost-response retry, superseded late result, sign-out isolation, and explicit confirmation. Record any unobserved scenario rather than claiming it passed.

## Honest limits

This is a synchronous request/response teaching flow. A server restart can leave `pending` until the user explicitly starts a new request; there is no worker to resume it. Different request IDs can trigger concurrent paid calls, and explicit recovery after an uncertain failure can duplicate cost. The small request journal grows with explicit attempts and has no Phase 10 pruning policy. One active proposal per workflow is sufficient; quotas, cancellation propagation, retention cleanup, and production diagnostics wait for a measured need.

## References

- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [OpenRouter errors and debugging](https://openrouter.ai/docs/api_reference/errors-and-debugging)
