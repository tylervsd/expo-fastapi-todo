# Phase 7 Backend Workflow Modeling Implementation Plan

**Status:** Approved specification; implementation not started (2026-09-07)

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an authenticated, persisted guided-todo workflow whose backend
owns branching and atomically creates ordinary todos only after confirmation.

**Architecture:** A database-free Python domain module decides transitions; a
concrete service owns SQLAlchemy transactions across a workflow repository and
the existing todo repository. FastAPI exposes command-oriented endpoints, and
the existing Expo shell uses TanStack Query to render dedicated components from
authoritative workflow snapshots without predicting next state.

**Tech Stack:** Python 3.14, FastAPI 0.141.1, Pydantic, PostgreSQL 18.6,
SQLAlchemy 2.x, Alembic, Expo SDK 57.0.19, React 19.2.3, TypeScript 6.0.3,
TanStack Query 5.102.8, pytest, Jest, React Native Testing Library.

**Spec:**
`docs/superpowers/specs/2026-09-07-backend-workflow-modeling-design.md`

## Planning record

This document is a future execution plan. During planning, the repository and
approved specification were inspected and the specification's isolated
Markdown lint passed. No application code, migrations, application tests,
manual acceptance, completion tag, push, or pull request has been performed.
Every unchecked command below is planned for implementation and must not be
reported as passing until it has actually run successfully.

## Global constraints

- Start from the commit containing this plan and the approved specification.
  The approved specification was committed as `2493786`.
- Read `AGENTS.md`, `apps/mobile/AGENTS.md`, and the exact Expo SDK 57
  documentation before mobile edits.
- Preserve the existing quick-add UI and exact authenticated `/todos` contract.
- Add only `ASSESS_TASK`, `COLLECT_TASKS`, `REVIEW`, `COMPLETED`, and
  `CANCELLED`; do not add `OFFER_BREAKDOWN`.
- Clients submit `action` plus input, never `state` or `next_state`. GET and
  rendering are side-effect free. Workflow mutations are never optimistic and
  never retried automatically.
- Reuse ECMAScript trim, strict string handling, NUL/surrogate rejection, and
  the 1-120-code-point todo-title rule. Accept 2-10 breakdown titles in order;
  preserve duplicates.
- Use explicit Python transition logic. Add no workflow framework, generic
  repository interface, template registry, navigation dependency, or AI task
  generation.
- Persist owner, state, answer, ordered proposed titles, and completion result.
  Add no timestamp, active index, revision, step ID, idempotency key, definition
  version, discovery endpoint, or placeholder for Phase 8/9.
- Service functions own workflow write transactions. Confirmation locks one
  owner-scoped workflow row and commits created todos, result, and `COMPLETED`
  together.
- Preserve exact Phase 6 `401`, owner-hidden `404`, and database `503`
  behavior. Another owner's workflow is indistinguishable from an absent one.
- Keep existing query-cache clearing on authentication transitions. Key a
  workflow snapshot by `['todo-workflow', userPublicId, workflowId]`.
- Preserve safe area, scrolling, keyboard insets, explicit roles, alerts,
  disabled semantics, focus behavior, and 44-point targets on web and iOS.
- Use real PostgreSQL tests for persistence and rollback. Keep transition-table
  tests database-free.
- Do not create Guide 07, advance README implementation status, mark the phase
  complete, or tag a checkpoint until Tasks 1-7 are implemented and verified.
- Preserve unrelated untracked files, including root `AGENTS.md` and `.pi/`.
- Luna implementers may execute mechanical plan steps but must return any
  architecture or scope issue to the Sol controller. Sol performs significant
  review and the final whole-branch review.

## File map

### Backend domain and persistence

- Create `apps/api/app/title_validation.py`: the existing canonical title rule
  shared by todo and workflow request models.
- Create `apps/api/app/workflow_domain.py`: states, immutable commands,
  snapshots, transition decisions, and pure transition validation.
- Create `apps/api/app/workflow_repository.py`: `WorkflowRow` and concrete
  owner-scoped insert/read/lock/update SQLAlchemy operations.
- Create `apps/api/app/workflow_service.py`: start, fetch, and transactional
  advance orchestration, including atomic todo creation and result storage.
- Create
  `apps/api/alembic/versions/2026090702_add_todo_workflows.py`: the explicit
  `todo_workflows` schema migration.
- Modify `apps/api/alembic/env.py`: import workflow metadata before migrations.
- Modify `apps/api/app/main.py`: reuse title validation and add strict workflow
  request/response models and authenticated routes.

### Backend tests

- Create `apps/api/tests/test_workflow_domain.py`: table-driven pure transition
  and workflow-validation tests.
- Create `apps/api/tests/test_workflow_persistence.py`: repository and service
  tests against real PostgreSQL, including atomic rollback.
- Create `apps/api/tests/test_workflows.py`: authenticated API, ownership,
  OpenAPI, CORS, saved-progress, and error-contract tests.
- Modify `apps/api/tests/conftest.py`: expect revision `2026090702` and truncate
  workflows with the existing guarded test database.
- Modify `apps/api/tests/test_persistence.py`: assert the new migration shape
  without weakening existing table assertions.
- Modify `apps/api/tests/test_validation.py`: prove the extracted title helper
  preserves existing TodoCreate/TodoUpdate behavior.

### Frontend transport and presentation

- Modify `apps/mobile/src/todos/todoApi.ts`: add workflow types, strict runtime
  response validation, action transport, and `conflict` error mapping while
  reusing the existing request lifecycle.
- Modify `apps/mobile/src/todos/todoApi.test.ts`: workflow transport and runtime
  contract coverage.
- Modify `apps/mobile/src/auth/authenticatedApi.ts` and its test: inject Bearer
  credentials and preserve mid-session `401` sign-out for workflow calls.
- Create `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx`: start host,
  state-keyed cache, pessimistic submissions, uncertain-result recovery, and
  six dedicated screen components.
- Create `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx`: both
  branches, cancellation, validation, uncertainty, terminal behavior, cache
  invalidation, focus, and accessibility.
- Create `apps/mobile/src/TodoExperience.tsx`: local signed-in shell switch
  between the todo list and guided workflow.
