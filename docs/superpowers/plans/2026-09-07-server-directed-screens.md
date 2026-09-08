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

- Modify `apps/api/app/workflow_domain.py`: add `OFFER_BREAKDOWN` to `WorkflowState`; retarget Yes in `ASSESS_TASK` to `OFFER_BREAKDOWN`; add both `OFFER_BREAKDOWN` rows while preserving the first answer.
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

- Modify `apps/mobile/src/todos/todoApi.ts`: accept any non-empty state string without an allowlist; validate context structurally; add a discriminated known-view union plus a normalized `unsupported` fallback view; validate known views exactly; keep `conflict`/Bearer/401/409/422/timeout behavior.
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


def collect_snapshot() -> WorkflowSnapshot:
    snapshot = offer_snapshot()
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

Add `offer_snapshot` and replace the existing `collect_snapshot` helper with
the version above; do not leave two definitions of `collect_snapshot`.

- [ ] **Step 2: Run the domain tests and observe RED.**

Run: `uv run --directory apps/api python -m pytest tests/test_workflow_domain.py -v`
Expected: FAIL with `AttributeError` on `WorkflowState.OFFER_BREAKDOWN`.

- [ ] **Step 3: Write the acyclicity and preservation tests.**

```python
def test_valid_paths_never_repeat_a_state() -> None:
    commands: tuple[WorkflowCommand, ...] = (
        AnswerMultipleSteps(False),
        AnswerMultipleSteps(True),
        create_submit_tasks(("Send invitations", "Order birthday cake")),
        Confirm(),
        Cancel(),
    )

    def walk(snapshot: WorkflowSnapshot, seen: frozenset[WorkflowState]) -> None:
        assert snapshot.state not in seen
        if snapshot.state in (WorkflowState.COMPLETED, WorkflowState.CANCELLED):
            return
        for command in commands:
            try:
                decision = transition(snapshot, command)
            except InvalidWorkflowAction:
                continue
            walk(
                WorkflowSnapshot(
                    id=snapshot.id,
                    state=decision.state,
                    title=snapshot.title,
                    involves_multiple_steps=decision.involves_multiple_steps,
                    proposed_todo_titles=decision.proposed_todo_titles,
                    created_todos=() if decision.state == WorkflowState.COMPLETED else None,
                ),
                seen | {snapshot.state},
            )

    walk(assess_snapshot(), frozenset())


def test_submit_tasks_or_confirm_in_offer_is_wrong_state() -> None:
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

- [ ] **Step 1: Write the upgrade and downgrade RED tests.**

In `apps/api/tests/test_persistence.py` and `apps/api/tests/conftest.py`, set
`REVISION = "2026090801"`. In the former, replace the expected state CHECK SQL
with:

```python
(
    "ck_todo_workflows_state",
    "state = ANY (ARRAY['ASSESS_TASK'::text, 'OFFER_BREAKDOWN'::text, "
    "'COLLECT_TASKS'::text, 'REVIEW'::text, 'COMPLETED'::text, "
    "'CANCELLED'::text])",
),
```

In `test_workflow_persistence.py` add:

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


def test_downgrade_rewinds_offer_before_narrowing(database_engine: Engine) -> None:
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    public_id = uuid4()
    try:
        with database_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO users (public_id, username, password_hash) "
                    "VALUES (:public_id, :username, 'hash') RETURNING id"
                ),
                {"public_id": uuid4(), "username": f"downgrade-{public_id}"},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO todo_workflows "
                    "(public_id, owner_id, state, title, involves_multiple_steps, proposed_todo_titles) "
                    "VALUES (:public_id, :owner_id, 'OFFER_BREAKDOWN', "
                    "'Plan birthday party', true, '[]'::jsonb)"
                ),
                {"public_id": public_id, "owner_id": owner_id},
            )
            config.attributes["connection"] = connection
            command.downgrade(config, "2026090702")
            row = connection.execute(
                text(
                    "SELECT state, involves_multiple_steps, proposed_todo_titles "
                    "FROM todo_workflows WHERE public_id = :public_id"
                ),
                {"public_id": public_id},
            ).one()
            assert tuple(row) == ("ASSESS_TASK", None, [])
    finally:
        with database_engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
```

Add `Path`, `Engine`, `text`, `Config`, and `command` to the existing imports.

- [ ] **Step 2: Run the migration tests and observe RED.**

Run: `pnpm db:test:up && uv run --directory apps/api python -m pytest tests/test_persistence.py tests/test_workflow_persistence.py -v`
Expected: FAIL because Alembic head is still `2026090702` and `OFFER_BREAKDOWN` violates `ck_todo_workflows_state`.

