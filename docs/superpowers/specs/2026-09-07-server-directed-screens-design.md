# Phase 8 Server-Directed Screens Design

**Status:** Proposed (2026-09-07)

## Outcome

Phase 8 teaches the separation between backend-owned business workflows and a
small, typed presentation contract. The guided-todo workflow gains a second
question — after “Does this task involve multiple steps?”, a Yes answer now
leads to **“Would you like to split it into smaller todos?”** instead of
jumping straight to title collection. Both questions render through one shared
yes/no native component with different content, and the backend alone decides
which question appears when.

The phase teaches an explicit presentation boundary: domain logic determines
valid actions and the next business state; a backend presentation mapper
converts the current workflow into a supported view description; the API
returns that description; the frontend selects a known native component using
the view's type and submits that template's fixed command with user input. The
frontend never branches on business state, and the domain never names
components, routes, or layouts.

For the teaching example, `Plan birthday party` now has three paths: No at
the first question reviews the single original todo; Yes then No reviews the
single original todo; Yes then Yes collects smaller todos for review. Titles
remain demonstration data, never special-case logic, and the user supplies
every breakdown title.

## Scope

Phase 8 includes:

- the `OFFER_BREAKDOWN` state and its transition rows, reusing the existing
  `AnswerMultipleSteps` command;
- a database-free backend presentation mapper from domain snapshots to typed
  view descriptions;
- an additive `view` object on the existing workflow response envelope;
- stable per-step identity carried inside the view;
- a small frontend template registry (`yes_no`, `task_breakdown`, `review`,
  `completion`) with one shared yes/no component;
- draft and error reset keyed by step identity;
- an explicit unknown-template fallback screen;
- validation, authorization, accessibility, and targeted automated tests.

The existing quick-add experience, the separate **Help me plan a task** entry
point, cancellation from every nonterminal state, terminal-state rules,
pessimistic mutations, uncertain-result recovery, and the `/todos` contract
all remain unchanged.

Phase 8 does not add idempotency keys, revision-based concurrency control,
active-workflow discovery, cross-device resume, workflow-definition or
full API-version negotiation, background workers, queues, external side
effects, LLMs, a generic workflow designer, arbitrary server-defined
layouts, a new navigation framework, a new state-management library, or
full web/iOS E2E automation. Reliable retries, concurrency, and advanced
resumption remain Phase 9. There is no `view_contract_version` field: partial
version negotiation would promise compatibility the phase does not deliver,
and an unknown template `type` already carries the fallback signal.

## Chosen approach

Extend the existing layers rather than replacing them: two transition rows in
the domain, one widened database check, one pure presentation module, one
additive response field, four template components reusing Phase 7 copy, style,
and accessibility conventions, and a registry that switches on view type
instead of business state.

A generically extensible template engine (server-sent component trees,
layout DSLs, downloaded code) would teach framework configuration instead of
the intended lesson and would violate the constraint that only supported
native components may render. Storing step identities in a new column would
add migration surface, rotation logic, and tests for zero Phase 8 benefit
while the state graph is acyclic. Replacing the response envelope instead of
extending it would break every existing contract test and component for no
behavioral gain.

## User journeys

### Simple path (unchanged behavior, new rendering contract)

1. The signed-in user selects **Help me plan a task** and enters
   `Plan birthday party`.
2. The backend creates an owner-scoped workflow in `ASSESS_TASK`. No todo
   exists. The response carries a `yes_no` view for the multiple-steps
   question.
3. The user answers **No**.
4. The backend enters `REVIEW` with `Plan birthday party` as the one proposed
   todo and returns a `review` view.
5. The user confirms; one ordinary todo is created atomically with the
   `completion` view; returning to the list shows it after the existing
   authoritative refresh.

### Declined-breakdown path (new)

1. The user starts the same title and answers **Yes** to the multiple-steps
   question.
2. The backend enters `OFFER_BREAKDOWN` and returns a second `yes_no` view
   asking **Would you like to split it into smaller todos?** The same native
   component renders with different content and a different step identity.
3. The user answers **No**. The backend enters `REVIEW` with the original
   title only.
4. Confirming creates exactly one ordinary todo titled `Plan birthday party`.

### Accepted-breakdown path (extended)

1. The user answers **Yes** to both questions.
2. `COLLECT_TASKS` returns a `task_breakdown` view carrying the entry limits.
3. The user enters two to ten titles, such as `Send invitations`,
   `Order birthday cake`, `Buy decorations`.
