# Phase 9 Workflow Reliability Design

**Status:** Approved by the user (2026-09-07, America/Los_Angeles). Implementation has not started.

## Outcome

Phase 9 makes the existing guided todo workflow safe to resume and retry. A
signed-in user can discover every unfinished plan, resume one on web or iOS,
and retry a start or action whose response was lost without creating a second
draft, advancing twice, or creating duplicate todos. If another device has
already advanced the plan, the client reloads the authoritative current step
and explains that the submitted answer was stale.

The backend remains authoritative. PostgreSQL owns revisions, idempotency
records, accepted outcomes, workflow state, and todo creation. The client keeps
only the latest server snapshot, unsubmitted form state, and one narrowly
scoped durable recovery record for a write whose result is unknown. Phase 9
does not add an offline command queue, event sourcing, background work, or an
external side effect.

## Scope

Phase 9 adds:

- owner-scoped discovery of all nonterminal workflows;
- resume of a selected saved workflow through the existing template host;
- an integer revision returned by start, discovery, fetch, and advance;
- request identifiers and payload fingerprints for idempotent start and
  advance operations, including simultaneous identical requests;
- a SQL revision predicate in the same transaction as each accepted action;
- atomic confirmation across todo inserts, workflow completion, revision, and
  the recorded idempotency outcome;
- persisted workflow-definition version `1`, backfilled onto existing rows;
- explicit view-contract version `1` and safe handling of unsupported versions;
- a durable, owner-bound client recovery record written before each workflow
  mutation and cleared only after reconciliation;
- client cache guards that reject older revisions and responses from a stale
  authentication session;
- focused PostgreSQL race/rollback tests and React Native recovery tests.

The existing states and acyclic graph remain unchanged. The existing
`"{workflow_id}:{state}"` step IDs therefore remain valid: a same-step fetch
keeps its identity and every accepted transition reaches a different state.
Step IDs identify rendered interaction state; revisions detect concurrent
business writes; request IDs identify one intended mutation. They are not
interchangeable.

Quick add, `/todos`, authentication, the presentation mapper, the four native
workflow templates, pessimistic workflow updates, title limits, and the 2-10
breakdown limit remain available and keep their current behavior.

## Non-goals

Phase 9 does not add offline-first synchronization, a general queue, automatic
background retry, event sourcing, distributed exactly-once delivery,
cross-device draft text synchronization, expiration or deletion policy for
abandoned workflows, arbitrary server UI, LLMs, agents, workers, web sockets,
or external side effects. Unsubmitted title and breakdown text remain local
component state and may be lost on reload. Only accepted workflow context is
resumable.

The client recovery journal covers the application instance's current unknown
workflow write. Multiple browser tabs sharing one installation are not a
Phase 9 coordination target. Backend correctness still covers independent
clients and devices.

## Chosen approach

Extend the current service and repository boundaries. Add revision and
definition columns to `todo_workflows`, plus one idempotency table for starts
and one for actions. The separate tables keep their uniqueness and foreign-key
rules direct instead of introducing nullable polymorphic columns. Each record
stores a SHA-256 fingerprint of the canonical request and the accepted domain
snapshot. The HTTP layer presents that saved snapshot through the existing
presentation mapper, so replay does not make persistence depend on response
models or React templates.

An action continues to lock its owner-scoped workflow row. Inside that same
transaction it resolves a prior request before checking the submitted
revision, evaluates the domain transition, writes todos when confirming,
updates the workflow using `WHERE revision = :expected_revision`, records the
accepted snapshot, and commits. The row lock gives clear serialization; the
SQL revision predicate makes the concurrency precondition part of the write.

For starts, the service generates the workflow UUID and complete initial
domain snapshot before claiming the request. The start-request row references
that UUID with a deferred foreign key, allowing the final recorded snapshot to
be inserted before the workflow. An identical
concurrent loser waits on the unique constraint, inserts nothing, then reads
the winner in a subsequent SQL statement. PostgreSQL `READ COMMITTED` gives
each statement a fresh snapshot; replay must not be folded into the same
`INSERT ... ON CONFLICT` statement.

## Data model and migration

Migration `2026090901_add_workflow_reliability.py` performs these changes:

1. Add `revision INTEGER` and `definition_version INTEGER` to
   `todo_workflows`, initially nullable.
2. Backfill every existing workflow with `revision = 0` and
   `definition_version = 1`. Revision is a concurrency token, not an audit
   count, so reconstructing historical transition counts is unnecessary.
3. Make both columns non-null, add `revision BETWEEN 0 AND 2147483647` and
   `definition_version >= 1` checks, and set server defaults `0` and `1`.
4. Add a unique constraint on `(public_id, owner_id)` so action idempotency can
   use an ownership-preserving composite foreign key.
5. Create the two request tables below.

`todo_workflow_start_requests`:

| Column | Contract |
| --- | --- |
| `owner_id` | Required FK to `users.id`, cascade on owner deletion |
| `request_id` | UUID supplied by the client |
| `request_fingerprint` | Lowercase 64-character SHA-256 hex digest |
| `workflow_id` | Required UUID, deferred FK to `todo_workflows.public_id` |
| `accepted_snapshot` | Required JSONB object containing the complete initial domain snapshot |

Primary key `(owner_id, request_id)` provides owner-scoped start idempotency.
The workflow foreign key is `DEFERRABLE INITIALLY DEFERRED`; a winning claim
and its workflow must both exist by commit. Owner deletion cascades to both
rows. Deleting a workflow cascades its start record.

`todo_workflow_action_requests`:

| Column | Contract |
| --- | --- |
| `owner_id`, `workflow_id` | Composite FK to the owned workflow, cascade on delete |
| `request_id` | UUID supplied by the client |
| `request_fingerprint` | Lowercase 64-character SHA-256 hex digest |
| `accepted_snapshot` | Required JSONB object containing the domain snapshot |

Primary key `(owner_id, workflow_id, request_id)` provides action idempotency.
There is no durable `pending` status: claim, business writes, and outcome commit
together, so a failed transaction leaves no claim that could strand a retry.

Accepted snapshots contain exactly `workflow_id`, `revision`,
`definition_version`, `state`, `title`, `involves_multiple_steps`,
`proposed_todo_titles`, and nullable `created_todos`. Repository serialization
validates exact keys and domain invariants when reading. A malformed stored
snapshot fails closed as a database-data error; it is never partially trusted.

Downgrade drops the two request tables and new constraints/columns. It does not
delete workflows or todos. The test database fixture advances its pinned head
from `2026090801` to `2026090901`; its existing `TRUNCATE ... CASCADE` covers
the new dependent tables.

## Definition and presentation versions

`definition_version` records which transition rules interpret a saved
workflow. New workflows use constant `CURRENT_WORKFLOW_DEFINITION_VERSION = 1`.
The domain transition entry point takes the version explicitly and dispatches
only to supported definitions. Version 1 is exactly the Phase 8 graph; no state
or transition changes in Phase 9.

Existing workflows are backfilled to version 1 because those are the rules
under which they were created. A future incompatible definition must use a new
integer and retain the old transition and presentation mapping until its saved
drafts are terminal or explicitly migrated. Deployment must not silently run
an older draft through newer rules.

Rows with an unknown definition version are readable only far enough to
identify the owner and workflow. Discovery and fetch return `409` with code
`unsupported_workflow_definition`; advance returns the same response without
recording an idempotency outcome or changing data. This is an operational
configuration/data problem rather than a client validation error.

`view_contract_version` is separate and is not persisted because it describes
the current response encoding. Every Phase 9 snapshot response carries
`view_contract_version: 1`. The TypeScript parser handles version 1 strictly.
For any other positive integer it validates only the stable metadata prefix
(`workflow_id`, `revision`, `definition_version`, and
`view_contract_version`) and produces an explicit client-only unsupported member. Missing, noninteger,
zero, out-of-range, or malformed stable metadata remains an `invalid-data`
transport error. The unsupported member renders recovery controls and never
submits a workflow action.

