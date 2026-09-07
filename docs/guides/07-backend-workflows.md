# Phase 7: Backend workflow modeling

## 1. CRUD versus backend-owned workflow

Quick-add creates a todo the moment you submit it. Guided planning works the
other way around: you open a **Help me plan a task** flow, answer questions,
review proposed todos, and only then does anything get created. Until you
confirm, the workflow is a saved draft — zero todos exist for it. The
fundamental rule of this phase is:

> The backend decides which business action is valid and what happens next.
> The frontend renders a supported screen and submits the user's next action.
> A client request never gets to choose the next workflow state.

Concretely, the client submits `{action: "confirm"}` — never
`{next_state: "COMPLETED"}`. The server validates the action against the
workflow's current state, applies the transition, and returns the resulting
view. An invalid action changes nothing.

## 2. State, action, context, and transition responsibilities

| Responsibility | Owner |
| --- | --- |
| Current business state, accepted answers, owner, terminal status | Backend domain logic (`workflow_domain.py`) plus PostgreSQL |
| Coordinating transition rules with repository writes | Service layer (`workflow_service.py`) |
| Owner-scoped SQL reads/writes, row locking | Repository layer (`workflow_repository.py`, `todo_repository.py`) |
| HTTP shapes, auth, validation, status codes | Thin FastAPI routes (`main.py`) |
| Latest authoritative workflow snapshot | TanStack Query (`['todo-workflow', userId, workflowId]`) |
| Drafts, focus, pending indicators, error copy | React component state |
| Rendering the six screens, collecting input, accessibility | Expo/React Native client |

The domain module is pure Python: frozen dataclasses in, a
`TransitionDecision` out, no database, no HTTP. The service owns
transactions. Routes authenticate, validate, call the service, and map
domain exceptions to HTTP statuses. Nothing in the domain knows about
React, and nothing in React knows the transition table.

## 3. The `todo_workflows` persistence shape and owner boundary

Migration `2026090702_add_todo_workflows` creates one table:

| Column | Rules |
| --- | --- |
| `id` | Internal `BIGINT IDENTITY` primary key |
| `public_id` | Unique UUID; the only identity the API exposes |
| `owner_id` | Non-null FK to `users(id)`, cascade delete |
| `state` | One of the five states, enforced by a named check |
| `title` | The original task title, 1–120 code points |
| `involves_multiple_steps` | Nullable Boolean answer (null until answered) |
| `proposed_todo_titles` | Non-null JSONB array of canonical titles, in order |
| `completion_result` | Nullable JSONB; must be an object when present |