- Create `apps/mobile/src/TodoExperience.test.tsx`: entry, exit, and quick-add
  preservation.
- Modify `apps/mobile/src/TodoScreen.tsx` and its test: add the separate
  **Help me plan a task** entry without changing quick-add behavior.
- Modify `apps/mobile/src/auth/AuthProvider.tsx` and its test: render
  `TodoExperience` with user identity and the authenticated combined API.
- Modify `apps/mobile/App.test.tsx`: retain the app-lifetime QueryClient and
  authenticated composition regression.

### Documentation after verified implementation

- Create `docs/guides/07-backend-workflows.md` only in Task 8.
- Modify `README.md`, `docs/curriculum-roadmap.md`, the approved specification,
  and this plan only after feature verification and observed acceptance.

### Task 1: Extract title validation and build the pure workflow domain

**Files:**

- Create: `apps/api/app/title_validation.py`
- Create: `apps/api/app/workflow_domain.py`
- Create: `apps/api/tests/test_workflow_domain.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/tests/test_validation.py`

**Interfaces:**

- Consumes: the exact canonical title behavior currently implemented by
  `app.main.canonicalize_title`.
- Produces:

```python
def canonicalize_title(title: str) -> str: ...

class WorkflowState(StrEnum):
    ASSESS_TASK = "ASSESS_TASK"
    COLLECT_TASKS = "COLLECT_TASKS"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

@dataclass(frozen=True)
class CreatedTodo:
    id: UUID
    title: str
    completed: bool

@dataclass(frozen=True)
class WorkflowSnapshot:
    id: UUID
    state: WorkflowState
    title: str
    involves_multiple_steps: bool | None
    proposed_todo_titles: tuple[str, ...]
    created_todos: tuple[CreatedTodo, ...] | None

@dataclass(frozen=True)
class AnswerMultipleSteps:
    answer: bool

@dataclass(frozen=True)
class SubmitTasks:
    titles: tuple[str, ...]

@dataclass(frozen=True)
class Confirm: ...

@dataclass(frozen=True)
class Cancel: ...

WorkflowCommand = AnswerMultipleSteps | SubmitTasks | Confirm | Cancel

@dataclass(frozen=True)
class TransitionDecision:
    state: WorkflowState
    involves_multiple_steps: bool | None
    proposed_todo_titles: tuple[str, ...]
    todo_titles_to_create: tuple[str, ...]

class InvalidWorkflowAction(ValueError): ...
class TerminalWorkflow(ValueError): ...
class InvalidWorkflowInput(ValueError): ...

def create_initial_snapshot(workflow_id: UUID, title: str) -> WorkflowSnapshot: ...
def create_submit_tasks(titles: Sequence[str]) -> SubmitTasks: ...
def transition(snapshot: WorkflowSnapshot,
               command: WorkflowCommand) -> TransitionDecision: ...
```

- `create_initial_snapshot` canonicalizes the original title and returns
  `ASSESS_TASK` with null answer, empty proposals, and null result.
- `create_submit_tasks` requires 2-10 canonical titles and preserves order and
  duplicates.
- `transition` handles cancellation from all three active states, raises
  `TerminalWorkflow` before considering commands in terminal states, and
  raises `InvalidWorkflowAction` for a well-formed command used in the wrong
  active state.

- [ ] **Step 1: Write failing title-extraction regressions.**

Add imports from `app.title_validation` in `test_validation.py`, while retaining
the existing TodoCreate/TodoUpdate cases. Add this direct contract:

```python
@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("  Plan birthday party  ", "Plan birthday party"),
        ("😀" * 120, "😀" * 120),
    ],
)
def test_shared_title_validation(raw: str, canonical: str) -> None:
    assert canonicalize_title(raw) == canonical
```

Retain direct rejection cases for empty/whitespace-only, 121 code points, NUL,
and both unpaired surrogate halves.

- [ ] **Step 2: Run the focused validation test and observe RED.**

Run:

```bash
uv run --directory apps/api python -m pytest tests/test_validation.py -v
```

Expected: FAIL during collection because `app.title_validation` does not exist.

- [ ] **Step 3: Move, do not copy, the title canonicalizer.**

Create `title_validation.py` with `ECMASCRIPT_TRIM_CHARS` and
`canonicalize_title`. Import it into `main.py`; delete the old constant and
function there. Keep `TodoCreate` and `TodoUpdate` validators unchanged except
for their import source.

- [ ] **Step 4: Verify the title behavior is green.**

Run the Step 2 command. Expected: all existing and new validation tests PASS.

- [ ] **Step 5: Write the complete table-driven domain tests.**

In `test_workflow_domain.py`, use a fixed UUID and helper snapshots. Cover:

```python
@pytest.mark.parametrize(
    ("answer", "state", "proposals"),
    [
        (True, WorkflowState.COLLECT_TASKS, ()),
        (False, WorkflowState.REVIEW, ("Plan birthday party",)),
    ],
)
def test_assessment_branches(answer, state, proposals): ...

@pytest.mark.parametrize(
    "state",
    [WorkflowState.ASSESS_TASK,
     WorkflowState.COLLECT_TASKS,
     WorkflowState.REVIEW],
)
def test_cancel_is_valid_from_every_active_state(state): ...

@pytest.mark.parametrize(
    ("state", "command"),
    [
        (WorkflowState.ASSESS_TASK, Confirm()),
        (WorkflowState.ASSESS_TASK,
         SubmitTasks(("Send invitations", "Buy decorations"))),
        (WorkflowState.COLLECT_TASKS, AnswerMultipleSteps(False)),
        (WorkflowState.COLLECT_TASKS, Confirm()),
        (WorkflowState.REVIEW, AnswerMultipleSteps(True)),
        (WorkflowState.REVIEW,
         SubmitTasks(("Send invitations", "Buy decorations"))),
    ],
)
def test_wrong_state_action_rejects_without_mutating_snapshot(state, command): ...
```

Also prove collection enters `REVIEW`; confirm returns exactly the stored
proposal list as `todo_titles_to_create`; both terminal states reject every
command; 1 and 11 titles fail; 2 and 10 pass; each title uses shared
canonicalization; duplicates and ordering survive.

