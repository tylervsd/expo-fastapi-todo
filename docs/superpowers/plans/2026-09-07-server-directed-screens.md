# Phase 8 Server-Directed Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the backend-owned `OFFER_BREAKDOWN` step and render every guided-todo step through a typed view contract with four frontend templates.

**Architecture:** Two transition rows in the pure domain; a database-free presentation mapper from snapshots to view descriptions; an additive `view` field on the existing envelope; a frontend registry that switches on `view.type` with per-step identity for draft reset.

**Tech Stack:** Python 3.14, FastAPI 0.141.1, Pydantic, PostgreSQL 18.6, SQLAlchemy 2.x, Alembic, Expo SDK 57.0.19, React 19.2.3, TypeScript 6.0.3, TanStack Query 5.102.8, pytest, Jest, React Native Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-07-server-directed-screens-design.md`

## Planning record

This plan was written on the `codex/phase-08-server-directed-screens` branch from the approved spec commit `ac93638` plus the Phase 7 implementation. Planning inspected `apps/api/app/workflow_domain.py`, `workflow_repository.py`, `workflow_service.py`, the workflow routes in `apps/api/app/main.py:144-206,385-490`, migration `2026090702_add_todo_workflows.py`, transport `apps/mobile/src/todos/todoApi.ts:398-579`, host `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx` (718 lines), and the Phase 7 domain/API/persistence/component suites. No implementation, production edit, migration run, or test execution was performed during planning. Unchecked steps below are future work, not evidence of passing tests.

## Global Constraints

- Start from the commit containing this plan and the approved spec. Do not re-specify Phase 8.
- Read root `AGENTS.md` if present, `apps/mobile/AGENTS.md`, and the exact Expo SDK 57 docs before mobile edits.
- Preserve quick-add, the separate **Help me plan a task** entry, cancellation from every nonterminal state, terminal rules, pessimistic mutations, uncertain-result recovery, and the exact `/todos` contract.
- Add only `OFFER_BREAKDOWN`; add no new command type. `AnswerMultipleSteps(answer: bool)` is reused and the current state disambiguates it.
- `involves_multiple_steps` keeps meaning only the first answer. In `OFFER_BREAKDOWN` the Boolean selects the next transition and is not persisted as a second fact.
- The domain never names components, routes, or layouts. The frontend never branches on business state and never submits or predicts a next state.
- Clients submit `action` plus input only. Mutations are never optimistic and never auto-retried. Only safe GETs retry once.
- Reuse ECMAScript trim, NUL/surrogate rejection, the 1-120-code-point title rule, and 2-10 ordered breakdown titles with duplicates preserved.
- `min_titles: 2` / `max_titles: 10` live in the backend; the client validates locally only for fast feedback and formats its count error from the supplied bounds.
- Step identity is `"{workflow_id}:{state}"`, derived only. Never store it, never use it in cache keys, never claim it as concurrency or idempotency control.
- The state graph stays acyclic; a domain unit test pins this by enumerating every valid path and asserting no repeated state.
- Keep the cache key `["todo-workflow", userPublicId, workflowId]`; exclude step identity. Keep clearing on auth transitions. Invalidate `['todos']` only when a `completion` view has `outcome="completed"`.
- Preserve exact Phase 7 `401`, owner-hidden `404`, wrong-state/terminal `409`, `422`, and `503` bodies. Structural validation precedes transition evaluation.
- Preserve safe area, scrolling, keyboard insets, header roles, labelled inputs, alert semantics, button roles with disabled state, ordered review labels, text-plus-disabled submission state, and 44-point targets.
- Use real PostgreSQL for persistence/rollback; keep transition-table tests database-free.
- Do not add idempotency keys, revisions, discovery, cross-device resume, definition/full-version negotiation, workers, queues, side effects, LLMs, a designer, layout DSLs, a navigation framework, a state library, or web/iOS E2E automation. Do not add `view_contract_version`.
- Luna implementers execute bounded mechanical steps and return any architecture or scope issue to the Sol controller. Sol performs significant review and the final whole-branch review.
- Do not create Guide 08, advance README/roadmap status, claim completion, push, open a PR, or create the `phase-08-server-directed-screens` tag until the verification task explicitly authorizes each.

---

## File map

### Backend domain, presentation, persistence

- Modify `apps/api/app/workflow_domain.py`: add `OFFER_BREAKDOWN` to `WorkflowState`; retarget Yes in `ASSESS_TASK` to `OFFER_BREAKDOWN`; add both `OFFER_BREAKDOWN` rows; widen the accepted `REVIEW`/`COMPLETED` context invariant (original title with `true` or `false`).
- Create `apps/api/app/workflow_presentation.py`: pure `present_workflow(snapshot) -> WorkflowView` with the six exact per-state views and derived `step_id`.
- Create `apps/api/alembic/versions/2026090801_allow_offer_breakdown.py`: drop/re-add `ck_todo_workflows_state` with the six-state set; downgrade rewinds `OFFER_BREAKDOWN` rows to `ASSESS_TASK` with null answer and empty proposals before narrowing.
- Modify `apps/api/alembic/env.py` only if it does not already import workflow metadata (Phase 7 registered it; verify before touching).
- Modify `apps/api/app/main.py`: add strict view response models (discriminated `view` union, exact keys per type); attach `view` in `as_workflow_response`; no new endpoints, methods, or headers.
- No change to `apps/api/app/workflow_service.py` signatures; `OFFER_BREAKDOWN` flows through the existing lock/transition/persist/commit path.

### Backend tests

- Modify `apps/api/tests/test_workflow_domain.py`: new rows, answer preservation, acyclicity enumeration, unchanged Phase 7 rows.
- Create `apps/api/tests/test_workflow_presentation.py`: exact view per state, shared yes/no type with distinct content/identity, identity stability, terminal outcome mapping.
- Modify `apps/api/tests/test_workflows.py`: exact view envelopes, three birthday paths, OFFER cancel/misplaced actions, unknown-field/strict-Boolean/view-key assertions, ownership, side-effect-free GET, `503`, OpenAPI view union, CORS unchanged.
- Modify `apps/api/tests/test_workflow_persistence.py`: CHECK widening persistence, downgrade rewind, untouched constraints.
- Modify `apps/api/tests/conftest.py` and `apps/api/tests/test_persistence.py`: expect revision `2026090801`.
- Modify `apps/api/tests/test_validation.py` only if view validation shares helpers; otherwise leave untouched.

### Frontend transport and presentation

- Modify `apps/mobile/src/todos/todoApi.ts`: add `OFFER_BREAKDOWN` to the opaque state set only for envelope echo (never branch on it); add discriminated `TodoWorkflowView` union plus fallback view; widen context validation for declined-breakdown; validate known views exactly; keep `conflict`/Bearer/401/409/422/timeout behavior.
- Modify `apps/mobile/src/todos/todoApi.test.ts`: view validation, fallback acceptance, malformed rejection, declined-breakdown context, preserved error mapping.
- Modify `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx`: registry on `snapshot.view.type` (`YesNoTemplate`, `TaskBreakdownTemplate`, `ReviewTemplate`, `CompletionTemplate`, fallback screen); `key={view.step_id}` remount; step-change draft/error clear with announce/focus only on identity change; invalidate `['todos']` on `outcome === "completed"`.
- Modify `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx`: shared-component two-question coverage, reset, stable-identity refetch, fallback, preserved transaction/focus/a11y behavior.
- No change to `workflowQueryKey`, the `TodoWorkflowScreenApi` action shapes, or the start screen.

### Documentation after verified implementation

- Create `docs/guides/08-server-directed-ui.md` only in the final verification task.
- Modify `README.md`, `docs/curriculum-roadmap.md`, the approved spec status, and this plan only after feature verification and observed acceptance.

---

### Task 1: Add OFFER_BREAKDOWN to the pure domain

**Files:**

- Modify: `apps/api/app/workflow_domain.py`
- Modify: `apps/api/tests/test_workflow_domain.py`

**Interfaces:**

- Consumes: existing `WorkflowSnapshot`, `AnswerMultipleSteps`, `TransitionDecision`, title helpers.
- Produces: `WorkflowState.OFFER_BREAKDOWN`; `transition()` rows `ASSESS_TASK+Yes -> OFFER_BREAKDOWN`, `OFFER_BREAKDOWN+Yes -> COLLECT_TASKS`, `OFFER_BREAKDOWN+No -> REVIEW` with `(snapshot.title,)` and preserved `involves_multiple_steps=true`.

- [ ] **Step 1: Write the failing transition-table tests.**

In `apps/api/tests/test_workflow_domain.py` add (keep existing imports/helpers):

```python
def offer_snapshot() -> WorkflowSnapshot:
    snapshot = assess_snapshot()
    decision = transition(snapshot, AnswerMultipleSteps(answer=True))
    return WorkflowSnapshot(
        id=snapshot.id,
        state=decision.state,
        title=snapshot.title,
        involves_multiple_steps=decision.involves_multiple_steps,
        proposed_todo_titles=decision.proposed_todo_titles,
        created_todos=None,
    )


