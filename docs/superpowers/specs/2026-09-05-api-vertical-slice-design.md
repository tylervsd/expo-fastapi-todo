# Phase 3 API Contract and Vertical Slice Design

**Status:** Implemented and locally accepted on 2026-09-05; release checkpoint pending

**Confirmed decision:** Completion and reactivation remain API-backed, as
confirmed by the user on 2026-09-05.

## Outcome

Phase 3 connects the existing todo screen to FastAPI. A learner can load,
create, complete, and reactivate todos on web and iOS, and both clients see the
same ordered data while one API process is running.

The phase teaches explicit REST contracts, server validation, generated
OpenAPI, runtime-checked TypeScript responses, request cancellation, and honest
recovery from uncertain writes. Data remains in memory so database concepts
stay in Phase 4.

## Scope

This phase adds `GET /todos`, `POST /todos`, and completed-only
`PATCH /todos/{id}`. It retains Phase 2's title form, reversible checkboxes,
local All/Active/Completed filters, contextual empty states, web keyboard
behavior, scrolling, keyboard insets, and safe-area layout.

It does not add a database, authentication, edit/delete operations, pagination,
sorting, a cache, a repository or service layer, optimistic updates, automatic
mutation retries, idempotency keys, generated client code, navigation, or
browser/iOS E2E automation. It adds no dependency.

## Server model and lifetime

`create_app()` builds FastAPI and closes over one insertion-ordered todo
collection. The exported `app = create_app()` serves the application, while
tests create a fresh app for isolation. Route handlers are `async def` with no
awaited work, so one process updates this teaching-sized collection without a
lock. Random UUIDs from Python's standard library avoid the predictable ID
reuse that a per-process counter would cause after restart.

The state is shared by web and iOS against that API instance. A mobile reload
reads the same data. Restarting the server clears every todo; multiple workers
would each have separate state and are outside this phase.

The response model is:

```json
{"id":"6fc33b84-16a8-4d8e-ae94-fc50bb457d72","title":"Buy milk","completed":false}
```

`id` is a UUID string, `title` is canonical, and `completed` is Boolean. Lists
retain creation order and duplicate titles are allowed.

## HTTP contract

| Operation | Request | Success | Client error |
| --- | --- | --- | --- |
| `GET /todos` | no body | `200` and `Todo[]` | none |
| `POST /todos` | `{"title": string}` | `201` and the active `Todo` | `422` invalid body |
| `PATCH /todos/{id}` | `{"completed": boolean}` | `200` and the updated `Todo` | `404` missing todo; `422` invalid UUID/body |

Request objects reject unknown properties. Title accepts only a JSON string and
PATCH accepts only JSON `true` or `false`, without Pydantic coercion. PATCH sets
the requested Boolean; it is not a toggle command, so repeating the same request
has the same final state. A missing todo returns exactly
`{"detail":"Todo not found."}`. FastAPI's standard validation response supplies
`detail` entries for `422`; clients do not depend on their prose.

Titles use ECMAScript `String.prototype.trim` edge whitespace so Phase 2's
normalization remains stable. Python uses an explicit equivalent character set
rather than `str.strip()`. The canonical title must contain 1–120 Unicode code
points and contain no unpaired surrogate. JavaScript counts with
`Array.from(title).length`, replacing Phase 2's UTF-16 `string.length`; Python
`len()` then matches astral characters such as emoji. The server is
authoritative and returns the canonical title.

FastAPI request models and field validators enforce these rules and expose the
schemas through its generated `/openapi.json` and `/docs`; there is no checked-in
schema or generated client. This follows FastAPI request-body modeling and
Pydantic validator behavior.

## CORS

The only allowed browser origin remains `http://localhost:8081`, without
credentials. Allowed methods are exactly `GET`, `POST`, and `PATCH`;
`Content-Type` is explicitly allowed in addition to the safelisted headers
Starlette includes. Tests cover GET health preflight, POST/PATCH todo preflight,
and an unlisted origin.

## Mobile client boundary

