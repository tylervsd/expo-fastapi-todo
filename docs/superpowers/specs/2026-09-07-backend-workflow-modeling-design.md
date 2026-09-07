# Phase 7 Backend Workflow Modeling Design

**Status:** Written for review; implementation plan pending approval (2026-09-07)

## Outcome

Phase 7 teaches the transition from CRUD to a persisted, backend-owned business
workflow. A signed-in user keeps the existing quick-add todo experience and can
also select **Help me plan a task**. The guided path records the current state,
accepted answers, and proposed todo titles in PostgreSQL. Todos are created only
after review and confirmation.

For the teaching example, `Plan birthday party` can become either one ordinary
todo or the accepted smaller todos. The title is demonstration data, not
special-case business logic. The user supplies every breakdown title; this
phase does not generate suggestions.

The phase teaches explicit workflow state, user actions, collected context,
transition rules, service-owned transactions, atomic completion, and a frontend
that presents authoritative backend state without owning business branching.

## Scope

Phase 7 includes:

- explicit Python states, commands, context, and transition decisions;
- a database-free domain boundary and a concrete transactional service;
- owner-scoped workflow persistence in the existing PostgreSQL database;
- authenticated start, fetch, advance, and cancel operations;
- saved progress across requests and API process restarts;
- dedicated React Native components selected from the returned workflow state;
- pessimistic workflow mutations with explicit uncertain-result recovery;
- atomic todo creation and completion-result persistence;
- validation, authorization, accessibility, and targeted automated tests.

The existing `/todos` contract and quick-add experience remain unchanged.

Phase 7 does not add `OFFER_BREAKDOWN`, a second yes/no question, server-directed
templates, a template registry, arbitrary JSON layouts, a navigation library,
active-workflow discovery, cross-device resume, revisions, step identifiers,
idempotency keys, workflow-definition versions, background workers, queues,
external side effects, LLM integration, parent/child todos, or full web/iOS E2E
automation.

## Chosen approach

Use a small explicit state machine, a concrete workflow service, one workflow
table, and dedicated frontend components. There is no workflow framework,
generic repository interface, presentation registry, or future-version
scaffolding.

Normalized proposed-task child rows would add joins and lifecycle rules without
improving this bounded lesson. Ordered JSONB arrays are sufficient for draft
titles and a stable completion snapshot. Branching directly in FastAPI handlers
would use fewer modules but defeat the learning objective by coupling business
decisions to HTTP and transactions.

## User journeys

### Simple path

1. The signed-in user selects **Help me plan a task** and enters
   `Plan birthday party`.
2. The backend creates an owner-scoped workflow in `ASSESS_TASK`. No todo exists.
3. The frontend asks **Does this task involve multiple steps?**
4. The user answers **No**.
5. The backend enters `REVIEW` with `Plan birthday party` as the one proposed
   todo.
6. The user confirms.
7. In one transaction, the backend creates one ordinary todo, stores the
   completion result, and enters `COMPLETED`.
8. Returning to the todo list performs its existing authoritative refresh and
   displays the created todo.

### Breakdown path

1. The user starts the same title and answers **Yes**.
2. The backend records the answer and enters `COLLECT_TASKS`.
3. The user enters two to ten proposed titles, one per line, such as:
   - `Send invitations`
   - `Order birthday cake`
   - `Buy decorations`
4. The backend validates, canonicalizes, and saves the ordered titles, then
   enters `REVIEW`.
5. The review screen displays exactly those backend-returned titles.
6. Confirming atomically creates those ordinary todos and enters `COMPLETED`.
   Cancelling enters `CANCELLED` without creating any todo.

Duplicate titles remain valid and preserve their order, matching the existing
todo contract.

### Cancellation

`cancel` is accepted in `ASSESS_TASK`, `COLLECT_TASKS`, and `REVIEW`. It enters
`CANCELLED` without creating todos. Completed and cancelled workflows remain
fetchable but accept no further actions.

## Workflow model

States are a Python `StrEnum`:

- `ASSESS_TASK`
- `COLLECT_TASKS`
- `REVIEW`
- `COMPLETED`
- `CANCELLED`

Commands are explicit domain values:

- `AnswerMultipleSteps(answer: bool)`
- `SubmitTasks(titles: tuple[str, ...])`
- `Confirm`
- `Cancel`

Clients submit commands and input only. They never submit `state`, `next_state`,
completion results, or todo identifiers.