- [ ] **Step 6: Run the domain suite and observe RED.**

Run:

```bash
uv run --directory apps/api python -m pytest tests/test_workflow_domain.py -v
```

Expected: FAIL because `app.workflow_domain` and its types do not exist.

- [ ] **Step 7: Implement the minimum pure transition function.**

Use frozen dataclasses and one explicit `match snapshot.state` statement. Do
not add transition registries, callbacks, decorators, or a workflow base class.
Return a new decision; never mutate the supplied snapshot.

- [ ] **Step 8: Verify and commit Task 1.**

Run:

```bash
uv run --directory apps/api python -m pytest tests/test_workflow_domain.py tests/test_validation.py -v
pnpm lint:api
git diff --check
```

Expected: all focused tests PASS, Ruff PASS, and no whitespace errors.

Commit boundary:

```bash
git add apps/api/app/title_validation.py apps/api/app/workflow_domain.py \
  apps/api/app/main.py apps/api/tests/test_workflow_domain.py \
  apps/api/tests/test_validation.py
git commit -m "feat: model guided todo workflow transitions"
```

### Task 2: Add workflow migration and owner-scoped repository

**Files:**

- Create: `apps/api/app/workflow_repository.py`
- Create: `apps/api/alembic/versions/2026090702_add_todo_workflows.py`
- Modify: `apps/api/alembic/env.py`
- Modify: `apps/api/tests/conftest.py`
- Modify: `apps/api/tests/test_persistence.py`
- Create: `apps/api/tests/test_workflow_persistence.py`

**Interfaces:**

- Consumes: `Base`, `Session`, Phase 6 `users(id)`, and the five exact
  `WorkflowState` string values.
- Produces:

```python
class WorkflowRow(Base):
    __tablename__ = "todo_workflows"
    id: Mapped[int]
    public_id: Mapped[UUID]
    owner_id: Mapped[int]
    state: Mapped[str]
    title: Mapped[str]
    involves_multiple_steps: Mapped[bool | None]
    proposed_todo_titles: Mapped[list[str]]
    completion_result: Mapped[dict[str, object] | None]

def create_workflow(session: Session, public_id: UUID,
                    owner_id: int, title: str) -> WorkflowRow: ...
def find_workflow(session: Session, public_id: UUID,
                  owner_id: int) -> WorkflowRow | None: ...
def lock_workflow(session: Session, public_id: UUID,
                  owner_id: int) -> WorkflowRow | None: ...
def update_workflow(
    session: Session,
    row: WorkflowRow,
    *,
    state: str,
    involves_multiple_steps: bool | None,
    proposed_todo_titles: list[str],
    completion_result: dict[str, object] | None,
) -> WorkflowRow: ...
```

`lock_workflow` uses `select(...).where(public_id, owner_id).with_for_update()`.
`update_workflow` assigns the supplied values and flushes; it does not commit.

- [ ] **Step 1: Write the migration-shape RED tests.**

Update `REVISION` in `conftest.py` and `test_persistence.py` to `2026090702`.
Add `todo_workflows` to the expected table list and assert exact column order,
types, nullability, identity, public-ID uniqueness, owner cascade FK, state and
title checks, and JSON-type checks. Update cleanup to:

```sql
TRUNCATE users, sessions, todos, todo_workflows RESTART IDENTITY CASCADE
```

Do not remove any existing users, sessions, or todos assertions.

- [ ] **Step 2: Run migration tests and observe RED.**

Run:

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest \
  tests/test_persistence.py::test_migration_creates_expected_todos_shape -v
```

Expected: FAIL because Alembic head is still `2026090701` and the table is
absent.

- [ ] **Step 3: Create the exact Alembic revision and register metadata.**

The upgrade creates `todo_workflows` with:

- `BIGINT IDENTITY` primary key;
- unique non-null UUID `public_id`;
- non-null owner FK with `ON DELETE CASCADE`;
- non-null text state plus named check for the five states;
- non-null text title plus named 1-120 character check;
- nullable Boolean answer;
- non-null JSONB proposals with server default `'[]'::jsonb` and array check;
- nullable JSONB completion result with object-when-present check.

The downgrade drops only `todo_workflows`. Import `WorkflowRow` in Alembic's
environment so its table is registered on the shared `Base.metadata`.

- [ ] **Step 4: Run the migration test to green.**

Run the Step 2 command. Expected: PASS with database revision `2026090702`.

- [ ] **Step 5: Write repository RED tests in the new focused file.**

Using real `database_session`, create two users and prove:

- insert flushes an `ASSESS_TASK` row with empty proposals;
- a new SQLAlchemy session reads accepted progress after commit;
- `find_workflow` and `lock_workflow` return `None` for another owner;
- `update_workflow` persists Boolean answer and ordered duplicate proposals;
- a rolled-back update leaves the committed row unchanged;
- deleting the owner cascades to their workflow at repository level.

- [ ] **Step 6: Run repository tests and observe RED.**

Run:

```bash
uv run --directory apps/api python -m pytest \
  tests/test_workflow_persistence.py -v
```

Expected: FAIL because repository functions are missing.

- [ ] **Step 7: Implement the concrete mapping and four operations.**

Use PostgreSQL `UUID` and `JSONB`, existing `BigInteger`/`Identity` conventions,
and no relationship objects or generic repository class. Copy mutable JSON
values at the boundary so callers cannot mutate ORM state after persistence.

- [ ] **Step 8: Verify and commit Task 2.**

Run:

```bash
uv run --directory apps/api python -m pytest \
  tests/test_persistence.py tests/test_workflow_persistence.py -v
pnpm lint:api
git diff --check
```

Expected: migration and repository tests PASS with the guarded real database.

Commit boundary:

```bash
git add apps/api/app/workflow_repository.py apps/api/alembic/env.py \
  apps/api/alembic/versions/2026090702_add_todo_workflows.py \
  apps/api/tests/conftest.py apps/api/tests/test_persistence.py \
  apps/api/tests/test_workflow_persistence.py