Use a client union with a shared metadata prefix: `KnownTodoWorkflow` contains
all version-1 fields; `UnsupportedContractWorkflow` contains only the validated
metadata and `view: { type: "unsupported", server_type: "contract:<version>",
step_id: "<workflow_id>:unsupported-contract:<version>" }`. The exported
`TodoWorkflow` is their union. Do not invent title, state, context, or result
values for an unknown contract. Components must narrow the union before using
known-contract fields; revision reconciliation can use the common prefix.
Unknown templates within version 1 retain Phase 8's existing fallback.

## HTTP contracts

All workflow routes require the existing Bearer session. UUIDs are canonical
JSON strings. Request objects reject unknown keys, revisions are integers from
zero through `2147483647`, and request IDs are UUIDs. Enforce strict integer
validation in Pydantic and integer/range checks in TypeScript. A new action at
the maximum returns `409 revision_exhausted` before writes; an existing
matching request remains replayable.

### Start

`POST /todo-workflows` returns `201` for the first accepted request and an
identical replay, including concurrent replay.

```json
{
  "request_id": "30bfb542-17f1-48a0-9fd8-3930379d5974",
  "title": "Plan birthday party"
}
```

The request fingerprint is SHA-256 over UTF-8 canonical JSON containing
`{"operation":"start","title":<canonical title>}` with sorted keys and
compact separators. The request ID itself and authentication token are not in
the fingerprint.

### Discover active workflows

`GET /todo-workflows?status=active` returns `200`. Omitted `status` defaults
to `active`; any other value returns `422`. The list is deliberately unpaginated
for this local tutorial; if workflow volume grows, add pagination without
silently limiting discoverability. Response shape:

```json
{"items": []}
```

A nonempty `items` array contains full `TodoWorkflowResponse` objects.

Only `ASSESS_TASK`, `OFFER_BREAKDOWN`, `COLLECT_TASKS`, and `REVIEW` rows owned
by the current user are returned, newest database identity first. Completed,
cancelled, missing, and other-owned workflows are absent. Discovery reads and
presents snapshots without a row lock or business write. Zero items is `200`
with `{"items":[]}`. This tutorial endpoint intentionally has no pagination;
it performs one owner-indexed active-row query. Add pagination only when a
measured number of abandoned drafts makes the bounded owner scan material.

### Fetch and resume

`GET /todo-workflows/{workflow_id}` remains `200` with the current snapshot.
It remains owner-hidden as `404` and has no business side effect.

### Advance

`POST /todo-workflows/{workflow_id}/actions` returns `200` for the first
accepted request and an identical historical replay:

```json
{
  "request_id": "f019129d-1936-4a5d-9de8-3da5aa01ccb1",
  "expected_revision": 2,
  "step_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3:COLLECT_TASKS",
  "action": {
    "action": "submit_tasks",
    "titles": ["Send invitations", "Order birthday cake"]
  }
}
```

The fingerprint is SHA-256 over compact, sorted-key UTF-8 JSON containing the
operation, workflow ID, expected revision, step ID, and canonical action. Array
order and duplicate titles remain significant. The request ID is excluded.

Every successful response has this metadata in addition to the existing
fields:

```json
{
  "workflow_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3",
  "revision": 3,
  "definition_version": 1,
  "view_contract_version": 1,
  "state": "REVIEW",
  "title": "Plan birthday party",
  "context": {
    "involves_multiple_steps": true,
    "proposed_todo_titles": ["Send invitations", "Order birthday cake"]
  },
  "result": null,
  "view": {
    "type": "review",
    "step_id": "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3:REVIEW",
    "title": "Review your plan",
    "proposed_titles": ["Send invitations", "Order birthday cake"]
  }
}
```

Start returns revision `0`. Every accepted action, including cancel and
confirm, increments by exactly one. Fetches and replays do not increment it.

### Error schema and statuses

Workflow-specific conflicts use FastAPI's `detail` envelope with a typed
object:

```json
{"detail":{"code":"stale_step","message":"This plan changed. Reload it and try again."}}
```