`src/todos/todoApi.ts` owns the `Todo` type plus `listTodos`, `createTodo`, and
`setTodoCompleted`. It derives URLs from `EXPO_PUBLIC_API_URL`, uses five-second
timeouts, relays caller cancellation, sends JSON only for mutations, and always
cleans up timers and listeners. This is a narrow todo transport helper; the
Phase 1 health client remains unchanged.

TypeScript annotations do not validate JSON. The client therefore checks the
exact keys and value types of every returned todo, including UUID shape,
canonical title length, and Boolean completion. It rejects malformed arrays,
unexpected success statuses, invalid JSON, `404`, `422`, and other failures as
typed safe errors. Error bodies and exception text never reach the UI. Caller
cancellation rejects as `AbortError`; the screen suppresses it after invalidating
that operation rather than presenting it as a request failure.

Cancellation prevents late state updates but does not roll back a POST or
PATCH that reached the server. Mutations are never retried automatically.

## Screen behavior and reconciliation

On mount, the screen shows **Loading todos…** and starts one list request. A
successful response replaces the list and exposes **Refresh**. Initial loading
does not permit writes. Initial failure shows **Could not load todos.** and
**Retry** without also showing an empty-list message. A later failed refresh
preserves displayed data, reports **Could not refresh todos.**, and keeps writes
disabled until Refresh succeeds.

One synchronous busy guard permits only one remote operation at a time,
including rapid button, keyboard, press, and Space events. Remote controls are
disabled while busy; filters remain usable because they only derive a local
view. Each operation has an AbortController and attempt identity. Unmount or a
new accepted load aborts and invalidates the old attempt.

Create keeps Phase 2's matching local validation. Success appends the returned
server todo, clears the disabled draft, clears the error, and refocuses the
field. PATCH sends the desired inverse of the current completion value; success
replaces that todo with the returned server value. Neither operation changes
the list before success.

A server `422` keeps the draft and shows **Check the todo title and try again.**
A missing PATCH target leaves data unchanged and shows **That todo no longer
exists. Refresh the list.** A timeout, network failure, or invalid mutation
response leaves local data unchanged and shows **The result may be unknown.
Refresh before making more changes.**, with a visible **Refresh** action. Further
writes stay disabled until Refresh succeeds and replaces the list; the current
filter and retained create draft survive Refresh. An earlier write may have
landed, so the learner inspects the refreshed list before manually resubmitting,
which can still duplicate a create. Remount selects All and reloads server data.

## Deterministic testing

Fresh-app FastAPI tests prove exact statuses and JSON, normalization, 120-code-
point boundaries including emoji, duplicate insertion order, completed-only
PATCH semantics, UUID and body errors, isolated app state, OpenAPI paths/schema,
and CORS. The existing health tests remain green.

Todo-client tests inject fetch and fake timers to prove method/URL/body/header,
runtime response validation, safe status mapping, five-second timeout, caller
cancellation, and cleanup without a live API. Screen tests inject the three API
functions and deferred promises to prove loading, retry/refresh, create, PATCH,
filters, validation, a rapid-event gate, no optimistic changes, uncertain-write
copy, stale-result protection, and unmount cancellation. Tests do not use real
time, a server, browser, or simulator.

## Manual acceptance

With one fresh API process, verify `/docs` lists the three operations. On web,
load empty state, reject invalid titles, create two same-title todos, and toggle
one. On iOS, refresh and observe the same UUID-backed rows, reactivate the
completed row, and create another todo. Select a non-All filter and refresh to
confirm refresh preserves it; reload the app to confirm remount selects All
while server data remains. Stop the API before attempting a mutation to verify
honest uncertain-result copy and disabled writes, then restart it and refresh;
finally restart the API once more and refresh to observe empty state. Record
actual runtimes and both targets in
`docs/guides/03-api-vertical-slice.md`.

Phase 3 is complete after focused and full quality checks pass, the journey is
recorded on web and the reference iOS Simulator, whole-branch review has no
unresolved findings, CI passes on the integrated commit, and that commit is
tagged `phase-03-api-vertical-slice`.

## Sources

- [FastAPI request bodies](https://fastapi.tiangolo.com/tutorial/body/)
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)
- [Pydantic validators](https://pydantic.dev/docs/validation/latest/concepts/validators/)