- [ ] **Step 3: Create the exact Alembic revision.**

```python
"""allow offer breakdown

Revision ID: 2026090801
Revises: 2026090702
"""
from collections.abc import Sequence

from alembic import op

revision: str = "2026090801"
down_revision: str | Sequence[str] | None = "2026090702"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE todo_workflows DROP CONSTRAINT ck_todo_workflows_state")
    op.execute(
        "ALTER TABLE todo_workflows ADD CONSTRAINT "
        "ck_todo_workflows_state CHECK (state IN "
        "('ASSESS_TASK', 'OFFER_BREAKDOWN', 'COLLECT_TASKS', "
        "'REVIEW', 'COMPLETED', 'CANCELLED'))"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE todo_workflows SET state = 'ASSESS_TASK', "
        "involves_multiple_steps = NULL, proposed_todo_titles = '[]'::jsonb "
        "WHERE state = 'OFFER_BREAKDOWN'"
    )
    op.execute("ALTER TABLE todo_workflows DROP CONSTRAINT ck_todo_workflows_state")
    op.execute(
        "ALTER TABLE todo_workflows ADD CONSTRAINT "
        "ck_todo_workflows_state CHECK (state IN "
        "('ASSESS_TASK', 'COLLECT_TASKS', 'REVIEW', 'COMPLETED', 'CANCELLED'))"
    )
```

Add no columns, indexes, or tables.

- [ ] **Step 4: Verify and commit Task 2.**

Run: `pnpm db:test:up && uv run --directory apps/api python -m pytest tests/test_persistence.py tests/test_workflow_persistence.py tests/test_workflow_domain.py -v` then `uv run --directory apps/api ruff check .` then `git diff --check`
Expected: PASS against the guarded real database; the downgrade test returns to head in `finally`, and existing constraints remain untouched.

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
- Produces: the concrete `YesNoView`, `TaskBreakdownView`, `ReviewView`, and
  `CompletionView` `TypedDict` definitions shown in Step 3; their
  `WorkflowView` union; and
  `present_workflow(snapshot: WorkflowSnapshot) -> WorkflowView`.

`ASSESS_TASK`/`OFFER_BREAKDOWN` share `yes_no`; `COLLECT_TASKS` uses `task_breakdown`; `REVIEW` uses `review`; both terminals use `completion`. `CANCELLED` always maps `created_todos` to `[]`, never `None`.

- [ ] **Step 1: Write the exact-view RED tests.**

Create `apps/api/tests/test_workflow_presentation.py` with the existing `WORKFLOW_ID` and title values:

```python
from dataclasses import replace

import pytest

from app.workflow_domain import CreatedTodo, WorkflowSnapshot, WorkflowState
from app.workflow_presentation import present_workflow


def snapshot(state: WorkflowState) -> WorkflowSnapshot:
    return WorkflowSnapshot(
        id=WORKFLOW_ID,
        state=state,
        title="Plan birthday party",
        involves_multiple_steps=state != WorkflowState.ASSESS_TASK,
        proposed_todo_titles=(),
        created_todos=None,
    )


@pytest.mark.parametrize(
    ("state", "question"),
    [
        (WorkflowState.ASSESS_TASK, "Does this task involve multiple steps?"),
        (WorkflowState.OFFER_BREAKDOWN, "Would you like to split it into smaller todos?"),
    ],
)
def test_yes_no_views_are_exact(state: WorkflowState, question: str) -> None:
    assert present_workflow(snapshot(state)) == {
        "type": "yes_no",
        "step_id": f"{WORKFLOW_ID}:{state.value}",
        "title": "Plan birthday party",
        "question": question,
        "actions": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
    }


def test_breakdown_and_review_views_are_exact() -> None:
    assert present_workflow(snapshot(WorkflowState.COLLECT_TASKS)) == {
        "type": "task_breakdown",
        "step_id": f"{WORKFLOW_ID}:COLLECT_TASKS",
        "title": "Break it into smaller todos",
        "min_titles": 2,
        "max_titles": 10,
    }
    review = replace(
        snapshot(WorkflowState.REVIEW),
        proposed_todo_titles=("Send invitations", "Order birthday cake"),
    )
    assert present_workflow(review) == {
        "type": "review",
        "step_id": f"{WORKFLOW_ID}:REVIEW",
        "title": "Review your plan",
        "proposed_titles": ["Send invitations", "Order birthday cake"],
    }


def test_terminal_views_are_exact() -> None:
    todo = CreatedTodo(id=TODO_ID, title="Plan birthday party", completed=False)
    completed = replace(snapshot(WorkflowState.COMPLETED), created_todos=(todo,))
    assert present_workflow(completed) == {
        "type": "completion",
        "step_id": f"{WORKFLOW_ID}:COMPLETED",
        "title": "Plan complete",
        "outcome": "completed",
        "created_todos": [
            {"id": TODO_ID, "title": "Plan birthday party", "completed": False}
        ],
    }
    assert present_workflow(snapshot(WorkflowState.CANCELLED)) == {
        "type": "completion",
        "step_id": f"{WORKFLOW_ID}:CANCELLED",
        "title": "Plan cancelled",
        "outcome": "cancelled",
        "created_todos": [],
    }


def test_mapping_same_snapshot_is_stable() -> None:
    current = snapshot(WorkflowState.OFFER_BREAKDOWN)
    assert present_workflow(current) == present_workflow(current)
```