git commit -m "feat: persist owner-scoped todo workflows"
```

### Task 3: Implement transactional workflow service orchestration

**Files:**

- Create: `apps/api/app/workflow_service.py`
- Modify: `apps/api/tests/test_workflow_persistence.py`

**Interfaces:**

- Consumes: Task 1 domain values, Task 2 workflow repository, and existing
  `todo_repository.create_todo(session, public_id, title, owner_id)`.
- Produces:

```python
def start_workflow(session: Session, owner_id: int,
                   title: str) -> WorkflowSnapshot: ...
def get_workflow(session: Session, owner_id: int,
                 workflow_id: UUID) -> WorkflowSnapshot | None: ...
def advance_workflow(session: Session, owner_id: int,
                     workflow_id: UUID,
                     command: WorkflowCommand) -> WorkflowSnapshot | None: ...
```

`start_workflow` and `advance_workflow` own `with session.begin()` blocks.
`get_workflow` performs a read only. `advance_workflow` locks the owner-scoped
row, invokes `transition`, inserts todos only when
`todo_titles_to_create` is nonempty, stores exact JSON snapshots, updates the
workflow, and commits before returning.

- [ ] **Step 1: Write service RED tests for persisted journeys.**

Extend `test_workflow_persistence.py` with real-PostgreSQL cases that prove:

- start commits `ASSESS_TASK` and creates zero todos;
- Yes persists `COLLECT_TASKS`, then submission persists `REVIEW` across a fresh
  session, still with zero todos;
- No persists `REVIEW` with only the original title;
- cancel from each active state persists `CANCELLED` and zero todos;
- confirm on the simple path creates one ordinary todo;
- confirm on the breakdown path creates the exact ordered ordinary todos;
- both completion snapshots contain the created UUID/title/completed values;
- another owner gets `None` from fetch and advance without changing the row.

- [ ] **Step 2: Add the required completion rollback RED test.**

Monkeypatch the service's imported todo creator so its second call raises a
sentinel exception after the first real insert:

```python
real_create = workflow_service.create_todo
calls = 0

def fail_after_one(*args, **kwargs):
    nonlocal calls
    calls += 1
    if calls == 2:
        raise RuntimeError("forced completion failure")
    return real_create(*args, **kwargs)
```

After the exception, verify in a fresh session that todo count is unchanged and
the workflow remains `REVIEW` with null completion result.

- [ ] **Step 3: Add the invalid-action learning experiment at service level.**

Start `Plan birthday party`, record the workflow row and owner's todo count,
submit `Confirm()` in `ASSESS_TASK`, and assert `InvalidWorkflowAction`. In a
fresh session assert the row and todo count are byte-for-byte/value-for-value
unchanged.

- [ ] **Step 4: Run service tests and observe RED.**

Run:

```bash
uv run --directory apps/api python -m pytest \
  tests/test_workflow_persistence.py -v
```

Expected: FAIL because `app.workflow_service` is missing.

- [ ] **Step 5: Implement row/snapshot mapping and service transactions.**

Serialize completion results exactly as:

```python
{"created_todos": [
    {"id": str(todo.public_id),
     "title": todo.title,
     "completed": todo.completed}
]}
```

Deserialize only the schema this service wrote. Do not re-read created todos on
future workflow GETs; the stored result is the immutable completion snapshot.
Let domain exceptions escape for the HTTP adapter. Do not catch general
exceptions inside the transaction.

- [ ] **Step 6: Verify the transaction suite and commit Task 3.**

Run:

```bash
uv run --directory apps/api python -m pytest \
  tests/test_workflow_domain.py tests/test_workflow_persistence.py -v
pnpm lint:api
git diff --check
```

Expected: all domain and real-PostgreSQL service tests PASS, including forced
rollback.

Commit boundary:

```bash
git add apps/api/app/workflow_service.py \
  apps/api/tests/test_workflow_persistence.py
git commit -m "feat: advance todo workflows transactionally"
```

### Task 4: Publish the authenticated workflow HTTP contract

**Files:**

- Modify: `apps/api/app/main.py`
- Create: `apps/api/tests/test_workflows.py`
- Modify: `apps/api/tests/test_auth.py`
- Modify: `apps/api/tests/test_todos.py`

**Interfaces:**

- Consumes: Task 3 service and existing `get_current_user`/`get_session`.
- Produces exact endpoints:

```text
POST /todo-workflows                         -> 201 TodoWorkflowResponse
GET  /todo-workflows/{workflow_id}           -> 200 TodoWorkflowResponse
POST /todo-workflows/{workflow_id}/actions   -> 200 TodoWorkflowResponse
```

Request models use `ConfigDict(extra="forbid")`, strict fields, and a
discriminated union:

```python
class TodoWorkflowStart(BaseModel):
    title: StrictStr

class AnswerMultipleStepsAction(BaseModel):
    action: Literal["answer_multiple_steps"]
    answer: StrictBool

class SubmitTasksAction(BaseModel):
    action: Literal["submit_tasks"]
    titles: list[StrictStr]

class ConfirmAction(BaseModel):
    action: Literal["confirm"]

class CancelAction(BaseModel):
    action: Literal["cancel"]