| Status | Code or behavior | Meaning |
| --- | --- | --- |
| `401` | Existing auth detail | Session is absent or invalid |
| `404` | Existing `Todo workflow not found.` | Missing or other-owned workflow |
| `409` | `stale_step` | Step ID or expected revision does not match current data |
| `409` | `request_id_reused` | Same scoped request ID has a different fingerprint |
| `409` | `invalid_action` | Well-formed action is invalid in the current active state |
| `409` | `terminal_workflow` | A new request targets a terminal workflow |
| `409` | `unsupported_workflow_definition` | Stored definition is not supported by this server |
| `409` | `revision_exhausted` | Revision is `2147483647`; no further action can be accepted |
| `422` | Standard validation detail | Request shape, UUID, title, Boolean, count, or bound is invalid |
| `503` | Existing database-unavailable detail | PostgreSQL operation failed or timed out |

No conflict body includes another owner's existence, state, revision, title,
or result. On `stale_step`, the client performs the safe current GET; the
conflict response does not duplicate a snapshot.

## Transaction ordering and idempotency

### Start transaction

1. Authenticate and validate/canonicalize the body before opening the service
   transaction. Generate a workflow UUID, its complete initial domain snapshot
   at revision 0/definition 1, and the request fingerprint in memory.
2. Insert the owner/request record with the complete initial snapshot using
   `INSERT ... ON CONFLICT DO NOTHING RETURNING`. Its deferred workflow foreign
   key permits the workflow row to be inserted later in this transaction.
3. If inserted, create that workflow and commit both. No provisional outcome
   or empty placeholder is ever inserted.
4. If not inserted, issue a separate `SELECT` for `(owner_id, request_id)`.
   Compare fingerprints. A mismatch raises `request_id_reused`; an identical
   fingerprint returns the recorded snapshot without creating a workflow.

A test-only failure between the record insert and workflow creation must roll
back the entire transaction. The deferred foreign key also prevents committing
an orphan request record.

### Action transaction

1. Authenticate and validate/canonicalize the body. Compute the fingerprint.
2. Lock the workflow using `(public_id, owner_id) FOR UPDATE`. Absence returns
   `404` before any idempotency record exists.
3. Read the existing `(owner_id, workflow_id, request_id)` record while holding
   that lock. Compare fingerprints before checking revision or terminal state.
   Mismatch returns `request_id_reused`; equality returns the saved snapshot.
4. For a new request, validate the stored definition, exact current step ID,
   expected revision, terminal rules, revision ceiling, and domain action.
5. Compute the pure domain decision. For confirmation, insert every todo.
6. Update the workflow and revision with one statement constrained by owner,
   workflow ID, and `revision = expected_revision`, requiring one returned row.
7. Insert the complete accepted domain snapshot and fingerprint into the
   action-request table. Its primary key enforces uniqueness; the workflow
   lock serializes concurrent checks and inserts for this workflow.
8. Commit once. Any error rolls back todos, workflow/context/revision, and
   the request outcome together. No provisional action record is needed.

The replay check precedes stale and terminal checks so a lost successful
response remains replayable after its action changed the workflow. Distinct
requests racing one revision serialize on the row lock; the first commits and
the second fails `stale_step`. Identical requests serialize and the second
returns the first accepted outcome. The SQL revision predicate remains the
last guard against an unprotected update path.