Define `TODO_ID` beside `WORKFLOW_ID` as a second fixed UUID.

- [ ] **Step 2: Run and observe RED.**

Run: `uv run --directory apps/api python -m pytest tests/test_workflow_presentation.py -v`
Expected: FAIL during collection because `app.workflow_presentation` does not exist.

- [ ] **Step 3: Implement the pure function.**

Create `apps/api/app/workflow_presentation.py` with no SQLAlchemy, session, React, or route imports:

```python
from typing import Literal, TypedDict
from uuid import UUID

from app.workflow_domain import (
    MAX_BREAKDOWN_TITLES,
    MIN_BREAKDOWN_TITLES,
    WorkflowSnapshot,
    WorkflowState,
)


class Choice(TypedDict):
    id: Literal["yes", "no"]
    label: str


class PresentedTodo(TypedDict):
    id: UUID
    title: str
    completed: bool


class YesNoView(TypedDict):
    type: Literal["yes_no"]
    step_id: str
    title: str
    question: str
    actions: list[Choice]


class TaskBreakdownView(TypedDict):
    type: Literal["task_breakdown"]
    step_id: str
    title: str
    min_titles: int
    max_titles: int


class ReviewView(TypedDict):
    type: Literal["review"]
    step_id: str
    title: str
    proposed_titles: list[str]


class CompletionView(TypedDict):
    type: Literal["completion"]
    step_id: str
    title: str
    outcome: Literal["completed", "cancelled"]
    created_todos: list[PresentedTodo]


WorkflowView = YesNoView | TaskBreakdownView | ReviewView | CompletionView


def present_workflow(snapshot: WorkflowSnapshot) -> WorkflowView:
    step_id = f"{snapshot.id}:{snapshot.state.value}"
    if snapshot.state in (WorkflowState.ASSESS_TASK, WorkflowState.OFFER_BREAKDOWN):
        question = (
            "Does this task involve multiple steps?"
            if snapshot.state == WorkflowState.ASSESS_TASK
            else "Would you like to split it into smaller todos?"
        )
        return {
            "type": "yes_no",
            "step_id": step_id,
            "title": snapshot.title,
            "question": question,
            "actions": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
        }
    if snapshot.state == WorkflowState.COLLECT_TASKS:
        return {
            "type": "task_breakdown",
            "step_id": step_id,
            "title": "Break it into smaller todos",
            "min_titles": MIN_BREAKDOWN_TITLES,
            "max_titles": MAX_BREAKDOWN_TITLES,
        }
    if snapshot.state == WorkflowState.REVIEW:
        return {
            "type": "review",
            "step_id": step_id,
            "title": "Review your plan",
            "proposed_titles": list(snapshot.proposed_todo_titles),
        }
    completed = snapshot.state == WorkflowState.COMPLETED
    return {
        "type": "completion",
        "step_id": step_id,
        "title": "Plan complete" if completed else "Plan cancelled",
        "outcome": "completed" if completed else "cancelled",
        "created_todos": (
            [
                {"id": item.id, "title": item.title, "completed": item.completed}
                for item in snapshot.created_todos or ()
            ]
            if completed
            else []
        ),
    }
```

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

Extend the existing journey tests rather than creating another harness. The
first response and new Yes/No branch must include these exact assertions:

```python
started = client.post(
    "/todo-workflows",
    json={"title": "Plan birthday party"},
    headers=headers,
)
assert started.status_code == 201
body = started.json()
workflow_id = body["workflow_id"]
assert set(body) == {"workflow_id", "state", "title", "context", "result", "view"}
assert body["view"] == {
    "type": "yes_no",
    "step_id": f"{workflow_id}:ASSESS_TASK",
    "title": "Plan birthday party",
    "question": "Does this task involve multiple steps?",
    "actions": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
}

offered = client.post(
    f"/todo-workflows/{workflow_id}/actions",
    json={"action": "answer_multiple_steps", "answer": True},
    headers=headers,
)
assert offered.status_code == 200
assert offered.json()["state"] == "OFFER_BREAKDOWN"
assert offered.json()["context"] == {
    "involves_multiple_steps": True,
    "proposed_todo_titles": [],
}
assert offered.json()["view"]["question"] == (
    "Would you like to split it into smaller todos?"
)
assert offered.json()["view"]["step_id"] == f"{workflow_id}:OFFER_BREAKDOWN"

review = client.post(
    f"/todo-workflows/{workflow_id}/actions",
    json={"action": "answer_multiple_steps", "answer": False},
    headers=headers,
)
assert review.status_code == 200
assert review.json()["context"] == {
    "involves_multiple_steps": True,
    "proposed_todo_titles": ["Plan birthday party"],
}
assert review.json()["view"] == {
    "type": "review",
    "step_id": f"{workflow_id}:REVIEW",
    "title": "Review your plan",
    "proposed_titles": ["Plan birthday party"],
}
```

In the existing Yes journey, insert a second Yes before `submit_tasks` and pin
the remaining view payloads (retain its existing todo/result assertions):

```python
breakdown = client.post(
    f"/todo-workflows/{workflow_id}/actions",
    json={"action": "answer_multiple_steps", "answer": True},
    headers=headers,
)
assert breakdown.json()["view"] == {
    "type": "task_breakdown",
    "step_id": f"{workflow_id}:COLLECT_TASKS",
    "title": "Break it into smaller todos",
    "min_titles": 2,
    "max_titles": 10,
}

submitted = client.post(
    f"/todo-workflows/{workflow_id}/actions",
    json={"action": "submit_tasks", "titles": ["Send invitations", "Order cake"]},
    headers=headers,
)
assert submitted.json()["view"] == {
    "type": "review",
    "step_id": f"{workflow_id}:REVIEW",
    "title": "Review your plan",
    "proposed_titles": ["Send invitations", "Order cake"],
}

confirmed = client.post(
    f"/todo-workflows/{workflow_id}/actions",
    json={"action": "confirm"},
    headers=headers,
)
created = confirmed.json()["result"]["created_todos"]
assert confirmed.json()["view"] == {
    "type": "completion",
    "step_id": f"{workflow_id}:COMPLETED",
    "title": "Plan complete",
    "outcome": "completed",
    "created_todos": created,
}
```

- [ ] **Step 2: Write OFFER rules, validation, and contract RED tests.**

Add `"offer"` to the existing cancellation parametrization and add
`submit_tasks`/`confirm` cases for exact wrong-state `409`. Keep the current
malformed action tests for strict Boolean, unknown action discriminator, and
unknown request fields returning `422`.

Response-view validation is not an HTTP `422`: test it directly after the
models exist:

```python
def test_known_view_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        YesNoWorkflowView.model_validate(
            {
                "type": "yes_no",
                "step_id": f"{uuid4()}:ASSESS_TASK",
                "title": "Plan birthday party",
                "question": "Does this task involve multiple steps?",
                "actions": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
                "extra": True,
            }
        )
```

Import `ValidationError` and `YesNoWorkflowView`. Preserve the existing
owner-B `404`, unauthenticated `401`, side-effect-free GET, `503`, and CORS
tests. Extend the OpenAPI test with:

```python
view_schema = schema["components"]["schemas"]["TodoWorkflowResponse"]["properties"]["view"]
assert view_schema["discriminator"] == {
    "propertyName": "type",
    "mapping": {
        "yes_no": "#/components/schemas/YesNoWorkflowView",
        "task_breakdown": "#/components/schemas/TaskBreakdownWorkflowView",
        "review": "#/components/schemas/ReviewWorkflowView",
        "completion": "#/components/schemas/CompletionWorkflowView",
    },
}
assert len(view_schema["oneOf"]) == 4
```

- [ ] **Step 3: Run API tests and observe RED.**

Run: `pnpm db:test:up && uv run --directory apps/api python -m pytest tests/test_workflows.py -v`
Expected: FAIL on missing `view` key and `OFFER_BREAKDOWN` transitions.