TodoWorkflowAction = Annotated[
    AnswerMultipleStepsAction | SubmitTasksAction | ConfirmAction | CancelAction,
    Field(discriminator="action"),
]
```

Response models always expose exactly `workflow_id`, `state`, `title`,
`context`, and `result`. `context` exposes exactly
`involves_multiple_steps` and `proposed_todo_titles`; `result` is null unless
completed and then exposes exactly `created_todos` using the existing Todo
shape.

- [ ] **Step 1: Write API RED tests for both complete journeys.**

In `test_workflows.py`, reuse local signup/login helpers or a fixture equivalent
to existing tests. Execute the exact birthday-party requests from the spec and
assert every status and full JSON response:

- start returns `201 ASSESS_TASK`, null answer, empty proposals/result;
- Yes returns `COLLECT_TASKS`;
- valid titles return `REVIEW` with exact order;
- confirm returns `COMPLETED` with exact created todo snapshots;
- owner `GET /todos` contains exactly those new todos;
- the separate No branch reviews and creates one original-title todo.

- [ ] **Step 2: Write API RED tests for cancellation and terminal behavior.**

Parameterize cancellation from each active state and prove a `200 CANCELLED`
snapshot plus unchanged todo count. For both terminal states, parameterize all
four well-formed action shapes and expect exact:

```json
{"detail":"Todo workflow is already terminal."}
```

with status `409` and no changed workflow/result/todos.

- [ ] **Step 3: Write validation, ownership, and saved-progress RED tests.**

Cover:

- invalid start title, strict Boolean, unknown discriminator, missing/extra
  fields, 1/11 titles, and an invalid individual title as `422`;
- `confirm` in `ASSESS_TASK` as exact wrong-state `409`, followed by GET and
  todo-count assertions proving no mutation (the required learning experiment);
- owner B receives exact `404 {"detail":"Todo workflow not found."}` for owner
  A's GET and action;
- absent and malformed UUID behavior (`404` and `422` respectively);
- unauthenticated start/get/action all return exact Phase 6 `401`;
- progress fetched through a fresh `TestClient(create_app(session_factory))`
  matches the committed state and GET creates no todos or state change;
- database-unavailable start/get/action return exact existing `503`.

- [ ] **Step 4: Write OpenAPI and CORS RED assertions.**

Assert all three operations, Bearer security, request schema references,
discriminated action union, response schema, and POST/GET preflights using
`Authorization` and `Content-Type`. Existing todo OpenAPI and preflight tests
must remain unchanged and green.

- [ ] **Step 5: Run the API tests and observe RED.**

Run:

```bash
uv run --directory apps/api python -m pytest \
  tests/test_workflows.py tests/test_auth.py tests/test_todos.py -v
```

Expected: workflow tests FAIL with `404` routes or missing imports; existing
auth/todo tests remain green.

- [ ] **Step 6: Implement strict models, mapping, and thin routes.**

Give `TodoWorkflowStart.title` a field validator that calls
`canonicalize_title`. Give `SubmitTasksAction.titles` a field validator that
calls `create_submit_tasks`, then replaces the request value with the returned
canonical title list. Pydantic converts either `ValueError` into the existing
standard `422` response. Map validated actions to domain commands in one
explicit helper: assessment constructs `AnswerMultipleSteps`, submission
constructs `SubmitTasks(tuple(payload.titles))`, and the marker actions construct
`Confirm()` or `Cancel()`.

Map `InvalidWorkflowAction` to exact wrong-state `409`, `TerminalWorkflow` to
exact terminal `409`, missing service result to owner-hidden `404`, and only
`OperationalError`/SQLAlchemy pool `TimeoutError` to existing `503`. Do not add
an active-list endpoint or state-to-view presentation mapper.

- [ ] **Step 7: Verify and commit Task 4.**

Run:

```bash
uv run --directory apps/api python -m pytest \
  tests/test_workflows.py tests/test_auth.py tests/test_todos.py \
  tests/test_persistence.py tests/test_workflow_persistence.py \
  tests/test_validation.py -v
pnpm lint:api
git diff --check
```

Expected: all API, repository, transaction, validation, OpenAPI, and CORS tests
PASS.

Commit boundary:

```bash
git add apps/api/app/main.py apps/api/tests/test_workflows.py \
  apps/api/tests/test_auth.py apps/api/tests/test_todos.py
git commit -m "feat: expose authenticated todo workflow API"
```

### Task 5: Extend the typed authenticated transport

**Files:**

- Modify: `apps/mobile/src/todos/todoApi.ts`
- Modify: `apps/mobile/src/todos/todoApi.test.ts`
- Modify: `apps/mobile/src/auth/authenticatedApi.ts`
- Modify: `apps/mobile/src/auth/authenticatedApi.test.ts`

**Interfaces:**

- Consumes: the Task 4 JSON contract and existing request timeout,
  cancellation, Bearer header, safe-error, and runtime-validation machinery.
- Produces:

```typescript
export type TodoWorkflowState =
  | "ASSESS_TASK"
  | "COLLECT_TASKS"
  | "REVIEW"
  | "COMPLETED"
  | "CANCELLED";

export type TodoWorkflow = {
  workflow_id: string;
  state: TodoWorkflowState;
  title: string;
  context: {
    involves_multiple_steps: boolean | null;
    proposed_todo_titles: string[];
  };
  result: { created_todos: Todo[] } | null;
};

export type TodoWorkflowAction =
  | { action: "answer_multiple_steps"; answer: boolean }
  | { action: "submit_tasks"; titles: string[] }
  | { action: "confirm" }
  | { action: "cancel" };

export function startTodoWorkflow(
  title: string,
  options?: TodoRequestOptions,
): Promise<TodoWorkflow>;
export function getTodoWorkflow(
  id: string,
  options?: TodoRequestOptions,
): Promise<TodoWorkflow>;
export function advanceTodoWorkflow(
  id: string,
  action: TodoWorkflowAction,
  options?: TodoRequestOptions,
): Promise<TodoWorkflow>;
```

Add `"conflict"` to `TodoApiErrorKind`. Extend `TodoScreenApi`'s authenticated
object structurally with:

```typescript
export type TodoWorkflowScreenApi = {
  startWorkflow: (title: string) => Promise<TodoWorkflow>;
  getWorkflow: (id: string,
    options: { signal: AbortSignal }) => Promise<TodoWorkflow>;
  advanceWorkflow: (id: string,
    action: TodoWorkflowAction) => Promise<TodoWorkflow>;
};