4. `REVIEW` displays exactly those backend-returned titles; confirming
   atomically creates those ordinary todos. No parent/child hierarchy is
   introduced.

### Cancellation

`cancel` remains accepted in every nonterminal state, now including
`OFFER_BREAKDOWN`. It enters `CANCELLED` without creating todos. Completed
and cancelled workflows render through the shared `completion` template
with an outcome marker and remain fetchable but actionless.

## Workflow model

One state is added to the Python `StrEnum`:

- `OFFER_BREAKDOWN`

No new command type is added. `AnswerMultipleSteps(answer: bool)` is reused:
the current state disambiguates its meaning, so the action union, request
schemas for actions, and all client submission code stay stable. New commands
for yes/no answers would duplicate a distinction the state already carries.
The persisted `involves_multiple_steps` value continues to mean only the
answer to the first question. In `OFFER_BREAKDOWN`, the Boolean selects the
next transition but is not persisted as a second fact; the resulting state and
proposed titles already encode the choice, so another column is unnecessary.

## Transition table

Only these rows change; every Phase 7 row not listed here is unchanged.

| Current state | Submitted action | Result |
| --- | --- | --- |
| `ASSESS_TASK` | `answer_multiple_steps`, `true` | Save `involves_multiple_steps=true`; enter `OFFER_BREAKDOWN` (changed from `COLLECT_TASKS`) |
| `OFFER_BREAKDOWN` | `answer_multiple_steps`, `true` | Preserve `involves_multiple_steps=true`; enter `COLLECT_TASKS` |
| `OFFER_BREAKDOWN` | `answer_multiple_steps`, `false` | Preserve `involves_multiple_steps=true`, save the original title, and enter `REVIEW` |

`OFFER_BREAKDOWN` accepts `cancel` like every other nonterminal state.
`submit_tasks`, `confirm`, and any other well-formed action there return the
existing exact wrong-state `409`. The terminal, malformed-payload (`422`),
missing/other-owned (`404`), unauthenticated (`401`), and unavailable
(`503`) rows are unchanged, as is the rule that structural validation
precedes transition evaluation.

## Validation

Title rules, the 2–10 breakdown count, strict discriminators and Booleans,
and unknown-field rejection are unchanged. The multiline frontend remains an
input convenience sending an explicit JSON array.

Context invariants widen for the new declined-breakdown path. `REVIEW` and
`COMPLETED` accept the original title with either
`involves_multiple_steps=false` (the first question was declined) or
`involves_multiple_steps=true` (breakdown was declined), while two to ten
proposed titles still require `involves_multiple_steps=true`. Domain and API
tests pin these semantic combinations; the TypeScript transport validates the
envelope structurally and uses only the view to select a component.

The `task_breakdown` view carries `min_titles: 2` and `max_titles: 10` so the
limits live in exactly one place — the backend that enforces them — instead
of being duplicated as a client constant. The client still validates locally
for fast feedback and formats its count error using the supplied bounds,
keeping the backend authoritative on disagreement.

## Responsibilities and boundaries

### Domain

Unchanged duties plus the two `OFFER_BREAKDOWN` rows. The domain still knows
nothing of views, templates, components, or routes.

### Presentation mapper

A new database-free module (proposed: `apps/api/app/workflow_presentation.py`)
owns one pure function:

```python
present_workflow(snapshot: WorkflowSnapshot) -> WorkflowView
```

It converts an authoritative domain snapshot into a supported view
description. It performs no I/O, owns no transactions, and references no
React component names, navigation routes, or layout details — only template
types, content strings, limits, and, for choice templates, choice identifiers
with display labels.

### Service

Unchanged, except that snapshots in `OFFER_BREAKDOWN` flow through the same
lock → transition → persist → commit path as every other active state. No
new use cases and no signature changes.

### Persistence

One migration widens the state check to admit `OFFER_BREAKDOWN` (drop and
re-add the named constraint). All existing rows satisfy the wider set, so the
upgrade requires no data migration. Before restoring the narrower check, the
downgrade rewinds any `OFFER_BREAKDOWN` row to `ASSESS_TASK`, resets
`involves_multiple_steps` to null, and clears proposed titles. This discards
only an accepted answer from an unfinished workflow; no todo exists yet. No
columns, indexes, or tables are added: step identity is derived, not stored.

### HTTP