def test_yes_in_assess_task_now_offers_breakdown() -> None:
    decision = transition(assess_snapshot(), AnswerMultipleSteps(answer=True))
    assert decision.state == WorkflowState.OFFER_BREAKDOWN
    assert decision.involves_multiple_steps is True
    assert decision.proposed_todo_titles == ()


def test_offer_yes_collects_and_offer_no_reviews_original() -> None:
    snapshot = offer_snapshot()
    assert snapshot.state == WorkflowState.OFFER_BREAKDOWN
    collect = transition(snapshot, AnswerMultipleSteps(answer=True))
    assert collect.state == WorkflowState.COLLECT_TASKS
    assert collect.involves_multiple_steps is True
    review = transition(snapshot, AnswerMultipleSteps(answer=False))
    assert review.state == WorkflowState.REVIEW
    assert review.involves_multiple_steps is True
    assert review.proposed_todo_titles == (TITLE,)
```

- [ ] **Step 2: Run the domain tests and observe RED.**

Run: `uv run --directory apps/api python -m pytest tests/test_workflow_domain.py -v`
Expected: FAIL with `AttributeError` on `WorkflowState.OFFER_BREAKDOWN`.

- [ ] **Step 3: Write the acyclicity and preservation tests.**

```python
def test_valid_paths_never_repeat_a_state() -> None:
    paths = [
        [WorkflowState.ASSESS_TASK, WorkflowState.REVIEW, WorkflowState.COMPLETED],
        [WorkflowState.ASSESS_TASK, WorkflowState.OFFER_BREAKDOWN, WorkflowState.REVIEW, WorkflowState.COMPLETED],
        [WorkflowState.ASSESS_TASK, WorkflowState.OFFER_BREAKDOWN, WorkflowState.COLLECT_TASKS, WorkflowState.REVIEW, WorkflowState.COMPLETED],
    ]
    for path in paths:
        assert len(set(path)) == len(path)