export type AuthenticatedApi = TodoScreenApi & TodoWorkflowScreenApi;
```

- [ ] **Step 1: Write workflow transport RED tests.**

Add exact tests for all three URLs/methods/bodies, Bearer header, expected
201/200 statuses, caller cancellation on GET, timeout cleanup, and complete
runtime validation. Reject extra/missing keys, unknown states, malformed UUIDs,
noncanonical titles, bad context, non-null active result, null completed result,
and malformed created todos.

- [ ] **Step 2: Write safe error RED tests.**

Assert `401 -> auth-required`, `409 -> conflict`, `422 -> validation`, all other
unexpected/transport failures -> `unavailable`, and invalid success bodies ->
`invalid-data`. User-visible workflow copy must be fixed safe strings and must
not include response bodies or thrown exception text.

- [ ] **Step 3: Run transport tests and observe RED.**

Run:

```bash
pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts
```

Expected: FAIL because workflow exports and `conflict` do not exist.

- [ ] **Step 4: Extend the existing transport minimally.**

Reuse the private request function, timer/listener cleanup, URL validation, and
`isTodo`. Expand its request-body and operation unions; do not add another fetch
wrapper. Add one strict `isTodoWorkflow` guard with state-dependent result
checks. Keep existing todo/auth behavior byte-for-byte compatible.

- [ ] **Step 5: Write authenticated wrapper RED tests.**

Prove all three workflow calls receive the current token, workflow `401` invokes
the existing sign-out callback and rethrows, and validation/conflict/unavailable
errors do not sign out.

- [ ] **Step 6: Extend the authenticated API and verify.**

Return one `AuthenticatedApi` object containing existing todo methods plus the
three workflow methods. Reuse the same private auth-required guard; do not add a
second provider or token store.

Run:

```bash
pnpm --dir apps/mobile test --runInBand \
  src/todos/todoApi.test.ts src/auth/authenticatedApi.test.ts
pnpm lint:mobile
pnpm typecheck
git diff --check
```

Expected: transport and wrapper tests PASS with lint and typecheck green.

- [ ] **Step 7: Commit Task 5.**

```bash
git add apps/mobile/src/todos/todoApi.ts \
  apps/mobile/src/todos/todoApi.test.ts \
  apps/mobile/src/auth/authenticatedApi.ts \
  apps/mobile/src/auth/authenticatedApi.test.ts
git commit -m "feat: add typed todo workflow transport"
```

### Task 6: Build dedicated authoritative workflow screens

**Files:**

- Create: `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx`
- Create: `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx`

**Interfaces:**

- Consumes: Task 5 `TodoWorkflow`, `TodoWorkflowAction`, and
  `TodoWorkflowScreenApi`; existing QueryClient policy and
  `normalizeTodoTitle`.
- Produces:

```typescript
export function workflowQueryKey(userId: string, workflowId: string) {
  return ["todo-workflow", userId, workflowId] as const;
}

export function TodoWorkflowScreen({
  userId,
  api,
  onExit,
}: {
  userId: string;
  api: TodoWorkflowScreenApi;
  onExit: () => void;
}): React.JSX.Element;
```

The file contains six focused local components:
`WorkflowStartScreen`, `AssessTaskScreen`, `CollectTasksScreen`,
`ReviewWorkflowScreen`, `CompletedWorkflowScreen`, and
`CancelledWorkflowScreen`. An exhaustive switch selects them solely from the
returned backend state.

- [ ] **Step 1: Create the test harness and start-path RED tests.**

Use a fresh QueryClient per case with the production query policy and deferred
API promises. Prove the start form:

- has heading **Help me plan a task**, labelled **Task title**, and local empty/
  length/NUL validation;
- sends canonical `Plan birthday party` once despite rapid press/submit;
- remains on the start screen with disabled controls and **Submitting...** while
  pending;
- renders only the returned `ASSESS_TASK` after success;
- preserves draft on `422`;
- shows the explicit lost-start uncertainty copy on unavailable/invalid data,
  never retries, and warns that another attempt may create another draft.

- [ ] **Step 2: Write both-branch RED component tests.**

For an `ASSESS_TASK` fixture, press Yes and No separately. Assert the old screen
stays visible until the deferred response and the component renders exactly the
returned state, even if it differs from what the pressed button might imply.

For `COLLECT_TASKS`, enter the three birthday titles separated by newlines and
assert the exact `submit_tasks` array. Prove local 1/11-line rejection, blank
line handling, canonicalization, duplicate preservation, draft retention on
`422`, and no optimistic review.

For `REVIEW`, assert the exact backend list and exact `confirm` command. A
`COMPLETED` response displays its persisted created-todo result.

- [ ] **Step 3: Write cancellation and terminal RED tests.**

For each active state, press **Cancel planning**, assert exact
`{action: "cancel"}`, wait for the response, and render `CANCELLED`. Terminal
screens expose only **Back to todos** and no business action. Pressing Back calls
`onExit` once.

- [ ] **Step 4: Write cache and uncertainty RED tests.**

Prove:

- successful start seeds
  `['todo-workflow', userId, workflowId]` with the exact response;
- action success replaces that cache only with the response;
- Reload for a known ID fetches the authoritative snapshot without advancing
  it; a full app remount intentionally loses the locally held ID in Phase 7;
- action `unavailable` or `invalid-data` marks the workflow query stale, keeps
  the prior screen/draft, disables actions, and shows **Reload plan**;
- Reload performs one safe GET, then either advances or retains the screen based
  only on that response;
- `conflict` performs safe reconciliation and shows plan-changed copy;
- completion invalidates `['todos']` but does not create a second todo array.

- [ ] **Step 5: Write accessibility and focus RED tests.**

Assert header, button, input, alert, disabled, and 44-point semantics. After each
authoritative state response, assert focus/announcement targeting for the title
input, first Yes/No action, multiline breakdown input, Confirm, and terminal
Back control. Review rows must have ordered readable labels even where native
list roles are unavailable.

- [ ] **Step 6: Run the new component suite and observe RED.**

Run:

```bash
pnpm --dir apps/mobile test --runInBand \
  src/todoWorkflows/TodoWorkflowScreen.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 7: Implement the smallest state-driven host.**

Use local state only for start/breakdown drafts, current known workflow ID,
focus signals, and visible validation copy. Use TanStack Query for the remote
snapshot and mutations. Keep a synchronous busy ref for rapid-event gating,
matching the existing TodoScreen convention. Do not create a reducer, registry,
navigation stack, or client transition table.

Split multiline input on line boundaries, discard blank-only lines, and
canonicalize each remaining line before submission. Backend validation remains
authoritative.

- [ ] **Step 8: Verify and commit Task 6.**

Run:

```bash
pnpm --dir apps/mobile test --runInBand \
  src/todoWorkflows/TodoWorkflowScreen.test.tsx
pnpm lint:mobile
pnpm typecheck
git diff --check
```

Expected: workflow component tests, lint, and typecheck PASS.

Commit boundary:

```bash
git add apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx \
  apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx
git commit -m "feat: add guided todo workflow screens"
```