This design relies on PostgreSQL 18.6 `READ COMMITTED` behavior. A waiting
`INSERT ... ON CONFLICT DO NOTHING` can observe a conflicting row that was not
visible to that statement's original snapshot, so replay uses a following
`SELECT` statement as documented by the
[PostgreSQL 18 transaction-isolation documentation](https://www.postgresql.org/docs/18/transaction-iso.html).

## Client discovery, resume, and reconciliation

`TodoExperience` owns the selected workflow ID as part of its shell mode:
`"todos"`, `"workflow-new"`, or `{ workflowId }`. The todo screen shows a
**Resume plans** section when discovery has active items. Selecting an item
passes its ID into `TodoWorkflowScreen`; the screen no longer owns the only
copy of the ID. **Help me plan a task** still opens the empty start form and
quick add stays unchanged.

Discovery uses `['todo-workflows', userId, 'active']`. A snapshot cache key
remains `['todo-workflow', userId, workflowId]`. Discovery seeds per-workflow
cache entries only when the incoming revision is at least the cached revision.
Mutation responses and every GET completion use the same compare-before-write
helper, including GETs that began before a newer mutation completed. A
replayed historical outcome with a lower revision is recovery evidence only;
it never overwrites newer cached data. After every mutation success, the
client performs current GET and renders that result. `stale_step` does the same
current GET before enabling another write.

A start replay has no previously known workflow ID, so its recorded response
recovers the ID, conditionally seeds its saved snapshot without lowering any
existing cached revision, clears its durable record, and then fetches
the current workflow. This covers a start that committed before the app lost
the response and another device that advanced the recovered workflow.

Responses are accepted only when the captured authentication-session epoch is
still current. The epoch changes on restore, login, logout, and replacement,
including signing out and signing back in as the same public user. A stale
callback cannot populate cache, select a plan, or clear a newer recovery
record. Existing token comparison for `401` remains; tokens are never stored
in the recovery journal.

## Durable unknown-write recovery

Before sending a start or action, the client creates a UUID request ID and
persists one exact record:

```ts
type PendingWorkflowWrite =
  | { version: 1; ownerId: string; requestId: string; operation: "start";
      body: { request_id: string; title: string } }
  | { version: 1; ownerId: string; requestId: string; operation: "advance";
      workflowId: string; body: WorkflowActionRequest };
```

The record contains no session token, username, password, or server response.
Its storage key includes the public owner UUID, so another user's record is
never overwritten or loaded. Web uses `localStorage`; native uses Expo
SecureStore. Implementation adds the Expo-SDK-compatible `expo-crypto` package
solely for `randomUUID()` request IDs after reading the exact Expo SDK 57
documentation, including the
[Expo SDK 57 Crypto API](https://docs.expo.dev/versions/v57.0.0/sdk/crypto/);
no custom UUID generator is introduced.
This is a separate storage API from `TokenStorage`: unlike optional session
restoration, its `set` and `clear` errors are surfaced. The network mutation
must not begin unless the complete exact payload was read back successfully.
This preserves all existing title/count limits; it does not truncate Unicode
or silently reduce accepted inputs. If the platform cannot persist a valid
maximum-size payload, the UI says **This device could not save a safe retry.
The plan was not sent. Try again.**

Only one workflow write can be pending in one app instance. A second write is
disabled until the first settles. On a validated success, the client clears
the matching owner/request record and applies the response. A storage-clear
failure keeps the record and reports that recovery is still pending; replay is
safe. A timeout, network failure, app termination, or invalid response keeps
the record and locks new workflow writes.

After authentication, only a record whose `ownerId` equals the live user is
loaded. A different user's record is neither displayed nor submitted. A
matching record survives a new session epoch and is offered as **Retry saved
request** or **Discard saved request**; it is never sent automatically. Retry
uses the same exact body and request ID under the current token. Discard only
removes the local record and warns that the server result may already exist;
the next discovery refresh reveals any accepted start or active workflow.

For an unknown action result, retry first recovers the stored historical
outcome, then performs current GET and renders the newest revision. A stale
conflict clears the matching record and triggers current GET. For
`request_id_reused`, the record remains visible until explicitly discarded
because its identity is not safe to replace.

Definitive `422`, `404`, `invalid_action`, `terminal_workflow`,
`revision_exhausted`, and `unsupported_workflow_definition` responses clear the
matching pending record because they prove this request did not commit.
`401` requires re-authentication without replaying under another owner. Network,
`503`, and invalid-response failures retain the record. A failed cleanup must
not silently unlock another write. After every successful mutation or replay,
perform a current GET before enabling actions; a failed reconciliation GET
keeps controls disabled with a visible retry. Invalidating/refetching discovery
and todos after completion also applies when recovery finds a terminal plan.

## Accessibility and user-visible states

Resume plans uses native accessible buttons labelled with each plan title and
the current prompt/title supplied by its view. An unknown-contract item uses
**Unsupported saved plan** and its workflow ID rather than absent title fields.
Loading, empty, error, and retry
states have readable text. Opening a resumed plan applies the existing
step-change announcement/focus behavior. Stable same-step refetches preserve
current unsubmitted input; a changed step ID clears it.

Recovery and stale-state messages use `accessibilityRole="alert"`. Retry and
discard have distinct accessible names. Controls stay disabled while storage,
mutation, or reconciliation GET work is pending. The unsupported contract and
definition screens never expose action controls.

## Deterministic testing

Domain tests pin version-1 dispatch, revision-independent transition purity,
acyclic step-ID assumptions, and unknown-definition rejection. Presentation
tests prove current step IDs and views remain unchanged with the added metadata
handled outside the mapper.

PostgreSQL integration tests use independent sessions and bounded thread
barriers to prove:

- start replay, concurrent identical start, and start payload mismatch;
- action replay before stale checks, concurrent identical action, and action
  payload mismatch;
- two distinct requests against one revision produce one accepted action and
  one `stale_step` without a second revision increment;
- confirmation retry creates one exact ordered todo set;
- an injected failure after todo insertion rolls back todos, workflow state,
  revision, and request record;
- owner scoping for discovery, fetch, request identity, and actions;
- migration backfill and constraints.

API tests pin exact request and response schemas, discovery filtering/order,
all status/code rows, OpenAPI, replay status, and unavailable-database behavior.

Transport tests pin exact JSON bodies, strict version-1 parsing, unknown view
contract fallback, error-code mapping, list parsing, and abort behavior.
Storage tests cover web/native adapters, owner filtering, exact maximum-size
Unicode payload round trips, corruption, write/read-back failure, and clear
failure. Component tests cover discovery, selected-ID resume, start recovery,
action recovery, explicit retry after restart, discard, lower-revision replay,
stale GET reconciliation, same-user re-login epochs, cross-user isolation,
step-local draft reset, accessibility, and preserved quick add.

Full cross-platform automation remains Phase 12. Phase 9 finishes with manual
web and iOS observations of discovery, resume, lost-response retry, stale
reconciliation, completion, and quick add.

## Acceptance criteria

Phase 9 is acceptable when all of the following are observed or tested:

1. Owner-scoped discovery returns every and only nonterminal saved workflow.
2. Selecting a discovered workflow resumes its authoritative current view on
   web and iOS without advancing it.
3. Start and every action require a client UUID; action revision/step requirements are
   exact, and malformed inputs are rejected before a business write.
4. Sequential and simultaneous identical requests return one accepted outcome
   and produce one effect; payload mismatch returns `request_id_reused`.
5. Distinct actions racing one revision result in one advance and one
   recoverable stale conflict.
6. Confirmation, todos, revision, terminal state, and idempotency outcome
   commit or roll back together.
7. A committed response lost before receipt is recovered after an app restart
   with the same request ID and no duplicate draft, transition, or todos.
8. Historical replay never regresses a newer cache entry; current GET decides
   the rendered state.
9. Client persistence failure prevents the network write, and all valid
   maximum-size Unicode inputs are either stored exactly or rejected before
   send with explicit copy.
10. Cross-user and stale-session responses cannot reveal, render, overwrite,
    or clear another session's workflow data or recovery record.
11. Existing quick add, `/todos`, Phase 8 templates, cancellation, title/count
    validation, focus, and accessibility behavior remain green.
12. Definition version 1 is backfilled and dispatched explicitly; unsupported
    definition and view-contract versions fail safely without mutation.

## Documentation and delivery

The user approved this specification and its implementation plan together.
Both documents must be kept consistent with any subsequently approved design
changes. The phase branch is `codex/phase-09-workflow-reliability`.
Neither document claims implementation, passing tests, supported-platform
acceptance, integration, or a Phase 9 checkpoint.

Execution must begin in an isolated worktree, follow the repository's
Superpowers workflow, and read the exact Expo SDK 57 documentation required by
`apps/mobile/AGENTS.md` before mobile code is written. After implementation,
write `docs/guides/09-workflow-reliability.md` only from verified behavior.
Run focused tests, the full quality gate, manual web/iOS acceptance, and a
`gpt-5.6-sol` whole-branch review before proposing integration. No LLM or
external worker is needed; `expo-crypto` is the only planned dependency.

## Reference checks for implementation

- [PostgreSQL 18 transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html)
- [Expo SDK 57 Crypto](https://docs.expo.dev/versions/v57.0.0/sdk/crypto/)

Read the exact SDK documentation before mobile implementation and verify UUID
and storage behavior on the supported web/iOS targets. This specification does
not claim those runtime checks have already passed.