The database-free domain operation is conceptually:

```python
transition(
    snapshot: WorkflowSnapshot,
    command: WorkflowCommand,
) -> TransitionDecision
```

A decision contains the next state, accepted context, and, only for
confirmation, the titles that must become todos. It does not perform I/O or
know about FastAPI, SQLAlchemy, HTTP statuses, React components, or routes.

## Transition table

| Current state | Submitted action | Result |
| --- | --- | --- |
| Start | Valid `title` | Insert workflow in `ASSESS_TASK`; create no todos |
| Start | Invalid title or body | `422`; create no workflow or todos |
| `ASSESS_TASK` | `answer_multiple_steps`, `true` | Save answer; enter `COLLECT_TASKS` |
| `ASSESS_TASK` | `answer_multiple_steps`, `false` | Save answer and original title; enter `REVIEW` |
| `COLLECT_TASKS` | `submit_tasks` with 2-10 valid titles | Save canonical ordered titles; enter `REVIEW` |
| `COLLECT_TASKS` | Invalid count, title, or body | `422`; change nothing |
| `REVIEW` | `confirm` | Create proposed todos, store result, and enter `COMPLETED` atomically |
| Any nonterminal state | `cancel` | Enter `CANCELLED`; create no todos |
| Any nonterminal state | Well-formed action valid only elsewhere | `409`; change nothing |
| `COMPLETED` or `CANCELLED` | Any well-formed action | `409`; change nothing |
| Any state | Malformed or unknown action payload | `422`; change nothing |
| Any persisted state | `GET` | Return the same snapshot without advancing or writing |
| Missing or other-owned ID | Fetch or well-formed action | `404`; disclose nothing |
| Any operation | Unauthenticated request | Existing exact `401` contract |
| Any database operation | Database unavailable | Existing exact `503` contract |

Request parsing and structural validation occur before transition evaluation.
A malformed action therefore receives `422` even when the target ID is absent
or terminal. A well-formed action reaches owner lookup and state validation.

## Validation

Workflow and proposed todo titles reuse the existing canonical title rule:

- the value is a strict JSON string;
- ECMAScript leading and trailing whitespace is removed;
- the canonical value contains 1-120 Unicode code points;
- NUL and unpaired surrogates are rejected.

The existing canonicalizer moves from `main.py` into a small shared validation
module rather than being copied. Existing `TodoCreate` and `TodoUpdate` continue
to use it without changing their contract.

A breakdown contains two to ten titles. Each title is validated independently.
Order and duplicates are preserved. Extra request properties, missing required
properties, unknown action discriminators, and coercible values such as `1`
for a Boolean are rejected. The multiline frontend is an input convenience;
the API receives an explicit JSON array.

## Responsibilities and boundaries

### Domain

The domain module owns states, commands, context, and pure transition decisions.
It rejects commands that are invalid for the current state without modifying
its input snapshot.

### Service

A concrete service exposes these use cases:

```python
start_workflow(session, owner_id, title) -> WorkflowSnapshot
get_workflow(session, owner_id, workflow_id) -> WorkflowSnapshot | None
advance_workflow(
    session,
    owner_id,
    workflow_id,
    command,
) -> WorkflowSnapshot | None
```

The service owns transactions, invokes domain transitions, coordinates the
workflow repository with the existing todo repository, and returns domain
snapshots. There is no protocol or interface with one implementation.

### Persistence

A concrete workflow repository owns its SQLAlchemy mapping and SQL operations:

- insert an owner-scoped workflow;
- fetch it by `(public_id, owner_id)`;
- lock it by `(public_id, owner_id)` for an action;
- persist accepted state, context, and completion result.

Action processing uses `SELECT ... FOR UPDATE` to serialize operations on one
workflow row. This is basic transactional integrity, not Phase 9's revision,
stale-step, retry, or idempotency contract.

### HTTP

FastAPI handlers authenticate with the existing dependency, parse strict
Pydantic request unions, translate them into domain commands, call the service,
and map domain snapshots into response models. They do not choose next states
or create todos directly.

### Frontend

The frontend renders one dedicated component for the returned state, collects
local drafts and actions, submits actions pessimistically, and replaces its
cached snapshot only with an authoritative response. It never computes the next
business state.

## Database schema and migration

Alembic revision `2026090702_add_todo_workflows.py` adds one table:

| Column | PostgreSQL type | Rules | Purpose |
| --- | --- | --- | --- |
| `id` | `BIGINT IDENTITY` | Primary key | Internal row identity |
| `public_id` | `UUID` | Unique, not null | Public workflow identifier |
| `owner_id` | `BIGINT` | FK `users(id)` with cascade delete, not null | Authorization boundary |
| `state` | `TEXT` | Not null; checked against the five Phase 7 states | Current business state |
| `title` | `TEXT` | Not null; length 1-120 check | Original canonical title |
| `involves_multiple_steps` | `BOOLEAN` | Nullable | Accepted assessment answer |
| `proposed_todo_titles` | `JSONB` | Not null, default `[]`; JSON array check | Ordered accepted draft titles |
| `completion_result` | `JSONB` | Nullable; JSON object check when present | Immutable terminal result |

No timestamps, owner listing index, active-workflow index, revision, version,
step ID, or submission table is added. State-dependent invariants remain in the
domain and service rather than becoming one complex database constraint.

`completion_result` stores the exact todos created at confirmation:

```json
{
  "created_todos": [
    {
      "id": "5f699d61-9449-407e-aa37-89e759b78df0",
      "title": "Send invitations",
      "completed": false
    }
  ]
}
```

This is an immutable completion snapshot. Later renaming or deleting a created
todo does not rewrite workflow history. Active and cancelled workflows keep
`completion_result` null.

Python generates workflow and todo public IDs with `uuid4()`, following the
existing convention. The migration has explicit upgrade and downgrade steps;
application startup still never calls `create_all`.

## HTTP contract

### Start

```http
POST /todo-workflows
Authorization: Bearer <token>
Content-Type: application/json

{"title":"Plan birthday party"}
```

Success is `201 Created`:

```json
{
  "workflow_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3",
  "state": "ASSESS_TASK",
  "title": "Plan birthday party",
  "context": {
    "involves_multiple_steps": null,
    "proposed_todo_titles": []
  },
  "result": null
}
```

### Fetch without advancing

```http
GET /todo-workflows/a5693d6a-159d-4ae2-b9d3-e4184e6b82b3
Authorization: Bearer <token>
```

Success is `200 OK` with the same response shape. It performs no business
write. `GET /todo-workflows?status=active` is intentionally absent because
active discovery belongs to Phase 9.

### Answer the assessment

All actions use:

```http
POST /todo-workflows/{workflow_id}/actions
Authorization: Bearer <token>
Content-Type: application/json
```

The Yes request is:

```json
{"action":"answer_multiple_steps","answer":true}
```

It returns `200 OK`:

```json
{
  "workflow_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3",
  "state": "COLLECT_TASKS",
  "title": "Plan birthday party",
  "context": {
    "involves_multiple_steps": true,
    "proposed_todo_titles": []
  },
  "result": null
}
```

The No request uses `"answer": false` and returns `REVIEW` with:

```json
{
  "involves_multiple_steps": false,
  "proposed_todo_titles": ["Plan birthday party"]
}
```

### Submit a breakdown

```json
{
  "action": "submit_tasks",
  "titles": [
    "Send invitations",
    "Order birthday cake",
    "Buy decorations"
  ]
}
```

Success is `200 OK` in `REVIEW`, with the same canonical titles in the same
order under `context.proposed_todo_titles`.

### Confirm

```json
{"action":"confirm"}
```

Success is `200 OK` in `COMPLETED`. The response retains the reviewed context
and returns the persisted `result.created_todos` snapshot.

### Cancel

```json
{"action":"cancel"}
```

Success is `200 OK` in `CANCELLED` with `result: null` and no new todos.

### Error contract

| Status | Stable contract |
| --- | --- |
| `401` | `{"detail":"Not authenticated."}` |
| `404` | `{"detail":"Todo workflow not found."}` |
| `409`, wrong state | `{"detail":"Action is not valid for the current workflow state."}` |
| `409`, terminal | `{"detail":"Todo workflow is already terminal."}` |
| `422` | Standard FastAPI validation detail; clients depend on category, not prose |
| `503` | `{"detail":"Database unavailable."}` |

The TypeScript transport adds a `conflict` error category for `409` and
continues to suppress server bodies and exception text from user-visible copy.
OpenAPI publishes the discriminated action request and workflow response
schemas. CORS needs no new method or header because all operations use existing
GET/POST and Authorization support, but tests cover workflow preflights.

## Transactions and rollback

Each state-changing service operation owns one `session.begin()` block.

