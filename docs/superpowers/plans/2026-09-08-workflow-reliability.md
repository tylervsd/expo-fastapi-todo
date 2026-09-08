# Phase 9 Workflow Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Approved by the user (2026-09-07, America/Los_Angeles). Implementation has not started.

**Branch:** `codex/phase-09-workflow-reliability`, based on `e89abcf` on `main`.

**Goal:** Let users discover and resume plans and safely retry interrupted starts/actions without duplicate writes or stale workflow advancement.

**Architecture:** Extend the existing Python service, PostgreSQL repository, and Expo template host. Record accepted request outcomes transactionally, compare revisions in SQL, and retain one owner-bound pending request on the client until its outcome is resolved. Keep domain snapshots separate from presentation responses.

**Tech Stack:** Existing FastAPI/Pydantic, SQLAlchemy/Alembic, PostgreSQL 18.6, Expo SDK 57, React Native, TanStack Query, pytest, and Jest. Add only SDK-compatible `expo-crypto` for UUID generation.

**Spec:** [Phase 9 Workflow Reliability Design](../specs/2026-09-08-workflow-reliability-design.md). Read the entire spec before executing any task.

## Global constraints

- Existing quick add, `/todos`, authentication, four templates, acyclic state graph, and title/count limits retain their behavior.
- Revision range is `0..2147483647`; definition and view-contract version are independently `1`.
- Preserve `{workflow_id}:{state}` step IDs; request IDs and revisions have separate purposes.
- No LLM, agent integration, worker, offline queue, arbitrary layouts, or automatic mutation retries.
- Only accepted context survives reload; unsubmitted input need not persist.
- A pending write must be durably stored and read back before network submission. Storage failure blocks sending.
- Domain snapshots, workflow changes, created todos, and idempotency results commit or roll back together.
- Do not commit placeholder outcomes. Replay precedes stale/terminal checks.
- All cache writes, including query results, reject older revisions and obsolete authentication epochs.
- Read the exact [Expo SDK 57 docs](https://docs.expo.dev/versions/v57.0.0/) required by `apps/mobile/AGENTS.md` before mobile code changes.
- Use a fresh isolated worktree at execution time. Preserve unrelated `.pi/` and `AGENTS.md` files. Do not claim earlier manual acceptance has occurred.
- Sol controls architecture and reviews; Luna performs the bounded tasks below. Escalate integration/debugging to Terra, and return architecture/scope questions to Sol.

## Execution order and file ownership

Execute Tasks 1–6 sequentially because their contracts are dependent. Use a fresh Luna implementer and Sol review per task when following subagent-driven development. Each task includes a red/green cycle and a focused commit; do not dispatch overlapping edits to `main.py`, `todoApi.ts`, or the workflow screen.

| Task | Deliverable |
| --- | --- |
| 1 | Versioned snapshots and database schema |
| 2 | Transactional start/action replay and discovery service |
| 3 | HTTP contracts and typed client transport |
| 4 | Durable pending-request storage and session safety |
| 5 | Discovery, resume, retry, and cache reconciliation UI |
| 6 | Regression checks, guide, acceptance, and branch review |

## Task 1: Versioned snapshots and durable schema

**Files:** Modify `apps/api/app/workflow_domain.py`, `apps/api/app/workflow_repository.py`, `apps/api/app/workflow_service.py`, `apps/api/tests/conftest.py`, `apps/api/tests/test_workflow_domain.py`, `apps/api/tests/test_workflow_persistence.py`, and `apps/api/tests/test_workflow_presentation.py`. Create `apps/api/alembic/versions/2026090901_add_workflow_reliability.py`.

**Interfaces:** Add `revision: int` and `definition_version: int` to `WorkflowSnapshot`; add constants `MAX_WORKFLOW_REVISION = 2147483647` and `CURRENT_WORKFLOW_DEFINITION_VERSION = 1`. Preserve existing `transition(snapshot, command)` and have it reject unsupported `snapshot.definition_version` before dispatching the unchanged graph. `_snapshot_from_row` carries both fields. The presentation mapper stays revision-independent.

- [ ] Add a failing domain test using an existing valid snapshot fixture, with explicit version dispatch:

```python
from dataclasses import replace

assert snapshot.revision == 0
with pytest.raises(UnsupportedWorkflowDefinition):
    transition(replace(snapshot, definition_version=2), Cancel())
```

- [ ] Add migration tests that upgrade Phase 8 rows in each state, assert revision `0`/definition `1` and preserved context/results, and reject negative or unsafe revisions. Run the existing migration harness against the isolated `todo_test` database. Add rollback-to-Phase-8/re-upgrade coverage without deleting todos or workflows.
- [ ] Run `uv run --directory apps/api python -m pytest tests/test_workflow_domain.py tests/test_workflow_persistence.py tests/test_workflow_presentation.py -v`; confirm failures concern the new fields/schema.
- [ ] Add mapped columns and the two request tables from the spec in `workflow_repository.py`. Use the exact unique and ownership-preserving foreign keys, JSONB object checks, and 64-character lowercase hexadecimal fingerprint checks. Start-request FK is deferred; action-request FK is composite `(workflow_id, owner_id)`.
- [ ] Implement migration after `2026090801`, backfill existing rows, then enforce non-null/default/check constraints. Update the test fixture's `REVISION` to `2026090901` and verify dependent records are truncated through its existing cascade.
- [ ] Implement pure `snapshot_to_record(snapshot) -> dict[str, object]` and `snapshot_from_record(record) -> WorkflowSnapshot` in the repository. Encode UUIDs as strings and tuples as arrays; validate exact keys, bounds, version/state, title/count invariants, and completion data on decode. No HTTP view models enter storage.
- [ ] Round-trip active, cancelled, and completed snapshots in tests; reject malformed persisted records. Update all existing constructors/fixtures to supply the new metadata. Run the focused tests green and commit the named files as `feat: add workflow revision and request storage`.

## Task 2: Transactional replay, conflicts, and discovery

**Files:** Modify `apps/api/app/workflow_repository.py`, `apps/api/app/workflow_service.py`, `apps/api/tests/test_workflow_persistence.py`. Create `apps/api/tests/test_workflow_reliability.py`.

**Interfaces:** Service exports:

```python
def start_workflow(session: Session, owner_id: int, title: str,
                   request_id: UUID) -> WorkflowSnapshot: ...

def advance_workflow(session: Session, owner_id: int, workflow_id: UUID,
                     command: WorkflowCommand, *, request_id: UUID,
                     expected_revision: int,
                     step_id: str) -> WorkflowSnapshot | None: ...

def list_active_workflows(session: Session,
                          owner_id: int) -> list[WorkflowSnapshot]: ...
```

The ellipses above denote interface signatures only. Implement the algorithms below. Keep `get_workflow` unchanged apart from metadata/version validation. Define typed exceptions `StaleWorkflowStep`, `RequestIdReused`, `RevisionExhausted`, and `UnsupportedWorkflowDefinition` for HTTP mapping in Task 3.

- [ ] Write a failing replay test with a committed owner created using the existing test helper:

```python
request_id = uuid4()
with session_factory() as session:
    first = start_workflow(session, owner_id, "Party", request_id)
with session_factory() as session:
    replay = start_workflow(session, owner_id, "Party", request_id)
assert replay == first
with session_factory() as session:
    with pytest.raises(RequestIdReused):
        start_workflow(session, owner_id, "Different", request_id)
```

- [ ] Add real PostgreSQL tests for identical start/action races, distinct actions at one revision, confirmation replay after terminal completion, rollback after todo insertion, owner isolation, and discovery filtering/order. Each racing worker uses its own Session; use a bounded `threading.Barrier` before service entry and `future.result(timeout=10)` rather than sleeps. Commit setup rows before launching workers. Assert database row counts and revisions, not just response status.
- [ ] Run `uv run --directory apps/api python -m pytest tests/test_workflow_reliability.py -v` and observe the missing replay behavior.
- [ ] Implement canonical request fingerprints in the service with stdlib only:

```python
encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
fingerprint = hashlib.sha256(encoded).hexdigest()
```

Build `payload` exactly as specified: canonical titles, significant array order/duplicates, operation and action preconditions, excluding request ID and credentials.

- [ ] Implement start in one transaction: construct the complete initial snapshot; insert request with `on_conflict_do_nothing(...).returning(...)`; on a win insert the referenced workflow; on a loss select the request in a subsequent statement, compare fingerprint, and decode its saved snapshot. Roll back all exceptions. Never combine the conflict insert and replay select into one CTE.
- [ ] Implement advance in one transaction: lock owner-scoped workflow; read existing request; return matching recorded outcome or reject mismatch; validate version/step/revision/terminal/ceiling/action; create todos when confirming; perform conditional update; insert full accepted request outcome; commit. A missing workflow returns `None`. Rejections roll back everything.

The conditional update must include this predicate and increment atomically:

```python
.where(WorkflowRow.public_id == workflow_id,
       WorkflowRow.owner_id == owner_id,
       WorkflowRow.revision == expected_revision)
.values(revision=WorkflowRow.revision + 1, **accepted_fields)
.returning(WorkflowRow)
```

Require exactly one returned row. Ensure SQLAlchemy's identity map is refreshed after the SQL update before serializing the accepted snapshot.

- [ ] Implement unpaginated owner-scoped active discovery ordered by descending internal ID, with no mutation or row lock. Reject unsupported stored definitions according to the spec.
- [ ] Test a start failure between request insert and workflow creation, and an action failure after todo insertion; verify no orphan/outcome remains and retry succeeds. Test replay at the revision ceiling and rejection of a new request there. Update affected service callers in the focused tests to supply explicit request metadata. Run reliability, domain, presentation, and persistence suites green; commit as `feat: make workflow mutations resumable and idempotent`.

## Task 3: HTTP and client contracts

**Files:** Modify `apps/api/app/main.py`, `apps/api/tests/test_workflows.py`, `apps/api/tests/test_validation.py`, `apps/mobile/src/todos/todoApi.ts`, `apps/mobile/src/todos/todoApi.test.ts`, `apps/mobile/src/auth/authenticatedApi.ts`, `apps/mobile/src/auth/authenticatedApi.test.ts`. Update workflow fixtures in `apps/mobile/src/auth/AuthProvider.test.tsx`, `apps/mobile/src/TodoExperience.test.tsx`, and `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx`.

**Interfaces:** Preserve `TodoWorkflowAction` as the inner command. Add:

```ts
type WorkflowStartRequest = { request_id: string; title: string };
type WorkflowActionRequest = {
  request_id: string;
  expected_revision: number;
  step_id: string;
  action: TodoWorkflowAction;
};
```

Transport signatures become `startTodoWorkflow(request, options)`, `advanceTodoWorkflow(id, request, options)`, and `listTodoWorkflows(options) -> Promise<{ items: TodoWorkflow[] }>`. Authenticated API mirrors them as `startWorkflow`, `advanceWorkflow`, and `listWorkflows`, preserving captured Bearer handling. Keep one exported `TodoWorkflowScreenApi` contract rather than inconsistent duplicate declarations.

- [ ] Add failing API tests for exact start/action envelopes, missing/extra fields, strict safe integers/UUIDs, canonical fingerprint replay, discovery default/invalid status, all conflict codes, owner-hidden 404, and database 503. Pin `201` on start replay and `200` on action replay.
- [ ] Add client tests asserting the exact outgoing nested action body:

```ts
expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({
  request_id: requestId,
  expected_revision: 2,
  step_id: `${workflowId}:COLLECT_TASKS`,
  action: { action: "submit_tasks", titles: ["Invite guests", "Buy cake"] },
});
```

Use existing `response(...)` and fetch fake helpers with a valid versioned snapshot. Add missing metadata, unsafe integer, unknown contract, malformed known view, error-code, and list-validation cases.

- [ ] Run backend workflow/validation tests and mobile API/authenticated-API tests red. Implement Pydantic envelopes and metadata, route discovery before any ambiguous dynamic route, and map each typed conflict to the spec's `detail: {code,message}` shape. Preserve unrelated todo/auth error contracts.
- [ ] Implement the exact known/unsupported contract union from the spec. Check the stable prefix before version dispatch; known version uses strict exact-object validation, unknown positive version returns metadata-only unsupported UI. Preserve Phase 8 unknown-template behavior. Never fabricate business fields for unsupported contracts.
- [ ] Extend `TodoApiError` with an optional typed workflow conflict code. Parse codes only for relevant workflow operations; retain existing auth and CRUD semantics. Validate every discovery item before returning the list and forward query abort signals.
- [ ] Thread request objects through authenticated transport and update all touched fixtures. Run the focused transport/API tests. The screen integration follows in Tasks 4–5; defer the whole-app typecheck until that integration and never fabricate temporary request IDs just to satisfy old call sites. This is an intermediate contract checkpoint, not a runnable feature checkpoint. Commit as `feat: expose workflow recovery contracts`.

## Task 4: Durable pending requests and authentication epochs

**Files:** Create `apps/mobile/src/todoWorkflows/pendingWorkflowWrite.ts` and `apps/mobile/src/todoWorkflows/pendingWorkflowWrite.test.ts`. Modify `apps/mobile/src/auth/AuthProvider.tsx`, `apps/mobile/src/auth/AuthProvider.test.tsx`, `apps/mobile/package.json`, and `pnpm-lock.yaml`.

**Interfaces:** Export the spec's `PendingWorkflowWrite` union and a `PendingWriteStore` with `read(ownerId)`, `save(record)`, and `clear(ownerId, requestId)` asynchronous methods. Reads validate exact shape, owner, duplicate request-ID fields, UUIDs, and canonical payload. Clear compares the current record's request ID before deleting it. Export an injected memory store for tests. `AuthProvider` supplies an opaque numeric `sessionEpoch` and `isSessionCurrent(epoch): boolean` to the workflow shell; change epoch on restore/login/logout/replacement, never persist a bearer token in workflow storage.

- [ ] Add failing tests for exact Unicode round trips, invalid/cross-owner data, storage exceptions, read-back mismatch, matching-only clear, stale clear after a new record, and re-authentication as the same user. Test a maximum valid ten-title payload without truncation.
- [ ] Run `pnpm --dir apps/mobile test --runInBand src/todoWorkflows/pendingWorkflowWrite.test.ts src/auth/AuthProvider.test.tsx` red.
- [ ] Read the required SDK docs, then run `pnpm --dir apps/mobile exec expo install expo-crypto`. Use `randomUUID()` through an injectable generator. Preserve all existing dependency pins except the justified new package and resulting lockfile changes.
- [ ] Implement owner-keyed localStorage and SecureStore adapters with surfaced errors. Save serializes exact request JSON, writes, reads back, and rejects mismatch. Reuse the installed SecureStore API, not the token-storage wrapper that swallows web failures.
- [ ] Implement the before-send sequence, with the final live-session check after persistence:

```ts
const capturedEpoch = sessionEpoch;
await pendingStore.save(record);
if (!isSessionCurrent(capturedEpoch)) return;
await sendExactStoredRequest(record);
```

`sendExactStoredRequest` belongs to the screen integration in Task 5 and dispatches solely by `record.operation`; it must send the stored body unchanged. Add a test that failed save means the API spy was never called.

- [ ] Ensure stale asynchronous callbacks cannot select a plan, write cache, or clear the current session's record. Owner-matching records remain recoverable after same-owner re-login, but are never auto-submitted. Run tests green and commit as `feat: retain pending workflow requests safely`.

## Task 5: Resume and recover through the existing UI

**Files:** Modify `apps/mobile/src/TodoExperience.tsx`, `apps/mobile/src/TodoExperience.test.tsx`, `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx`, `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx`. Create `apps/mobile/src/todoWorkflows/workflowCache.ts` and `apps/mobile/src/todoWorkflows/workflowCache.test.ts` for the one shared reconciliation rule. Update `AuthProvider` wiring from Task 4.

**Interfaces:** Shell mode is `"todos" | "workflow-new" | { workflowId: string }`. Pass `initialWorkflowId: string | null`, pending store, UUID generator, and session guards into the workflow host. Export `keepLatestWorkflow(oldData: TodoWorkflow | undefined, incoming: TodoWorkflow): TodoWorkflow`; use it for direct cache writes and query `structuralSharing` after identity/runtime validation.

- [ ] Add failing component tests for owner-scoped discovery, selecting a saved plan, empty/error/retry states, unknown contract fallback, and preserved quick add. Add separate tests that remount with a saved start/action record and render **Retry saved request** without sending anything automatically.
- [ ] Add a pure cache regression check:

```ts
const newer = { ...workflow, revision: 4 };
const older = { ...workflow, revision: 3 };
expect(keepLatestWorkflow(newer, older)).toBe(newer);
expect(keepLatestWorkflow(older, newer)).toBe(newer);
```

Reject mismatched workflow identities before this helper. Add a deferred GET test proving TanStack Query itself cannot replace revision 4 with revision 3.

- [ ] Run the shell, workflow-screen, and cache tests red. Add **Resume plans** adjacent to the existing todo experience using `['todo-workflows', userId, 'active']`. Use accessible labels and include loading/error/empty behavior. Selection fetches the authoritative workflow and renders its existing template. Existing completion and quick-add behavior remains unchanged.
- [ ] On user submission, freeze the canonical request with UUID and current revision/step; save and verify it; then send the exact body. Disable all workflow writes while persistence, mutation, or reconciliation is unresolved. Scope callbacks to the live epoch and matching pending identity.
- [ ] Implement explicit retry, discard with the spec's uncertainty warning, definitive rejection cleanup, uncertain-error retention, and clear-failure recovery. A second write must not replace an unresolved record. Successful starts recover their workflow ID. Every successful mutation/replay performs current GET before enabling another action. Stale conflicts clear only the matching record, then GET; request-ID mismatch requires explicit discard.
- [ ] Apply `keepLatestWorkflow` to list seeding, mutation results, and automatic GET results. Guard all writes with live session identity; use existing abort support on GET. Preserve local drafts on same-step refetch and reset them only when step identity changes. Invalidate active discovery after accepted writes and todos when current or replayed outcome proves completion.
- [ ] Add deterministic deferred-response tests for lost confirmation/retry, lost start/restart, replay older than cache, failed current GET, same-user re-login, cross-user login, stale storage callbacks, and accessible focus/alerts. Confirm unsupported views never submit. Run focused suites, all mobile tests, and typecheck green; commit as `feat: add workflow discovery and safe recovery UI`.

## Task 6: Verification, guide, and review

**Files:** Create `docs/guides/09-workflow-reliability.md` after implementation. Modify `docs/guides/08-server-directed-ui.md` to clarify that stable React keys do not preserve unsaved text across actual reload/unmount. Update `README.md` and `docs/curriculum-roadmap.md` with accurate implementation/acceptance status only after verification.

- [ ] Run the focused backend suite:

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest tests/test_workflow_domain.py tests/test_workflow_presentation.py tests/test_workflow_persistence.py tests/test_workflow_reliability.py tests/test_workflows.py tests/test_validation.py -v
```

- [ ] Run the focused client suite, then the existing full gate:

```bash
pnpm --dir apps/mobile test --runInBand src/todoWorkflows src/TodoExperience.test.tsx src/todos/todoApi.test.ts src/auth/authenticatedApi.test.ts src/auth/AuthProvider.test.tsx
pnpm quality
```

Expected outcomes are future requirements, not checks already performed. Investigate failures at their boundary; do not weaken race or ownership assertions to pass.

- [ ] Write Guide 09 from verified code: step ID versus revision versus request ID, canonical payload equality, transactional replay ordering, saved context versus unsent text, durable unknown writes, version migration, stale-cache reconciliation, and manual recovery exercises. Document the deliberate single-instance client journal and unpaginated tutorial list limitations.
- [ ] Record manual web and iOS runtime/date and actual observations for: quick add; each existing birthday-party branch; draft discovery after API/app restart; another device resume; lost-start and lost-confirmation response retry; competing revisions; cancel; storage failure-before-send; sign-out/re-login recovery; unsupported UI; focus and alerts. Leave unobserved rows unchecked and report blockers explicitly.
- [ ] Run markdown/link checks and `git diff --check`; inspect all modified files for unrelated changes. Resolve actionable Sol whole-branch review findings, rerun affected checks, and commit the verified guide/status changes.
- [ ] Present verified branch results for integration. Do not claim Phase 9 complete or create `phase-09-workflow-reliability` until supported-platform acceptance, integration, and CI on the exact integrated commit satisfy the repository checkpoint process.

## Spec coverage and handoff

| Spec requirement | Implementation tasks |
| --- | --- |
| Schema, migration, definition dispatch, snapshot serialization | 1, 2 |
| Start/action fingerprints, races, replay ordering, rollback | 2, 3 |
| Discovery, response versions, exact errors and ownership | 2, 3, 5 |
| Pending identity across restarts and storage failure boundaries | 4, 5 |
| Stale sessions, historical responses, automatic GET cache writes | 4, 5 |
| Accessibility, manual acceptance, guide, release honesty | 5, 6 |

The linked spec and this plan are approved. Before execution, reconcile any subsequently approved design changes into both documents. The next step is implementation in an isolated worktree using the model routing above; these documents themselves do not authorize deployment or claim feature completion.