def test_submit_or_cancel_in_offer_is_wrong_state() -> None:
    snapshot = offer_snapshot()
    with pytest.raises(InvalidWorkflowAction):
        transition(snapshot, create_submit_tasks(("Send invitations", "Order birthday cake")))
    with pytest.raises(InvalidWorkflowAction):
        transition(snapshot, Confirm())
```

- [ ] **Step 4: Implement the minimal domain change.**

In `apps/api/app/workflow_domain.py`: add `OFFER_BREAKDOWN = "OFFER_BREAKDOWN"` to `WorkflowState`; change the `ASSESS_TASK` Yes branch target from `COLLECT_TASKS` to `OFFER_BREAKDOWN`; add an `OFFER_BREAKDOWN` match arm returning `COLLECT_TASKS` on `True` (preserving `snapshot.involves_multiple_steps`) and `REVIEW` with `(snapshot.title,)` on `False`; `Cancel` keeps working via the existing pre-match branch; leave `COLLECT_TASKS`/`REVIEW`/terminal arms untouched.

- [ ] **Step 5: Verify and commit Task 1.**

Run: `uv run --directory apps/api python -m pytest tests/test_workflow_domain.py -v` then `uv run --directory apps/api ruff check .` then `git diff --check`
Expected: domain tests PASS including all unmodified Phase 7 rows, Ruff PASS.

```bash
git add apps/api/app/workflow_domain.py apps/api/tests/test_workflow_domain.py
git commit -m "feat: add offer-breakdown domain transitions"
```

**Review checkpoint:** Sol reviews the transition diff for state/action completeness and the acyclicity pin. Luna implementers stop on any scope question.

---

### Task 2: Widen the state CHECK with a safe downgrade

**Files:**

- Create: `apps/api/alembic/versions/2026090801_allow_offer_breakdown.py`
- Modify: `apps/api/tests/test_workflow_persistence.py`
- Modify: `apps/api/tests/test_persistence.py`
- Modify: `apps/api/tests/conftest.py`

**Interfaces:**

- Consumes: Task 1 domain states; existing `WorkflowRow`, guarded `todo_test` database, revision `2026090702`.
- Produces: head revision `2026090801`; `OFFER_BREAKDOWN` rows persist; downgrade rewinds them to `ASSESS_TASK` with null answer and empty proposals.

- [ ] **Step 1: Write the migration-shape RED tests.**

In `apps/api/tests/test_persistence.py` update `REVISION = "2026090801"` and extend the constraint-name assertions to expect the six-state `ck_todo_workflows_state`; in `test_workflow_persistence.py` add:

```python
def test_offer_breakdown_row_persists(database_session: Session) -> None:
    owner_id = make_owner(database_session)
    row = create_workflow(database_session, uuid4(), owner_id, "Plan birthday party")
    update_workflow(
        database_session, row, state="OFFER_BREAKDOWN",
        involves_multiple_steps=True, proposed_todo_titles=[],
        completion_result=None,
    )
    assert find_workflow(database_session, row.public_id, owner_id).state == "OFFER_BREAKDOWN"