### Task 7: Integrate the separate entry point into the signed-in shell

**Files:**

- Create: `apps/mobile/src/TodoExperience.tsx`
- Create: `apps/mobile/src/TodoExperience.test.tsx`
- Modify: `apps/mobile/src/TodoScreen.tsx`
- Modify: `apps/mobile/src/TodoScreen.test.tsx`
- Modify: `apps/mobile/src/auth/AuthProvider.tsx`
- Modify: `apps/mobile/src/auth/AuthProvider.test.tsx`
- Modify: `apps/mobile/App.test.tsx`

**Interfaces:**

- Consumes: Task 5 `AuthenticatedApi`, Task 6 `TodoWorkflowScreen`, and the
  existing TodoScreen.
- Produces:

```typescript
export function TodoExperience({
  userId,
  api,
}: {
  userId: string;
  api: AuthenticatedApi;
}): React.JSX.Element;

export function TodoScreen({
  api,
  onPlanTask,
}: {
  api?: TodoScreenApi;
  onPlanTask?: () => void;
} = {}): React.JSX.Element;
```

`TodoExperience` owns only `"todos" | "workflow"` local shell mode. It starts
on todos, passes `onPlanTask` to TodoScreen, and returns only through the
workflow terminal `onExit` callback.

- [ ] **Step 1: Add the separate-entry RED regression to TodoScreen tests.**

Render with `onPlanTask`, assert a button named **Help me plan a task**, press it,
and assert one callback. Re-run the existing quick-add, filters, CRUD,
uncertainty, accessibility, and cache tests unchanged to prove the new entry is
additive.

- [ ] **Step 2: Write TodoExperience RED tests.**

With injected todo/workflow methods, prove:

- initial mode shows the existing Todos heading, title field, and quick-add;
- pressing the separate entry replaces it with workflow start without making a
  workflow request;
- completing or cancelling and pressing Back returns to TodoScreen;
- returning after completion observes a stale `['todos']` cache and starts the
  existing authoritative GET;
- an active workflow has no silent shell Back control; cancellation is the exit;
- switching users through remount cannot render the prior user's workflow key.

- [ ] **Step 3: Run TodoScreen and shell tests and observe RED.**

Run:

```bash
pnpm --dir apps/mobile test --runInBand \
  src/TodoScreen.test.tsx src/TodoExperience.test.tsx
```

Expected: new tests FAIL for missing entry/shell; existing TodoScreen tests PASS.

- [ ] **Step 4: Implement the entry and two-mode shell.**

Add one secondary Pressable to TodoScreen using existing button styles and
accessibility conventions. Create TodoExperience with a local mode Boolean/
union; do not add Expo Router or another navigation package.

- [ ] **Step 5: Write AuthProvider integration RED tests.**

Update its transport double with the three workflow methods. Prove signed-in
render passes the public user ID, workflow calls carry the current token, a
workflow `401` clears storage/cache and returns to sign-in, and sign-out while a
workflow request settles cannot expose the former user's snapshot to the next
session.

- [ ] **Step 6: Replace direct TodoScreen composition with TodoExperience.**

Keep auth status ownership, token restore, logout, storage, and query clearing
unchanged. Build the authenticated combined API once per render as today; pass
it and `user.id` to TodoExperience. Do not move auth state into TanStack Query.

- [ ] **Step 7: Run the full focused mobile regression.**

Run:

```bash
pnpm --dir apps/mobile test --runInBand \
  src/todoWorkflows/TodoWorkflowScreen.test.tsx \
  src/TodoExperience.test.tsx src/TodoScreen.test.tsx \
  src/auth/authenticatedApi.test.ts src/auth/AuthProvider.test.tsx \
  src/todos/todoApi.test.ts App.test.tsx
pnpm lint:mobile
pnpm typecheck
pnpm build:web
git diff --check
```

Expected: all focused mobile tests PASS, TypeScript and lint PASS, and Expo web
export completes successfully.

- [ ] **Step 8: Commit Task 7.**

```bash
git add apps/mobile/src/TodoExperience.tsx \
  apps/mobile/src/TodoExperience.test.tsx apps/mobile/src/TodoScreen.tsx \
  apps/mobile/src/TodoScreen.test.tsx apps/mobile/src/auth/AuthProvider.tsx \
  apps/mobile/src/auth/AuthProvider.test.tsx apps/mobile/App.test.tsx
git commit -m "feat: integrate guided planning into todo experience"
```

### Task 8: Verify, teach, accept, review, and checkpoint Phase 7

**Files:**

- Create: `docs/guides/07-backend-workflows.md`
- Modify: `README.md`
- Modify: `docs/curriculum-roadmap.md`
- Modify:
  `docs/superpowers/specs/2026-09-07-backend-workflow-modeling-design.md`
- Modify:
  `docs/superpowers/plans/2026-09-07-backend-workflow-modeling.md`

**Interfaces:**

- Consumes: implemented and verified Tasks 1-7.
- Produces: the learner guide, observed web/iOS acceptance record, accurate
  Phase 7 status, reviewed integration commit, and only after passing CI the
  annotated `phase-07-backend-workflows` checkpoint.

- [ ] **Step 1: Run focused automated acceptance before writing the guide.**

Run:

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest \
  tests/test_workflow_domain.py tests/test_workflow_persistence.py \
  tests/test_workflows.py tests/test_validation.py -v
pnpm --dir apps/mobile test --runInBand \
  src/todoWorkflows/TodoWorkflowScreen.test.tsx \
  src/TodoExperience.test.tsx src/todos/todoApi.test.ts \
  src/auth/authenticatedApi.test.ts