- [ ] **Step 4: Implement strict view models and attach the mapper.**

In `apps/api/app/main.py`, import `StrictInt`, `present_workflow`, and
`WorkflowView`, then add the concrete HTTP models:

```python
class WorkflowChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal["yes", "no"]
    label: StrictStr


class YesNoWorkflowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["yes_no"]
    step_id: StrictStr
    title: StrictStr
    question: StrictStr
    actions: list[WorkflowChoice]


class TaskBreakdownWorkflowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["task_breakdown"]
    step_id: StrictStr
    title: StrictStr
    min_titles: StrictInt
    max_titles: StrictInt


class ReviewWorkflowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["review"]
    step_id: StrictStr
    title: StrictStr
    proposed_titles: list[StrictStr]


class CompletionWorkflowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["completion"]
    step_id: StrictStr
    title: StrictStr
    outcome: Literal["completed", "cancelled"]
    created_todos: list[Todo]


TodoWorkflowView = Annotated[
    YesNoWorkflowView
    | TaskBreakdownWorkflowView
    | ReviewWorkflowView
    | CompletionWorkflowView,
    Field(discriminator="type"),
]
```

Add `view: TodoWorkflowView` to `TodoWorkflowResponse`. In
`as_workflow_response`, pass `view=present_workflow(snapshot)`; assign the
mapper result to a `WorkflowView` local so its interface is type-checked. Do
not change action schemas, routes, status codes, or error bodies.

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

- Consumes: Task 4 JSON and existing timeout, cancellation, and runtime-validation machinery.
- Produces:

```typescript
type KnownTodoWorkflowView =
  | {
      type: "yes_no";
      step_id: string;
      title: string;
      question: string;
      actions: [{ id: "yes"; label: string }, { id: "no"; label: string }];
    }
  | { type: "task_breakdown"; step_id: string; title: string; min_titles: number; max_titles: number }
  | { type: "review"; step_id: string; title: string; proposed_titles: string[] }
  | { type: "completion"; step_id: string; title: string; outcome: "completed" | "cancelled"; created_todos: Todo[] };

type UnsupportedTodoWorkflowView = {
  type: "unsupported";
  server_type: string;
  step_id: string;
};

export type TodoWorkflowView = KnownTodoWorkflowView | UnsupportedTodoWorkflowView;
```

`TodoWorkflow` gains `view: TodoWorkflowView`. Delete `workflowStates` and
change the compatibility alias to `export type TodoWorkflowState = string`
so Task 5 still type-checks before the host stops importing it in Task 6;
`TodoWorkflow.state` may keep using that alias. There is no state allowlist.

- [ ] **Step 1: Write view-validation RED tests.**

Add `view` to the shared workflow fixtures, then add these focused cases:

```typescript
const assessView = {
  type: "yes_no" as const,
  step_id: `${workflowId}:ASSESS_TASK`,
  title: "Plan birthday party",
  question: "Does this task involve multiple steps?",
  actions: [
    { id: "yes" as const, label: "Yes" },
    { id: "no" as const, label: "No" },
  ],
};

it("accepts an opaque state and normalizes an unknown view", async () => {
  const body = {
    ...assessWorkflow,
    state: "FUTURE_STATE",
    view: {
      type: "future_template",
      step_id: `${workflowId}:FUTURE_STATE`,
      server_only: true,
    },
  };
  const fetchImpl = jest.fn().mockResolvedValue(response(200, body));

  await expect(
    getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
  ).resolves.toEqual({
    ...body,
    view: {
      type: "unsupported",
      server_type: "future_template",
      step_id: `${workflowId}:FUTURE_STATE`,
    },
  });
});

it.each([
  ["empty state", { ...assessWorkflow, state: "" }],
  ["wrong step", { ...assessWorkflow, view: { ...assessView, step_id: "wrong" } }],
  ["missing view key", { ...assessWorkflow, view: { type: "future_template" } }],
  ["extra known key", { ...assessWorkflow, view: { ...assessView, extra: true } }],
  ["wrong choice id", {
    ...assessWorkflow,
    view: {
      ...assessView,
      actions: [{ id: "maybe", label: "Maybe" }, { id: "no", label: "No" }],
    },
  }],
])("rejects %s", async (_name, body) => {
  const fetchImpl = jest.fn().mockResolvedValue(response(200, body));
  await expect(
    getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
  ).rejects.toMatchObject({ kind: "invalid-data" });
});

it("accepts declined breakdown context structurally", async () => {
  const body = {
    ...assessWorkflow,
    state: "REVIEW",
    context: {
      involves_multiple_steps: true,
      proposed_todo_titles: ["Plan birthday party"],
    },
    view: {
      type: "review",
      step_id: `${workflowId}:REVIEW`,
      title: "Review your plan",
      proposed_titles: ["Plan birthday party"],
    },
  };
  const fetchImpl = jest.fn().mockResolvedValue(response(200, body));
  await expect(
    getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
  ).resolves.toEqual(body);
});
```