```

- [ ] **Step 2: Run the migration tests and observe RED.**

Run: `pnpm db:test:up && uv run --directory apps/api python -m pytest tests/test_persistence.py tests/test_workflow_persistence.py -v`
Expected: FAIL because Alembic head is still `2026090702` and `OFFER_BREAKDOWN` violates `ck_todo_workflows_state`.

- [ ] **Step 3: Create the exact Alembic revision.**

```python
"""allow offer breakdown

Revision ID: 2026090801
Revises: 2026090702
"""
revision = "2026090801"
down_revision = "2026090702"

def upgrade() -> None:
    op.execute("ALTER TABLE todo_workflows DROP CONSTRAINT ck_todo_workflows_state")
    op.execute("ALTER TABLE todo_workflows ADD CONSTRAINT ck_todo_workflows_state CHECK (state IN ('ASSESS_TASK', 'OFFER_BREAKDOWN', 'COLLECT_TASKS', 'REVIEW', 'COMPLETED', 'CANCELLED'))")

def downgrade() -> None:
    op.execute("UPDATE todo_workflows SET state = 'ASSESS_TASK', involves_multiple_steps = NULL, proposed_todo_titles = '[]'::jsonb WHERE state = 'OFFER_BREAKDOWN'")
    op.execute("ALTER TABLE todo_workflows DROP CONSTRAINT ck_todo_workflows_state")
    op.execute("ALTER TABLE todo_workflows ADD CONSTRAINT ck_todo_workflows_state CHECK (state IN ('ASSESS_TASK', 'COLLECT_TASKS', 'REVIEW', 'COMPLETED', 'CANCELLED'))")