```

Expected: all targeted transition, persistence, transaction, API, transport,
and component tests PASS. If any fail, return to the owning task; do not create
the guide or change status.

- [ ] **Step 2: Run the complete repository gate.**

Run:

```bash
pnpm quality
git diff --check
```

Expected: Markdown, links, shell checks, repository contracts, doctor tests,
mobile lint/typecheck/tests, API lint/tests, and web export all PASS. Record
actual results; do not convert network-unavailable link checks into false
success.

- [ ] **Step 3: Write Guide 07 from verified behavior.**

Create `docs/guides/07-backend-workflows.md` with these sections:

1. CRUD versus backend-owned workflow.
2. State, action, context, and transition responsibilities.
3. The `todo_workflows` persistence shape and owner boundary.
4. Service transactions and completion rollback.
5. Exact API commands and current-state responses.
6. Frontend cache versus local interaction state.
7. The simple birthday-party walkthrough.
8. The breakdown birthday-party walkthrough.
9. The invalid-action experiment using `confirm` in `ASSESS_TASK`, including
   GET/todo-count verification that nothing changed.
10. Uncertain submission recovery and the unrecoverable lost-start limitation.
11. Focused commands that were actually verified.
12. Work deferred to Phase 8 (`OFFER_BREAKDOWN`, presentation mapper,
    templates) and Phase 9 (discovery, revisions, idempotency, versions,
    cross-device reliability).
13. An initially unchecked web/iOS Phase 7 acceptance table.

Do not claim a command or observation that was not performed.

- [ ] **Step 4: Update documentation entry points without premature claims.**

After automated verification, link Guide 07 from README. Describe Phase 7 as
implemented only after manual acceptance succeeds. Update the roadmap Phase 7
spec gate and implementation status accurately. Keep Phases 8-11 planned. Do
not renumber guides or change Phase 6 history.

- [ ] **Step 5: Run the manual birthday-party acceptance journey.**

Start the application from the repository root:

```bash
pnpm db:up
pnpm db:migrate
pnpm dev:api
pnpm dev:mobile
```

On both `http://localhost:8081` and the designated reference iOS Simulator:

1. Sign in and prove existing quick-add still creates an ordinary todo.
2. Start `Plan birthday party`; verify no todo is created in `ASSESS_TASK`.
3. Take No to REVIEW, confirm, return, and observe one original-title todo.
4. Start another birthday workflow; take Yes; enter the three example titles;
   confirm exact REVIEW content; confirm; return and observe exactly three new
   ordinary todos.
5. Cancel separate workflows from ASSESS_TASK, COLLECT_TASKS, and REVIEW; verify
   no corresponding todos.
6. Run the invalid-action API experiment with the signed-in token and known
   workflow UUID: submit `confirm` in ASSESS_TASK, receive exact `409`, GET the
   same state, and verify `/todos` is unchanged.
7. Restart FastAPI mid-workflow and fetch the known workflow to prove progress
   survives.
8. Stop FastAPI for an action, observe uncertain-result lock, restart it, press
   Reload plan, and verify the backend response alone determines the screen.
9. Verify heading announcement, focus movement, keyboard submission, disabled
   pending controls, alerts, and 44-point targets on each target.

Record actual dates, Expo/iOS runtime, results, and any platform-specific
observation in Guide 07. Do not claim cross-device discovery or app-reload
resume; those remain Phase 9 work.

- [ ] **Step 6: Mark local acceptance only after the evidence exists.**

When both target rows are checked and automated gates are green, update the
spec and plan status to `Locally accepted (YYYY-MM-DD)`, advance README's
current checkpoint to Phase 7, and state that Phase 8 remains planned. If either
target is unverified, retain an explicit pending status.

- [ ] **Step 7: Verify documentation and commit the teaching checkpoint.**

Run:

```bash
pnpm lint:markdown
pnpm lint:links
pnpm quality
git diff --check
```

Expected: all checks PASS on the documented implementation. Commit only after
the output supports the recorded claims:

```bash
git add docs/guides/07-backend-workflows.md README.md \
  docs/curriculum-roadmap.md \
  docs/superpowers/specs/2026-09-07-backend-workflow-modeling-design.md \
  docs/superpowers/plans/2026-09-07-backend-workflow-modeling.md
git commit -m "docs: add backend workflow learning guide"
```

- [ ] **Step 8: Obtain final review and resolve every finding.**

Use `gpt-5.6-sol` for a whole-branch review against the approved specification.
Review domain purity, state/action completeness, owner scoping, lock and
transaction boundaries, rollback evidence, HTTP exactness, cache isolation,
uncertain-result behavior, accessibility, and documentation accuracy. Apply
review feedback through the receiving-code-review workflow and rerun the
affected focused suites plus `pnpm quality`.

- [ ] **Step 9: Integrate and create the checkpoint only after exact-commit CI.**

Integrate the reviewed commits using the repository's normal process. Wait for
GitHub quality CI to pass on that exact integrated commit. Only then create the
annotated tag:

```bash
git tag -a phase-07-backend-workflows -m "Phase 7: Backend workflow modeling"
```

Never tag pending/failing CI, never use a curriculum-doc commit as evidence of
feature completion, and do not push or open a PR unless separately authorized.

## Spec coverage check

- Goals, non-goals, both user journeys, arbitrary titles, and no AI hierarchy:
  Tasks 1, 3, 4, 6, and 7.
- Complete transition table, cancellation, wrong-state actions, validation, and
  terminal behavior: Tasks 1, 3, and 4.
- Domain/service/HTTP/SQL/frontend responsibility split: Tasks 1-7.
- Owner-scoped schema, migration, saved context, immutable completion result:
  Tasks 2 and 3.
- Exact request/response/error contracts, OpenAPI, and CORS: Tasks 4 and 5.
- Transaction boundaries, row locking, atomic completion, and rollback: Task 3.
- Authentication, ownership-hidden `404`, and user-cache isolation: Tasks 2,
  4, 5, and 7.
- Dedicated screens, pessimistic submission, recovery, accessibility, and todo
  refresh after completion: Tasks 6 and 7.
- Both branches, cancellation, invalid action/input, ownership, saved progress,
  terminal behavior, rollback, and real PostgreSQL coverage: Tasks 1-7.
- Invalid-action learning experiment: Tasks 3, 4, and 8.
- Uncertain submission without automatic mutation retry or Phase 9 promises:
  Tasks 5, 6, and 8.
- Guide written only after verified implementation, deferred Phase 8/9 work,
  regression gates, review, acceptance, and checkpoint convention: Task 8.

The plan intentionally omits `OFFER_BREAKDOWN`, presentation templates,
navigation, discovery, revisions, idempotency, workflow versions, workers,
external effects, AI suggestions, parent/child todos, and full cross-platform
E2E automation.