Keep the existing malformed UUID, missing envelope key, wrong field type,
Bearer, `401`, `409`, `422`, cancellation, and timeout cases. Remove tests
whose only purpose was rejecting a state/context combination that the client
no longer owns.

- [ ] **Step 2: Run transport tests and observe RED.**

Run: `pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts`
Expected: FAIL because `view` validation and the fallback type do not exist.

- [ ] **Step 3: Implement the minimal transport extension.**

Replace the Boolean-only workflow guard with a parser because unknown views
must be normalized:

```typescript
const exactObject = (value: unknown, keys: string[]): value is Record<string, unknown> =>
  typeof value === "object" &&
  value !== null &&
  !Array.isArray(value) &&
  Reflect.ownKeys(value).length === keys.length &&
  keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));

const isCanonicalTitle = (value: unknown): value is string =>
  typeof value === "string" && normalizeTodoTitle(value) === value;

type BreakdownView = Extract<KnownTodoWorkflowView, { type: "task_breakdown" }>;
type ReviewView = Extract<KnownTodoWorkflowView, { type: "review" }>;
type CompletionView = Extract<KnownTodoWorkflowView, { type: "completion" }>;

function isExactBreakdownView(
  view: Record<string, unknown>,
): view is BreakdownView {
  return (
    exactObject(view, ["type", "step_id", "title", "min_titles", "max_titles"]) &&
    isCanonicalTitle(view.title) &&
    Number.isInteger(view.min_titles) &&
    Number.isInteger(view.max_titles) &&
    (view.min_titles as number) >= 1 &&
    (view.min_titles as number) <= (view.max_titles as number)
  );
}

function isExactReviewView(view: Record<string, unknown>): view is ReviewView {
  return (
    exactObject(view, ["type", "step_id", "title", "proposed_titles"]) &&
    isCanonicalTitle(view.title) &&
    Array.isArray(view.proposed_titles) &&
    view.proposed_titles.every(isCanonicalTitle)
  );
}

function isExactCompletionView(
  view: Record<string, unknown>,
): view is CompletionView {
  return (
    exactObject(view, ["type", "step_id", "title", "outcome", "created_todos"]) &&
    isCanonicalTitle(view.title) &&
    (view.outcome === "completed" || view.outcome === "cancelled") &&
    Array.isArray(view.created_todos) &&
    view.created_todos.every(isTodo)
  );
}

function parseWorkflowView(
  value: unknown,
  expectedStepId: string,
): TodoWorkflowView | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const view = value as Record<string, unknown>;
  if (typeof view.type !== "string" || view.type.length === 0) return null;
  if (view.step_id !== expectedStepId) return null;
  switch (view.type) {
    case "yes_no":
      if (!exactObject(view, ["type", "step_id", "title", "question", "actions"])) return null;
      if (!isCanonicalTitle(view.title) || typeof view.question !== "string") return null;
      if (!Array.isArray(view.actions) || view.actions.length !== 2) return null;
      if (!exactObject(view.actions[0], ["id", "label"]) || view.actions[0].id !== "yes") return null;
      if (!exactObject(view.actions[1], ["id", "label"]) || view.actions[1].id !== "no") return null;
      if (typeof view.actions[0].label !== "string" || typeof view.actions[1].label !== "string") return null;
      return view as KnownTodoWorkflowView;
    case "task_breakdown":
      return isExactBreakdownView(view) ? view : null;
    case "review":
      return isExactReviewView(view) ? view : null;
    case "completion":
      return isExactCompletionView(view) ? view : null;
    default:
      return { type: "unsupported", server_type: view.type, step_id: expectedStepId };
  }
}

function parseTodoWorkflow(value: unknown): TodoWorkflow | null {
  if (!exactObject(value, ["workflow_id", "state", "title", "context", "result", "view"])) {
    return null;
  }
  if (
    typeof value.workflow_id !== "string" ||
    !uuidPattern.test(value.workflow_id) ||
    typeof value.state !== "string" ||
    value.state.length === 0 ||
    !isCanonicalTitle(value.title) ||
    !exactObject(value.context, ["involves_multiple_steps", "proposed_todo_titles"])
  ) {
    return null;
  }

  const answer = value.context.involves_multiple_steps;
  const proposals = value.context.proposed_todo_titles;
  if (
    !(answer === null || typeof answer === "boolean") ||
    !Array.isArray(proposals) ||
    !proposals.every(isCanonicalTitle)
  ) {
    return null;
  }

  let result: TodoWorkflow["result"] = null;
  if (value.result !== null) {
    if (!exactObject(value.result, ["created_todos"])) return null;
    if (!Array.isArray(value.result.created_todos) || !value.result.created_todos.every(isTodo)) {
      return null;
    }
    result = { created_todos: value.result.created_todos };
  }

  const view = parseWorkflowView(
    value.view,
    `${value.workflow_id}:${value.state}`,
  );
  if (view === null) return null;
  return {
    workflow_id: value.workflow_id,
    state: value.state,
    title: value.title,
    context: {
      involves_multiple_steps: answer,
      proposed_todo_titles: proposals,
    },
    result,
    view,
  };
}
```