```

Add no columns, indexes, or tables.

- [ ] **Step 4: Verify and commit Task 2.**

Run: `pnpm db:test:up && uv run --directory apps/api python -m pytest tests/test_persistence.py tests/test_workflow_persistence.py tests/test_workflow_domain.py -v` then `uv run --directory apps/api ruff check .` then `git diff --check`
Expected: PASS against the guarded real database with existing constraints untouched.

```bash
git add apps/api/alembic/versions/2026090801_allow_offer_breakdown.py apps/api/tests/test_persistence.py apps/api/tests/test_workflow_persistence.py apps/api/tests/conftest.py
git commit -m "feat: persist offer-breakdown workflow state"
```

**Review checkpoint:** Sol confirms no data migration is needed, the downgrade rewind is exact, and no column was added.

---

### Task 3: Add the pure presentation mapper

**Files:**

- Create: `apps/api/app/workflow_presentation.py`
- Create: `apps/api/tests/test_workflow_presentation.py`

**Interfaces:**

- Consumes: `WorkflowSnapshot` (Task 1), `MIN_BREAKDOWN_TITLES`, `MAX_BREAKDOWN_TITLES`.
- Produces: `present_workflow(snapshot) -> WorkflowView` dict with exact per-state shapes:

```python
present_workflow(snapshot) -> dict[str, object]  # keys vary by state; see tests
```

`ASSESS_TASK`/`OFFER_BREAKDOWN` -> `{"type": "yes_no", "step_id", "title", "question", "actions": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}]}` with questions `"Does this task involve multiple steps?"` / `"Would you like to split it into smaller todos?"`. `COLLECT_TASKS` -> `{"type": "task_breakdown", "step_id", "title": "Break it into smaller todos", "min_titles": 2, "max_titles": 10}`. `REVIEW` -> `{"type": "review", "step_id", "title": "Review your plan", "proposed_titles": [...]}`. Terminals -> `{"type": "completion", "step_id", "title", "outcome", "created_todos": [...]}` with `"Plan complete"`/`"Plan cancelled"`.

- [ ] **Step 1: Write the exact-view RED tests.**

Create `apps/api/tests/test_workflow_presentation.py` asserting all six states byte-for-byte (type, step_id `f"{WORKFLOW_ID}:{state}"`, titles, questions, limits, outcomes), that both yes/no views share `type == "yes_no"` with different `question`/`step_id`, that repeated mapping is identical, and that terminal mapping carries `outcome` plus the snapshot's created todos.

- [ ] **Step 2: Run and observe RED.**

Run: `uv run --directory apps/api python -m pytest tests/test_workflow_presentation.py -v`
Expected: FAIL during collection because `app.workflow_presentation` does not exist.

- [ ] **Step 3: Implement the pure function.**

Create `apps/api/app/workflow_presentation.py` with no imports from SQLAlchemy, sessions, React names, or routes: one `present_workflow` branching on `snapshot.state` and returning the exact dicts above, with `step_id = f"{snapshot.id}:{snapshot.state.value}"`. No I/O, no transactions.

- [ ] **Step 4: Verify and commit Task 3.**

Run: `uv run --directory apps/api python -m pytest tests/test_workflow_presentation.py tests/test_workflow_domain.py -v` then `uv run --directory apps/api ruff check .` then `git diff --check`
Expected: PASS; mapper stays database-free.

```bash
git add apps/api/app/workflow_presentation.py apps/api/tests/test_workflow_presentation.py
git commit -m "feat: map workflow snapshots to typed views"
```

**Review checkpoint:** Sol verifies the domain still knows nothing of views and the mapper knows nothing of components/routes. Escalate any new-template request to Sol.

---

### Task 4: Publish the additive view envelope

**Files:**

- Modify: `apps/api/app/main.py`
- Modify: `apps/api/tests/test_workflows.py`

**Interfaces:**

- Consumes: Tasks 1-3, existing auth/session deps, exact error mapping.
- Produces: every start/fetch/advance response gains exact `view`; action schemas unchanged; no new endpoints.

- [ ] **Step 1: Write envelope RED tests for the three birthday paths.**

Extend `apps/api/tests/test_workflows.py` reusing `auth_headers`: assert start returns `201` with `view.type == "yes_no"` and `step_id` ending `:ASSESS_TASK`; Yes returns `OFFER_BREAKDOWN` with same type but the split question and `:OFFER_BREAKDOWN` identity; Yes/Yes reaches `task_breakdown` with `min_titles/max_titles`; Yes/No reaches `REVIEW` with `["Plan birthday party"]` and `involves_multiple_steps is True`; confirm creates the exact todos; assert `set(body) == {"workflow_id", "state", "title", "context", "result", "view"}` on each response.

- [ ] **Step 2: Write OFFER rules, validation, and contract RED tests.**

Cover: `cancel` from `OFFER_BREAKDOWN` -> `200 CANCELLED`; `submit_tasks`/`confirm` in `OFFER_BREAKDOWN` -> exact wrong-state `409`; terminal `409`s unchanged; strict Boolean/unknown discriminator/unknown view-key rejection as `422`; owner-B GET/action -> exact `404`; unauthenticated -> exact `401`; GET side-effect-free; `503` on unavailable DB; OpenAPI contains the discriminated view union; CORS preflights unchanged.

- [ ] **Step 3: Run API tests and observe RED.**

Run: `pnpm db:test:up && uv run --directory apps/api python -m pytest tests/test_workflows.py -v`
Expected: FAIL on missing `view` key and `OFFER_BREAKDOWN` transitions.

- [ ] **Step 4: Implement strict view models and attach the mapper.**

In `apps/api/app/main.py` add `ConfigDict(extra="forbid")` view models (yes/no, breakdown, review, completion as a discriminated union on `type` with exact keys), add `view` to `TodoWorkflowResponse`, and call `present_workflow(snapshot)` inside `as_workflow_response`. Do not change action schemas, routes, status codes, or error bodies.

- [ ] **Step 5: Verify and commit Task 4.**

Run: `pnpm db:test:up && uv run --directory apps/api python -m pytest tests/test_workflows.py tests/test_workflow_persistence.py tests/test_workflow_presentation.py tests/test_validation.py tests/test_auth.py tests/test_todos.py -v` then `pnpm lint:api` then `git diff --check`
Expected: all API suites PASS; existing auth/todo contracts unchanged.

```bash
git add apps/api/app/main.py apps/api/tests/test_workflows.py
git commit -m "feat: expose server-directed view envelope"
```

**Review checkpoint:** Sol reviews envelope exactness, error-body preservation, and OpenAPI output before any client work begins.

---

### Task 5: Extend the typed transport with fallback

**Files:**

- Modify: `apps/mobile/src/todos/todoApi.ts`
- Modify: `apps/mobile/src/todos/todoApi.test.ts`

**Interfaces:**

- Consumes: Task 4 JSON; existing timeout/cancellation/****** runtime-validation machinery.
- Produces:

```typescript
export type TodoWorkflowView =
  | { type: "yes_no"; step_id: string; title: string; question: string; actions: { id: string; label: string }[] }
  | { type: "task_breakdown"; step_id: string; title: string; min_titles: number; max_titles: number }
  | { type: "review"; step_id: string; title: string; proposed_titles: string[] }
  | { type: "completion"; step_id: string; title: string; outcome: "completed" | "cancelled"; created_todos: Todo[] }
  | { type: string; step_id: string };