Handlers keep authenticating, parsing, translating, calling, and mapping.
They now attach `present_workflow(snapshot)` as the `view` field of every
workflow response. No new endpoints and no new methods or headers; CORS is
untouched.

### Frontend

The host switches on `snapshot.view.type` through a template registry
instead of switching on `snapshot.state`. The four template components own
only rendering, input collection, and accessibility for their view shape.
Business branching never appears in React: no component reads workflow
state to decide what comes next, and no screen predicts the next step.

## Step identity and local interaction state

Each view carries `step_id`, derived deterministically as
`"{workflow_id}:{state}"` (for example,
`a5693d6a-…:OFFER_BREAKDOWN`). No step identifier exists in Phase 7 code,
responses, or schema, so there is nothing to reuse; derivation adds no
migration and no rotation logic. This satisfies all four Phase 8 identity
requirements with no migration:

- `ASSESS_TASK` and `OFFER_BREAKDOWN` yield different identities, so the
  shared yes/no component never confuses the two questions;
- re-fetching the same current step recomputes the identical string;
- every advance changes state and therefore identity;
- the template host uses `key={view.step_id}` to remount template-local state,
  and its step-change handler clears host-owned drafts and errors and triggers
  focus only when the identity changes. A same-identity refetch does neither.

The derivation rests on one documented assumption: the state graph is
acyclic — no transition re-enters a state — which holds for all six states
and is pinned by a domain unit test enumerating every valid transition path
and asserting that no path repeats a state. A no-self-loop assertion is not
sufficient because it would miss a multi-state cycle. If a future phase ever
adds cycles, identity must be revisited then; step identity is a rendering
correctness tool and is never used in cache keys, nor claimed as concurrency
control or idempotency.

## HTTP contract

### Envelope

Every start, fetch, and advance returns the same envelope: all Phase 7
fields unchanged, plus `view`:

```json
{
  "workflow_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3",
  "state": "ASSESS_TASK",
  "title": "Plan birthday party",
  "context": {
    "involves_multiple_steps": null,
    "proposed_todo_titles": []
  },
  "result": null,
  "view": {
    "type": "yes_no",
    "step_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3:ASSESS_TASK",
    "title": "Plan birthday party",
    "question": "Does this task involve multiple steps?",
    "actions": [
      {"id": "yes", "label": "Yes"},
      {"id": "no", "label": "No"}
    ]
  }
}
```

### Second yes/no response

Answering Yes in `ASSESS_TASK` now returns `OFFER_BREAKDOWN` with the same
`yes_no` type but different content and identity:

```json
{
  "state": "OFFER_BREAKDOWN",
  "context": {
    "involves_multiple_steps": true,
    "proposed_todo_titles": []
  },
  "view": {
    "type": "yes_no",
    "step_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3:OFFER_BREAKDOWN",
    "title": "Plan birthday party",
    "question": "Would you like to split it into smaller todos?",
    "actions": [
      {"id": "yes", "label": "Yes"},
      {"id": "no", "label": "No"}
    ]
  }
}
```

Answering Yes here enters `COLLECT_TASKS`; answering No enters `REVIEW`
with `["Plan birthday party"]`. Both paths preserve
`"involves_multiple_steps": true`.

### Task breakdown response

```json
{
  "state": "COLLECT_TASKS",
  "view": {
    "type": "task_breakdown",
    "step_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3:COLLECT_TASKS",
    "title": "Break it into smaller todos",
    "min_titles": 2,
    "max_titles": 10
  }
}
```

### Review response

```json
{
  "state": "REVIEW",
  "view": {
    "type": "review",
    "step_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3:REVIEW",
    "title": "Review your plan",
    "proposed_titles": ["Send invitations", "Order birthday cake", "Buy decorations"]
  }
}
```

### Terminal responses

Both terminals share the `completion` template with an explicit outcome:

```json
{
  "state": "COMPLETED",
  "view": {
    "type": "completion",
    "step_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3:COMPLETED",
    "title": "Plan complete",
    "outcome": "completed",
    "created_todos": [
      {"id": "5f699d61-9449-407e-aa37-89e759b78df0", "title": "Send invitations", "completed": false}
    ]
  }
}
```

`CANCELLED` returns the same shape with `"outcome": "cancelled"` and
`"created_todos": []`.

### Action submissions

Unchanged from Phase 7 for every template:

```json
{"action": "answer_multiple_steps", "answer": true}
{"action": "submit_tasks", "titles": ["Send invitations", "Order birthday cake"]}
{"action": "confirm"}
{"action": "cancel"}
```

The yes/no template maps its selected action id (`yes`/`no`) to the
`answer` Boolean. Template types define the remaining fixed controls:
`task_breakdown` submits `submit_tasks`, `review` submits `confirm`, and the
host offers `cancel` on every nonterminal template. Thus `actions[]` describes
the yes/no choices, not every domain-valid command. The backend remains
authoritative and rejects a well-formed command in the wrong state. Clients
submit actions and input, never a desired next state.

### Error contract

All Phase 7 statuses and bodies are unchanged, including the exact `401`,
owner-hidden `404`, wrong-state and terminal `409`s, `422`, and `503`.
`OFFER_BREAKDOWN` participates in the existing cancellation, terminal, and
ownership rules with no new error shape.

## Transactions and rollback

Unchanged. `OFFER_BREAKDOWN` transitions persist through the same
lock → transition → persist → commit path. Confirmation still performs
lock, validate, insert-all, store-result, mark-`COMPLETED`, commit-or-roll-back
as one unit. No new transaction boundaries are introduced.

## Authentication, ownership, and cache isolation

Unchanged. Every workflow endpoint requires the Phase 6 Bearer session;
every lookup stays `(public_id, owner_id)`; cross-owner UUIDs read as
absent. The TanStack key `["todo-workflow", userPublicId, workflowId]`
is unchanged — step identity is deliberately excluded from cache keys —
and existing clearing on authentication transitions stays mandatory.
The frontend invalidates `['todos']` when a `completion` view has
`outcome="completed"`; it does not inspect the business state.

## Frontend state and components

The host owns the workflow ID, drafts, focus signals, error copy, and the
Busy-gated pessimistic mutation pattern exactly as in Phase 7. It tracks the
last rendered `step_id`: a changed identity clears step-local drafts and
errors and triggers the next template's announcement and focus, while an
identical identity preserves them. Selection uses `snapshot.view.type`
through the registry instead of `snapshot.state` through a state switch.

| Template | Component | Content source |
| --- | --- | --- |
| `yes_no` | `YesNoTemplate` | `title`, `question`, `actions[]` |
| `task_breakdown` | `TaskBreakdownTemplate` | `title`, `min_titles`, `max_titles` |
| `review` | `ReviewTemplate` | `title`, `proposed_titles[]` |
| `completion` | `CompletionTemplate` | `title`, `outcome`, `created_todos[]` |

Components reuse Phase 7 copy (extended with the OFFER question and the
fallback message), styles, field labels, button conventions, and the
focus/announcement behavior per template: title input, first yes/no
action, breakdown input, confirm action, terminal return action.

### Unknown-template fallback

When `view.type` is not one of the four supported types, the runtime guard
accepts the response into a fallback view object instead of failing the
whole snapshot as invalid data, and the registry renders a fallback
screen: an understandable message plus **Back to todos** and **Reload
plan**. It never crashes, guesses a component, or submits an action.

The TypeScript transport treats the envelope's `state` as an opaque,
non-empty string and validates `context` structurally rather than using
business-state branches. Known views retain exact-key validation. An unknown
view is accepted only when it is an object with a non-empty string `type` and
a `step_id` equal to `"{workflow_id}:{state}"` from the validated envelope;
its other fields are ignored by the fallback.
Bad workflow UUIDs, missing envelope or base-view keys, mistyped base fields,
and malformed known views keep the existing invalid-data path. This lets a
future state with a future template reach the fallback without making the
current client interpret either one. The fallback is forward compatibility,
not a license for servers to invent UI: only supported native components and
known action types may be used.

## Submission and recovery behavior

Unchanged from Phase 7, including single-retry safe GETs, never-retried
mutations, stale marking with kept drafts, **Reload plan** reconciliation,
lost-start limits, and `409`-triggered safe GET. No Phase 9 reliability is
implied: duplicate-free retries, stale-step detection, and cross-device
resume remain explicitly out of scope.

## Accessibility

Phase 7 conventions carry over unchanged: safe area, scrolling, keyboard
insets, header roles, labelled inputs, alert semantics, button roles with
disabled state, ordered review labels, text-plus-disabled submission
state, and 44-point targets. New coverage asserts the OFFER question
renders through the shared component with its own accessible name,
draft/error reset between the two questions, step-change announcement and
focus, and fallback semantics.