Replace each request function's `isTodoWorkflow(body)` check with one call to
`parseTodoWorkflow(body)`: throw its existing `invalid-data` error on `null`,
otherwise return the parsed value. Reuse `requestJson`, `isTodo`, and all
existing error mapping unchanged; delete the old state/context semantic checks.

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

Add exact `view` data to every existing `TodoWorkflow` fixture. Add this new
fixture beside `assessWorkflow` (and give `assessWorkflow` its corresponding
`yes_no` view):

```typescript
const offerWorkflow: TodoWorkflow = {
  ...assessWorkflow,
  state: "OFFER_BREAKDOWN",
  context: { involves_multiple_steps: true, proposed_todo_titles: [] },
  view: {
    type: "yes_no",
    step_id: `${WORKFLOW_ID}:OFFER_BREAKDOWN`,
    title: "Plan birthday party",
    question: "Would you like to split it into smaller todos?",
    actions: [
      { id: "yes", label: "Yes" },
      { id: "no", label: "No" },
    ],
  },
};
```

Replace the old test that jumps directly from ASSESS to COLLECT with:

```typescript
it("uses the shared yes/no template for both questions", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);

  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      }),
    ).toBeTruthy(),
  );

  api.advanceWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  expect(api.advanceWorkflow).toHaveBeenLastCalledWith(WORKFLOW_ID, {
    action: "answer_multiple_steps",
    answer: true,
  });
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy(),
  );
});
```

Add the symmetric OFFER No case and assert it sends the same action with
`answer: false`, then renders the server-returned review. Keep the existing
pessimistic assertion: the old question remains until the request resolves.
Update `driveToCollect` to queue `offerWorkflow` and `collectWorkflow`, pressing
Yes once for each returned `yes_no` view; update `driveToReview` to call that
helper before submitting titles. Give `collectWorkflow`, `reviewWorkflow`,
`completedWorkflow`, and `cancelledWorkflow` exact `task_breakdown`, `review`,
and `completion` views matching Task 3; cancelled has `created_todos: []`.

- [ ] **Step 2: Write breakdown/review/completion/fallback RED tests.**

Update the current breakdown-limit test to use a fixture with `min_titles: 3`
and `max_titles: 4`; assert its alert is exactly
`"Enter 3 to 4 todo titles, one per line."`. Update the review and completion
fixtures so rendered titles and created todos come only from `view`, not
`context` or `result`. Add these focused cases:

```typescript
it("preserves a draft when a refetch keeps the same step id", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  await driveToCollect(api);
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Send invitations",
  );

  act(() => client.setQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID), collectWorkflow));
  expect(screen.getByDisplayValue("Send invitations")).toBeTruthy();
});

it("clears draft and local error when step id changes", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  await driveToCollect(api);
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Only one",
  );
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  expect(screen.getByRole("alert")).toBeTruthy();

  act(() =>
    client.setQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID), {
      ...collectWorkflow,
      state: "FUTURE_COLLECT",
      view: {
        type: "task_breakdown",
        step_id: `${WORKFLOW_ID}:FUTURE_COLLECT`,
        title: "Break it into smaller todos",
        min_titles: 3,
        max_titles: 4,
      },
    }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp("value", ""),
  );
  expect(screen.queryByRole("alert")).toBeNull();
});

it("renders an unsupported view without submitting", async () => {
  const api = makeApi();
  api.startWorkflow.mockResolvedValueOnce({
    ...assessWorkflow,
    state: "FUTURE_STATE",
    view: {
      type: "unsupported",
      server_type: "future_template",
      step_id: `${WORKFLOW_ID}:FUTURE_STATE`,
    },
  });
  await renderHost(api);
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

  expect(screen.getByText("This planning step needs a newer app version.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Back to todos" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy();
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
});
```