Confirmation performs the following work in one transaction:

1. Lock the owner-scoped workflow row.
2. Validate `confirm` against `REVIEW` through the domain transition.
3. Insert every proposed todo through the existing todo repository.
4. Build and store the completion result.
5. Update the workflow to `COMPLETED`.
6. Commit before returning success.

Any todo insertion, result construction, workflow update, or commit failure
rolls back all created todos and leaves the workflow in `REVIEW` with a null
completion result. Cancellation and accepted intermediate actions each update
their workflow in one transaction. Domain rejection occurs before persistence
changes.

## Authentication, ownership, and cache isolation

Every workflow endpoint requires the current Phase 6 Bearer session. Every
workflow repository lookup includes both public workflow ID and internal owner
ID. Another user's valid workflow ID returns the same `404` as an absent one.

PostgreSQL cascades workflows when an owner is deleted; no user-deletion
endpoint is added.

TanStack Query keys workflow snapshots by user and workflow:

```typescript
["todo-workflow", userPublicId, workflowId]
```

Existing query-cache clearing on authentication transitions remains mandatory.
The user ID in the key prevents a late response from being consumed by another
signed-in user. A late response may target only its former user's key and must
not change the current shell.

## Frontend state and components

The signed-in experience gains a small local shell mode rather than a navigation
dependency:

- the existing todo list and quick-add form;
- guided-workflow start;
- current workflow.

Dedicated components are selected with an exhaustive switch over the backend
state:

- `WorkflowStartScreen`
- `AssessTaskScreen`
- `CollectTasksScreen`
- `ReviewWorkflowScreen`
- `CompletedWorkflowScreen`
- `CancelledWorkflowScreen`

`CollectTasksScreen` uses one labelled multiline input with one todo title per
line. `ReviewWorkflowScreen` renders the exact backend-returned ordered list.
Every active workflow screen exposes **Cancel planning**. An active workflow is
not silently discarded through a Back control; the user cancels to leave it.

### State ownership

| State or responsibility | Owner |
| --- | --- |
| Current state, original title, accepted answer, proposed titles, owner, terminal result | PostgreSQL and backend domain/service |
| Latest received workflow snapshot | TanStack Query |
| Todo collection | Existing `['todos']` TanStack Query cache |
| Start and breakdown drafts | Local React state |
| Shell mode and current known workflow ID | Local React state |
| Focus signals and visible field errors | Local React state |
| Business branching and next state | Backend only |

Workflow mutations remain pessimistic. The current authoritative screen stays
visible while inputs and actions are disabled and **Submitting...** is shown.
On success, the returned snapshot replaces the cached snapshot. The client does
not optimistically render or predict the next state.

After a `COMPLETED` response, the frontend invalidates `['todos']`. Returning to
the todo screen invokes its existing authoritative refetch, making the created
todos visible without maintaining another todo collection.

## Submission and recovery behavior

Safe GET requests retain the current single-retry policy. Workflow mutations
never retry automatically.

When an action for a known workflow receives an unavailable or invalid response:

- keep the previous screen and its draft;
- mark the workflow query stale;
- disable further workflow actions;
- show **The result may be unknown. Reload this plan before trying again.**;
- expose **Reload plan**, which performs a safe GET.

If the GET shows that the action was accepted, the frontend renders that state
and does not resubmit. If it shows the previous state, the user may submit again
manually. Phase 7 does not promise safety against an extremely late first
request or a competing device.

A lost start response is intentionally not recoverable through the UI because
the client has no workflow ID and active discovery is deferred. The UI explains
that the result may be unknown and that manually trying again may create another
draft. It never retries automatically.

A `409` invalid-state response triggers safe GET reconciliation and an
explanation that the plan changed. It never causes a guessed transition.

## Accessibility

All new screens preserve the existing safe-area, scrolling, keyboard-inset,
explicit-role, and 44-point-target conventions.

- Every screen has a header role.
- Inputs have visible labels and accessible names.
- Validation and request failures use alert semantics.
- An authoritative state change announces the new step.
- After a state change, focus moves to the first relevant control: title input,
  first assessment action, breakdown input, confirm action, or terminal return
  action.
- Yes, No, Confirm, Cancel, Reload, and return controls expose button roles and
  disabled state.
- Review items use accessible ordered-list semantics where supported and
  readable numbered fallback text elsewhere.
- Submission state is conveyed through text and disabled semantics, never color
  alone.