Every read and write is owner-scoped in SQL (`public_id` **and**
`owner_id`), and confirmation locks its row with `SELECT ... FOR UPDATE`.
Another owner's workflow UUID behaves exactly like an absent one: `404
{"detail":"Todo workflow not found."}`. There is no discovery endpoint in
this phase — you resume what you started, and each launch starts fresh.

## 4. Service transactions and completion rollback

`start_workflow` and `advance_workflow` each own one `with session.begin()`
block; `get_workflow` is a read with no writes (fetching never advances
anything). Confirmation inserts each proposed todo, stores the exact created
UUID/title/completed snapshot as the immutable completion result, marks the
workflow `COMPLETED`, and commits all of it together. If any insert fails,
the todos, the state change, and the result roll back as one unit — the
workflow stays in `REVIEW` with a SQL-null result and zero new todos. The
completed snapshot is stored data, not a re-read: displaying a finished
workflow can never repeat its writes.

## 5. Exact API commands and current-state responses

All routes require the Phase 6 Bearer credential. Unauthenticated calls get
exact `401`; malformed UUIDs get `422`; database outages get exact `503`.

```text
POST /todo-workflows                         -> 201 + snapshot
GET  /todo-workflows/{workflow_id}           -> 200 + snapshot (no side effects)
POST /todo-workflows/{workflow_id}/actions   -> 200 + snapshot
```

A snapshot always exposes exactly `workflow_id`, `state`, `title`,
`context {involves_multiple_steps, proposed_todo_titles}`, and `result`
(null unless completed, then `{created_todos}` in the ordinary Todo
shape). Actions use a discriminated union on `action`:

| Action body | Meaning |
| --- | --- |
| `{"action":"answer_multiple_steps","answer":true/false}` | Branch from `ASSESS_TASK` |
| `{"action":"submit_tasks","titles":[...]}` | 2–10 canonical titles from `COLLECT_TASKS` |
| `{"action":"confirm"}` | Create proposed todos from `REVIEW` |
| `{"action":"cancel"}` | End from any active state, creating nothing |

A well-formed action in the wrong state returns exact `409
{"detail":"Action is not valid for the current workflow state."}`. Any
action against `COMPLETED`/`CANCELLED` returns exact `409
{"detail":"Todo workflow is already terminal."}`. Malformed bodies
(unknown action, missing/extra fields, non-strict types, 1 or 11 titles)
return `422` through the standard validation handler.

## 6. Frontend cache versus local interaction state

The TanStack snapshot is the only remote truth the workflow screens read.
Start seeds `['todo-workflow', userId, workflowId]` with the exact `201`
response; every successful action replaces it with the exact response.
Completion additionally invalidates `['todos']` so the list refetches the
newly created rows.

Everything else is local: the start/breakdown drafts, the known workflow
ID, focus signals, and error copy. Submissions are pessimistic — the old
screen stays visible with disabled controls and **Submitting…** until the
authoritative response arrives. A failed action with `unavailable` or
`invalid-data` marks the workflow query stale, keeps the prior screen and
draft, disables actions, and shows **Reload plan**; only a valid `GET`
replaces the snapshot and unlocks. A `409` reconciles the same way with the
plan-changed copy. Validation (`422`) keeps the draft, leaves the cache
fresh, and never locks. Remounting the app intentionally forgets the
locally held workflow ID in this phase.

## 7. The simple birthday-party walkthrough

1. From the todo list, press **Help me plan a task**.
2. Enter `Plan birthday party` and press **Start planning**. No todo is
   created; the screen asks **Does this task involve multiple steps?**
3. Press **No**. The backend stores the answer and returns `REVIEW` with
   the original title as the single proposal.
4. Press **Confirm plan**. One ordinary todo appears, the screen shows
   **Plan complete** with the persisted result, and **Back to todos**
   returns to a refreshed list.

## 8. The breakdown birthday-party walkthrough

1. Start `Plan birthday party` as above.
2. Press **Yes**. The backend stores `involves_multiple_steps: true` and
   returns `COLLECT_TASKS`.
3. Enter one title per line — for example `Send invitations`,
   `Buy decorations`, `Book venue` — and press **Save tasks**. Blank lines
   are ignored, each line is canonicalized with the shared title rule,
   duplicates and order are preserved, and fewer than 2 or more than 10
   lines are rejected locally without a request.
4. Review shows the exact backend list in numbered order. **Confirm plan**
   creates exactly those todos; **Back to todos** shows them after the
   invalidated list refetches.

## 9. The invalid-action experiment

Submit `confirm` while a workflow is still in `ASSESS_TASK`:

```bash
TOKEN=<signed-in Bearer token>
WID=<workflow UUID from POST /todo-workflows>
curl -X POST http://127.0.0.1:8000/todo-workflows/$WID/actions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"confirm"}'
# -> 409 {"detail":"Action is not valid for the current workflow state."}
```

Then `GET` the workflow and `GET /todos`: the state, proposals, result,
and todo count are byte-for-byte unchanged. The backend rejected the
command without advancing anything — try the same with `submit_tasks` in
`REVIEW` or `answer_multiple_steps` in `COLLECT_TASKS` for the full table.

## 10. Uncertain submission recovery and the lost-start limitation

If an action fails with a transport or data error, the screen keeps the
prior snapshot and draft under an uncertainty lock with **Reload plan**.
Reload performs one safe `GET`: a valid response replaces the snapshot and
unlocks; a failed or malformed one keeps the lock. Mutations are never
retried automatically — a second attempt could double-apply — so recovery
is always an explicit reload.

Limitation to know: if the *start* request itself is lost, there is no
workflow ID to reload, so the screen says **Starting may not have finished.
Start again to retry** and warns that retrying may create another draft.
Recovery identifiers arrive in Phase 9.

## 11. Focused commands that were actually verified

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest \
  tests/test_workflow_domain.py tests/test_workflow_persistence.py \
  tests/test_workflows.py tests/test_validation.py -v
pnpm --dir apps/mobile test --runInBand \
  src/todoWorkflows/TodoWorkflowScreen.test.tsx \
  src/TodoExperience.test.tsx src/todos/todoApi.test.ts \
  src/auth/authenticatedApi.test.ts
pnpm quality
```

Table-driven domain tests run database-free; persistence, transaction,
rollback, and API tests run against the real guarded `todo_test`
database; transport and component tests use injected fakes with a fresh
`QueryClient` per case.

## 12. Work deferred to Phase 8 and Phase 9

Phase 8 inserts the second yes/no question (`OFFER_BREAKDOWN`), a separate
state-to-view presentation mapper, and the reusable template registry —
two consecutive questions will share one template with different content
and step identities. Phase 9 adds discovery of unfinished workflows,
atomic revisions, submission idempotency, definition versions, and the
cross-device reliability matrix. None of those concepts exist in this
phase: there is no `OFFER_BREAKDOWN` state, no template registry, no
`step_id`/`expected_revision`/`submission_id` fields, no discovery
endpoint, and no automatic resubmission.

## 13. Phase 7 acceptance record

| Target | Date/runtime | Simple path | Breakdown path | Cancel/terminal | Invalid action | Restart/outage |
| --- | --- | --- | --- | --- | --- | --- |
| Web | — | ☐ | ☐ | ☐ | ☐ | ☐ |
| iOS Simulator | — | ☐ | ☐ | ☐ | ☐ | ☐ |