```

`TodoWorkflow` gains `view: TodoWorkflowView`; `state` stays an opaque non-empty string (add `"OFFER_BREAKDOWN"` to the accepted set for envelope echo only).

- [ ] **Step 1: Write view-validation RED tests.**

Assert: known views require exact keys; `OFFER_BREAKDOWN` yes/no envelope validates with `involves_multiple_steps: true` and empty proposals; declined-breakdown `REVIEW` validates with `(true, ["Plan birthday party"])`; unknown `type` validates only when it is an object with non-empty `type` and `step_id === workflow_id + ":" + state`; malformed UUIDs/missing keys/mistyped fields/malformed known views -> `invalid-data`; Bearer/401/409/422/timeout behavior preserved.

- [ ] **Step 2: Run transport tests and observe RED.**

Run: `pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts`
Expected: FAIL because `view` validation and the fallback type do not exist.

- [ ] **Step 3: Implement the minimal transport extension.**

Extend `todoApi.ts`: treat `state` as opaque (membership check including `OFFER_BREAKDOWN`, no branching); validate `context` structurally with the widened declined-breakdown rule; validate known views exactly; accept unknown views only on the `type`+`step_id` rule and ignore extra fields. Reuse `requestJson`, `isTodo`, and error mapping unchanged.

- [ ] **Step 4: Verify and commit Task 5.**

Run: `pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts` then `pnpm --dir apps/mobile lint` then `pnpm --dir apps/mobile typecheck` then `git diff --check`
Expected: transport tests, lint, and typecheck PASS.

```bash
git add apps/mobile/src/todos/todoApi.ts apps/mobile/src/todos/todoApi.test.ts
git commit -m "feat: validate server-directed workflow views"
```

**Review checkpoint:** Sol confirms no business-state branching leaked into the transport and the fallback rule matches the spec exactly.

---

### Task 6: Render through the template registry

**Files:**

- Modify: `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx`
- Modify: `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx`

**Interfaces:**

- Consumes: Task 5 `TodoWorkflowView`; existing `TodoWorkflowScreenApi`, cache key, pessimistic pattern, copy/styles/a11y conventions.

- Produces: `YesNoTemplate` (shared), `TaskBreakdownTemplate`, `ReviewTemplate`, `CompletionTemplate`, fallback screen; host keyed by `view.step_id`.

- [ ] **Step 1: Write shared yes/no RED tests.**

Reuse the existing `makeApi`/`renderHost` harness: drive start -> Yes and assert the second question renders through the same component with question `"Would you like to split it into smaller todos?"`, distinct Yes/No labels per question, and submission of `{ action: "answer_multiple_steps", answer }` for the OFFER step; assert drafts/errors do not survive the `ASSESS_TASK` -> `OFFER_BREAKDOWN` change.

- [ ] **Step 2: Write breakdown/review/completion/fallback RED tests.**

Cover: `task_breakdown` limits from the view with count errors formatted from supplied bounds; `review` renders exactly backend titles; `completion` invalidates `['todos']` only when `outcome === "completed"`; unknown `type` renders the fallback message with **Back to todos** and **Reload plan** and submits nothing; stable-identity refetch preserves draft; terminal/cancel/uncertainty/focus/a11y behavior preserved.

- [ ] **Step 3: Run the component suite and observe RED.**

Run: `pnpm --dir apps/mobile test --runInBand src/todoWorkflows/TodoWorkflowScreen.test.tsx`
Expected: FAIL because the registry, shared template, and fallback do not exist.

- [ ] **Step 4: Implement the registry host.**

Replace the `snapshot.state` switch with a `snapshot.view.type` registry; implement the four templates reusing Phase 7 copy/styles/labels; track last `step_id` to clear drafts/errors and announce/focus only on change; use `key={view.step_id}` on template state; map yes/no selection to `answer` Boolean; keep `cancel` on every nonterminal template and `confirm`/`submit_tasks` fixed per template. Never read `snapshot.state` for selection.

- [ ] **Step 5: Verify and commit Task 6.**

Run: `pnpm --dir apps/mobile test --runInBand src/todoWorkflows/TodoWorkflowScreen.test.tsx src/todos/todoApi.test.ts` then `pnpm --dir apps/mobile lint` then `pnpm --dir apps/mobile typecheck` then `git diff --check`
Expected: component tests, lint, and typecheck PASS.

```bash
git add apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx
git commit -m "feat: render workflows through view template registry"
```

**Review checkpoint:** Sol verifies no state branching remains, both questions share one component, and step-identity reset is exact.

---

### Task 7: Verify, teach, accept, and review Phase 8

**Files:**

- Create: `docs/guides/08-server-directed-ui.md`
- Modify: `README.md`
- Modify: `docs/curriculum-roadmap.md`
- Modify: `docs/superpowers/specs/2026-09-07-server-directed-screens-design.md`
- Modify: `docs/superpowers/plans/2026-09-07-server-directed-screens.md`

**Interfaces:**

- Consumes: implemented Tasks 1-6.

- Produces: learner guide, observed acceptance, accurate status, Sol-reviewed branch. Produces no tag, push, or PR.

- [ ] **Step 1: Run focused automated acceptance before writing the guide.**

Run:

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest tests/test_workflow_domain.py tests/test_workflow_presentation.py tests/test_workflow_persistence.py tests/test_workflows.py tests/test_validation.py -v
pnpm --dir apps/mobile test --runInBand src/todoWorkflows/TodoWorkflowScreen.test.tsx src/todos/todoApi.test.ts src/auth/authenticatedApi.test.ts
```