Component tests cover semantics and focus behavior. Manual web and iOS
acceptance verifies actual announcement and keyboard behavior.

## Deterministic testing

| Layer | Required coverage |
| --- | --- |
| Domain unit | Both assessment branches, collection, confirmation, cancellation from every active state, every wrong-state action, all terminal actions, and unchanged input on rejection |
| Validation unit | Strict discriminator and Boolean, missing/extra/unknown fields, title rules, 1/2/10/11 title boundaries, invalid individual titles, and duplicate preservation |
| PostgreSQL repository | Migration shape and constraints, owner-scoped insert/fetch/lock, saved progress across sessions, ordered JSONB context, and stable completion result |
| PostgreSQL service | Both paths, cancellation from each active state, no pre-confirmation todos, atomic completion, and forced mid-completion rollback of todos, state, and result |
| API integration | Exact requests/responses/statuses, authentication, cross-owner `404`, side-effect-free GET, fresh-session progress, terminal behavior, `503`, OpenAPI, and CORS |
| Learning experiment | Submit `confirm` in `ASSESS_TASK`; assert `409`, unchanged workflow row, and unchanged todo count |
| TypeScript transport | Paths, methods, Bearer header, strict runtime response validation, `409` mapping, cancellation, timeout, and safe errors |
| Component | Quick-add regression, both branches, exact review, cancellation, pending locks, validation recovery, uncertain-action reload, terminal rendering, todo invalidation, focus, and accessibility |
| Full regression | Existing auth, CRUD, API, database, mobile, lint, typecheck, and web-export checks |

Transaction assertions use real PostgreSQL. Domain transition tests remain
database-free and table-driven. The completion rollback test forces failure
after at least one todo insert inside the real PostgreSQL transaction, then
verifies that no todo, state change, or completion result committed.

## Acceptance criteria

Phase 7 is acceptable when:

1. Quick-add and existing `/todos` contracts remain unchanged.
2. Both guided branches work for arbitrary valid titles.
3. No todo exists before confirmation.
4. State and accepted context survive separate requests and API process
   restarts.
5. Clients never submit or predict a next state.
6. Fetching and redisplaying a workflow never advance it.
7. Wrong-state actions and validation failures change neither workflows nor
   todos.
8. Cancellation works from every active state and creates no todos.
9. Completed and cancelled workflows reject every further action.
10. Confirmation atomically creates the reviewed todos and stores the exact
    completion result.
11. A forced completion failure rolls back every effect in PostgreSQL.
12. Authentication, owner-scoped `404`, and user-isolated caching hold.
13. Dedicated accessible components cover every Phase 7 state.
14. Completion invalidates the todo list and returning to it displays the new
    rows after an authoritative fetch.
15. Targeted suites and the full quality gate pass during implementation.
16. Guide 07 is written only after the feature is implemented and verified.
17. No Phase 8/9 feature, completion claim, checkpoint tag, push, or PR is
    produced during planning.

## Documentation and checkpoint

The standalone implementation plan is created only after this written
specification is approved. It must distinguish commands already run from future
commands and cannot claim that unimplemented tests pass.

After implementation and verification, create
`docs/guides/07-backend-workflows.md`. The guide explains both birthday-party
paths, the state/action/context/transition split, persistence and transactions,
the invalid-action experiment, frontend state ownership, uncertain-result
limitations, and work deferred to Phases 8 and 9.

README and roadmap implementation status change only after verified feature
acceptance. Phase 7 completes only after focused and full checks, supported web
and iOS manual acceptance, whole-branch review, integration, and passing CI on
the exact integrated commit. Only then may an annotated
`phase-07-backend-workflows` tag be created.

## Future extension boundary and limitations

Phase 8 can add a separate state-to-view mapper, reusable templates, contract
versioning, and `OFFER_BREAKDOWN` without changing the domain/service/repository
responsibility split. Phase 7 clients branch directly on the returned business
state; Phase 8 replaces that presentation boundary deliberately.

Phase 9 can add revisions, step and submission identifiers, idempotency records,
active-workflow discovery, workflow-definition versions, and reliable
cross-device recovery. Phase 7 adds no placeholder columns or abstractions for
them.

Consequently, Phase 7 cannot discover an unfinished workflow after losing its
ID, guarantee duplicate-free start retries after a lost response, detect stale
intent from another device, or promise reliable multi-device resumption. These
limitations are documented rather than hidden behind automatic retries.