Retain the current terminal, cancel, uncertainty, focus, and accessibility
tests. Split the existing invalidation assertion into completed and cancelled
cases; only the completed fixture may observe `invalidateQueries({ queryKey:
["todos"] })`.

- [ ] **Step 3: Run the component suite and observe RED.**

Run: `pnpm --dir apps/mobile test --runInBand src/todoWorkflows/TodoWorkflowScreen.test.tsx`
Expected: FAIL because the registry, shared template, and fallback do not exist.

- [ ] **Step 4: Implement the registry host.**

Rename the four existing screen components to templates and make their display
data explicit props. Reuse their JSX, styles, refs, labels, and action wiring;
do not introduce a component framework. Define the registry once:

```typescript
const templateRegistry = {
  yes_no: YesNoTemplate,
  task_breakdown: TaskBreakdownTemplate,
  review: ReviewTemplate,
  completion: CompletionTemplate,
} as const;
```

Delete `announcedState`, its `TodoWorkflowState` import, and every
`snapshot.state` branch. Leave the string compatibility alias in the
transport; it encodes no allowlist. Drive reset,
completion invalidation, and local breakdown bounds from the view:

```typescript
const stepId = snapshot?.view.step_id;
const previousStepId = useRef<string | null>(null);
useEffect(() => {
  if (stepId === undefined || stepId === previousStepId.current) return;
  previousStepId.current = stepId;
  setTasksDraft("");
  setLocalError(null);
  setWriteError(null);
  setFocusSignal((signal) => signal + 1);
}, [stepId]);

const completion =
  snapshot?.view.type === "completion" ? snapshot.view : undefined;
useEffect(() => {
  if (completion?.outcome === "completed") {
    void queryClient.invalidateQueries({ queryKey: ["todos"] });
  }
}, [completion?.outcome, completion?.step_id, queryClient]);

const breakdown =
  snapshot?.view.type === "task_breakdown" ? snapshot.view : undefined;
if (breakdown === undefined) return;
if (
  (lines.length < breakdown.min_titles || lines.length > breakdown.max_titles)
) {
  setLocalError(
    `Enter ${breakdown.min_titles} to ${breakdown.max_titles} todo titles, one per line.`,
  );
  return;
}
```

Use one exhaustive switch solely to narrow the discriminated view, selecting
the component through the registry. The cases must have these inputs/actions:

```typescript
switch (view.type) {
  case "yes_no": {
    const Template = templateRegistry.yes_no;
    return (
      <Template
        key={view.step_id}
        view={view}
        onAnswer={sendAnswer}
        onCancel={cancel}
        disabled={buttonsDisabled}
        submitting={advancePending}
        yesRef={yesButton}
      />
    );
  }
  case "task_breakdown": {
    const Template = templateRegistry.task_breakdown;
    return (
      <Template
        key={view.step_id}
        view={view}
        draft={tasksDraft}
        onChangeDraft={setTasksDraft}
        onSubmit={submitTasks}
        onCancel={cancel}
        disabled={buttonsDisabled}
        submitting={advancePending}
        inputRef={tasksInput}
      />
    );
  }
  case "review": {
    const Template = templateRegistry.review;
    return (
      <Template
        key={view.step_id}
        view={view}
        onConfirm={confirm}
        onCancel={cancel}
        disabled={buttonsDisabled}
        submitting={advancePending}
        confirmRef={confirmButton}
      />
    );
  }
  case "completion": {
    const Template = templateRegistry.completion;
    return (
      <Template
        key={view.step_id}
        view={view}
        onExit={onExit}
        backRef={backButton}
      />
    );
  }
  case "unsupported":
    return <UnsupportedTemplate key={view.step_id} onExit={onExit} onReload={reload} />;
}
```

Thread the existing disabled/submitting/ref props through these calls as they
are today. `sendAnswer` converts action id `"yes"` to `true` and `"no"` to
`false`; `task_breakdown` alone sends `submit_tasks`, `review` alone sends
`confirm`, and every nonterminal known template retains Cancel. Announce the
`yes_no` question or the other known view's title, and focus by `view.type`.
The unsupported template offers only **Back to todos** and **Reload plan**.

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