Expected: all transition, presentation, persistence, API, transport, and component tests PASS. On failure return to the owning task; do not write the guide.

- [ ] **Step 2: Run the complete repository gate.**

Run: `pnpm quality` then `git diff --check`
Expected: every static, contract, mobile, API, and web-export check PASS. Record actual results; do not convert network-unavailable link checks into false success.

- [ ] **Step 3: Write Guide 08 from verified behavior.**

Create `docs/guides/08-server-directed-ui.md`: domain state versus presentation type; one yes/no component serving two questions; step identity and stale-state prevention; when backend changes do/do not require frontend changes; the backend-only additional-question experiment (domain row, mapper case, migration, contract tests, zero new components/branching); focused commands actually verified; unchecked web/iOS acceptance table; Phase 9 deferrals. Claim only performed observations.

- [ ] **Step 4: Run the manual three-path acceptance journey.**

From the repo root run `pnpm db:up`, `pnpm db:migrate`, `pnpm dev:api`, `pnpm dev:mobile`. On `http://localhost:8081` and the reference iOS Simulator: prove quick-add unchanged; take No to REVIEW and confirm one original todo; take Yes/No and confirm one original todo with `involves_multiple_steps=true`; take Yes/Yes with 2-10 titles and confirm exact REVIEW/creation; cancel from `OFFER_BREAKDOWN`; restart API mid-workflow and refetch; verify refetch keeps identity/draft; verify fallback only via a test double, never by inventing server UI. Record runtime, dates, and results in Guide 08.