## Deterministic testing

| Layer | Required coverage |
| --- | --- |
| Domain unit | The two changed/new transition rows; first-answer preservation in both OFFER branches; all valid paths contain no repeated state; all Phase 7 rows unchanged |
| Presentation unit | Exact view per state for all six states; both yes/no views share type with distinct content and identities; identity stability across repeated mapping; terminal outcome mapping |
| Validation unit | Discriminated view union, unknown-field rejection, title/limit rules |
| PostgreSQL repository | CHECK widening (OFFER rows persist, old rows valid); downgrade rewinds OFFER rows before narrowing; existing constraints untouched |
| PostgreSQL service | Full three-path journeys through the service; saved OFFER progress across sessions |
| API integration | Exact view envelopes for both yes/no responses, breakdown/review/terminal views, action submissions per template, invalid actions in OFFER, cancellation from OFFER, ownership, side-effect-free GET, `503`, OpenAPI with the view union, CORS |
| Learning experiment | Backend-only OFFER addition: domain row, mapper case, migration, contract tests — with zero new components and zero frontend branching, plus a component test proving the OFFER view renders through the shared yes/no template |
| TypeScript transport | View runtime validation per template, opaque state and structural context handling, unknown state/type fallback acceptance, malformed-body rejection, declined-breakdown context, and Bearer/401/409/422/timeout behavior preserved |
| Component | Both questions through one component with reset between them, correct content/labels/submission per question, stable-identity refetch without reset, fallback screen, preserved transaction/todo/focus/a11y behavior |
| Full regression | Existing auth, CRUD, workflow, API, database, mobile, lint, typecheck, and web-export checks, including all unmodified Phase 7 suites |

Branch coverage stays primarily in domain, API, and focused component
tests, matching the existing pyramid.

## Acceptance criteria

Phase 8 is acceptable when:

1. Quick-add, existing `/todos` contracts, and all Phase 7 suites pass
   unmodified except where the new state and contract require additions.
2. All three birthday-party paths work for arbitrary valid titles.
   The two paths that answer Yes first retain
   `involves_multiple_steps=true`, including when breakdown is declined.
3. Both yes/no questions render through one shared component with distinct
   content, labels, and step identities.
4. No selection, draft, or error survives moving between the two questions.
5. Refetching the same current step keeps identity, content, and local
   draft intact.
6. Unknown template types render the fallback with safe navigation and
   submit nothing.
7. Malformed responses still take the invalid-data path.
8. No todo exists before confirmation on any path.
9. OFFER accepts cancel, rejects misplaced actions, and participates in
   terminal and ownership rules.
10. State and accepted context survive separate requests and API restarts.
11. Fetching and redisplaying never advance the workflow.
12. Clients never submit or predict a next state; the domain never names UI.
13. Authentication, owner-scoped `404`, user-isolated caching, and
    completion todo-invalidation hold.
14. Targeted suites and the full quality gate pass during implementation.
15. Guide 08 is written only after the feature is implemented and verified.
16. No Phase 9 feature, completion claim, checkpoint tag, push, or PR is
    produced during planning.

## Documentation and checkpoint

The standalone implementation plan is created only after this written
specification is approved. It must distinguish commands already run from
future commands and cannot claim that unimplemented tests pass.

After implementation and verification, create
`docs/guides/08-server-directed-ui.md`. The guide explains domain state
versus presentation type, how one yes/no component serves two questions,
how step identity prevents stale local state, when backend changes do and
do not require frontend changes, the backend-only additional-question
experiment, and what remains for Phase 9.

README and roadmap implementation status change only after verified feature
acceptance. Phase 8 completes only after focused and full checks, supported
web and iOS manual acceptance, whole-branch review, integration, and
passing CI on the exact integrated commit. Only then may an annotated
`phase-08-server-directed-screens` tag be created.

## Future extension boundary and limitations

Phase 9 can add discovery, atomic revisions, submission identifiers,
idempotency records, definition versions, and reliable cross-device
recovery on top of this contract without changing the template system:
`step_id` gains siblings rather than a replacement. Phase 9 must revisit
the acyclicity assumption explicitly if it ever introduces a
state-re-entering transition.

Phase 8 cannot discover unfinished workflows after a lost ID, guarantee
duplicate-free start retries, detect stale intent from another device, or
promise cross-device resumption — unchanged Phase 7 limitations, still
documented rather than hidden.