- [ ] **Step 5: Update entry points and commit the guide without completion claims.**

Link Guide 08 from README/roadmap only after verification; keep Phase 8 uncompleted until review/integration/CI pass elsewhere. Run `pnpm lint:markdown`, `pnpm lint:links`, `pnpm quality`, `git diff --check`, then:

```bash
git add docs/guides/08-server-directed-ui.md README.md docs/curriculum-roadmap.md docs/superpowers/specs/2026-09-07-server-directed-screens-design.md docs/superpowers/plans/2026-09-07-server-directed-screens.md
git commit -m "docs: add server-directed screens learning guide"
```

- [ ] **Step 6: Obtain final whole-branch Sol review and resolve every finding.**

Dispatch `gpt-5.6-sol` against the branch and approved spec: domain/mapper purity, transition completeness, migration safety, envelope exactness, transport fallback rule, registry purity, step-identity reset, auth/ownership/cache behavior, a11y, and doc accuracy. Apply feedback via the receiving-code-review workflow; rerun affected suites plus `pnpm quality`. Do not integrate, push, open a PR, or tag: those need separate authorization.

## Spec coverage check

- Second question, shared yes/no component, backend-decided routing: Tasks 1, 3, 4, 5, 6.
- `OFFER_BREAKDOWN` rows, reused command, unpersisted second answer, acyclic identity assumption: Tasks 1, 2, 3.
- Pure mapper, additive envelope, stable identity, unknown-template fallback: Tasks 3, 4, 5, 6.
- Three birthday paths, arbitrary titles, cancellation/terminal/ownership rules: Tasks 1, 4, 6, 7.
- Validation widening, single-source limits, strict discriminators/Booleans, unknown-field rejection: Tasks 4, 5.
- Migration widening with rewind downgrade, no new columns: Task 2.
- Auth, cache isolation, completion invalidation, recovery behavior: Tasks 4, 5, 6.
- Deterministic testing table and pyramid: Tasks 1-6.
- Guide-after-verification, README/roadmap gating, review/integration/CI/tag order: Task 7.
- Phase 9 exclusions and no `view_contract_version`: all tasks (nothing to build).
