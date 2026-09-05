# Phase 3: API contract and vertical slice

Phase 3 connects the todo screen to FastAPI. Web and iOS now load, create,
complete, and reactivate the same ordered todos while one API process is
running. The phase keeps data in memory so the request contract and recovery
states stay visible before persistence arrives in the next phase.

## Start both processes

Complete the [Phase 0 macOS setup guide](../setup/macos.md), install the locked
dependencies, and configure the public API URL as described in the
[Phase 1 project foundation guide](01-project-foundation.md). Open two terminals
at the repository root.

Terminal 1 — FastAPI:

```bash
pnpm dev:api
```

Terminal 2 — Expo:

```bash
pnpm dev:mobile
```

FastAPI listens on `http://127.0.0.1:8000`. Expo serves web from the exact
origin `http://localhost:8081`; press `w` for web or `i` for the reference
iPhone 17 Pro Simulator. Keep both terminals visible while testing so a client
message can be compared with the server log.

## Read the HTTP contract

One FastAPI application instance owns an insertion-ordered in-memory todo
collection. It publishes three operations:

| Operation | Request | Success | Client error |
| --- | --- | --- | --- |
| `GET /todos` | No body | `200` with `Todo[]` | None |
| `POST /todos` | `{"title": string}` | `201` with an active `Todo` | `422` for an invalid body |
| `PATCH /todos/{id}` | `{"completed": boolean}` | `200` with the updated `Todo` | `404` if absent; `422` for an invalid ID or body |

A todo has exactly three fields:

```json
{
  "id": "6fc33b84-16a8-4d8e-ae94-fc50bb457d72",
  "title": "Buy milk",
  "completed": false
}
```

IDs are random UUID strings. Duplicate titles are allowed and remain separate
rows. PATCH receives the desired Boolean state, so sending `true` twice leaves
the todo completed rather than toggling it twice. Updating completion does not
move a row.

Request objects reject unknown fields. A title must be a JSON string. The API
applies the same edge whitespace as JavaScript `trim()`, rejects unpaired UTF-16
surrogates, and accepts 1–120 Unicode code points after trimming. Counting code
points matters for astral characters: 120 emoji are valid and 121 are not.
PATCH accepts only JSON `true` or `false`; numbers and strings do not coerce to
Boolean values.

Open `http://127.0.0.1:8000/docs` to inspect and exercise the generated OpenAPI
documentation. The schema comes from the FastAPI and Pydantic models; this
phase does not check in a second schema or generate client code.

The collection lasts only as long as that application process. Web and iOS
share rows when they use the same running process. Restarting FastAPI clears
the collection, and running multiple API workers would give each worker its
own separate collection.

## Understand the TypeScript boundary

`apps/mobile/src/todos/todoApi.ts` declares the TypeScript `Todo` type and the
three client functions. A type annotation cannot prove that network JSON has
the promised shape, so the module checks every successful response at runtime.
It rejects missing, extra, or wrong-type fields, malformed UUIDs, non-canonical
titles, invalid JSON, and unexpected success statuses.

Each request uses one five-second deadline that includes reading the JSON body.
The client relays caller cancellation and removes its timer and abort listener
on every completion path. Error objects expose safe categories and fixed UI
copy; server response prose and caught exception text do not reach the screen.
Mutations are not retried automatically.

## Follow the screen states

On mount, the screen displays **Loading todos…** and starts one GET. A successful
load replaces the rows and reveals **Refresh**. An initial failure displays
**Could not load todos.** with **Retry** and does not also display an empty-list
message. A later failed refresh preserves the visible rows and displays
**Could not refresh todos.**

Only one remote operation is accepted at a time. Add, submit, refresh, retry,
checkbox press, and checkbox Space activation share a synchronous gate. Remote
controls are disabled while an operation is pending, while All, Active, and
Completed remain usable because they only derive a local view.

Create and completion changes are deliberately not optimistic. POST appends
the canonical todo returned by the API, and PATCH replaces the matching row
after success. The server remains authoritative for IDs, normalized titles,
and completion state. A successful create clears the draft and returns focus
to the title field.

Each accepted request has an identity and an `AbortController`. A newer
accepted load invalidates the older load, and unmounting aborts the active
request. Late and cancelled results cannot update the remounted screen.

Validation and missing-row failures are known outcomes with direct recovery:

- **Check the todo title and try again.** keeps the create draft.
- **That todo no longer exists. Refresh the list.** keeps local rows until the
  learner refreshes.

A timeout, transport failure, or invalid mutation response is different. The
write may have reached the API even though the client never received a usable
result. The screen therefore keeps its draft and rows, displays **The result may
be unknown. Refresh before making more changes.**, and disables further writes
until Refresh succeeds. The refresh replaces the list while preserving the
draft and current filter. Inspect the refreshed rows before manually
resubmitting: if the first create landed, another submission can make a valid
duplicate.

Refresh preserves the selected filter. Remounting the app starts a new screen,
selects All, and loads the same server rows while the API process remains alive.

## Understand browser CORS

FastAPI allows the exact browser origin `http://localhost:8081` for GET, POST,
and PATCH. `Content-Type` is explicitly allowed for JSON mutations, credentials
are disabled, and an unlisted origin receives no allow-origin response header.
iOS follows the same HTTP contract but does not rely on browser CORS
enforcement.

## Run the checks

Use focused checks while changing one layer:

```bash
uv run --directory apps/api python -m pytest tests/test_todos.py tests/test_health.py -v
pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts
pnpm --dir apps/mobile test --runInBand src/TodoScreen.test.tsx App.test.tsx
```

Before acceptance, run the repository gate:

```bash
pnpm quality
```

The automated suites use fresh in-process API apps, injected fetch functions,
and deferred screen promises. They do not replace the browser and Simulator
journey below. A web export proves that Expo can build the target; it does not
prove visible interaction.

## Manual journey

Use one fresh FastAPI process for both targets.

1. Open `/docs` and confirm GET/POST `/todos` and PATCH `/todos/{id}` appear.
2. On web, load the All empty state and reject whitespace, 121 code points, and
   an unpaired surrogate title.
3. Create two `Buy milk` todos and complete one. Confirm the duplicate rows are
   independent and the Active and Completed filters show the expected row.
4. On iOS, refresh and confirm the same UUID-backed rows appear. Reactivate the
   completed row and create another todo.
5. Select a non-All filter and Refresh. Confirm the filter remains selected.
   Remount the app and confirm All is selected while the server rows remain.
6. Stop FastAPI, attempt a mutation, and confirm the unknown-result message and
   write lock. Restart FastAPI, select Refresh, and confirm recovery while the
   draft and selected filter remain.
7. Restart FastAPI once more, select Refresh, and confirm the All empty state
   because the process-local collection was reset.

Real HTTP checks on 2026-09-05 exercised health, list, canonical create,
completion/reactivation, OpenAPI, CORS, and the actual TypeScript client against
Uvicorn. Metro also compiled web and iOS bundles. Those checks are useful
integration evidence but are not visual acceptance, so the target results stay
unchecked until the journey is observed.

## Phase 3 acceptance record

| Target | Date | Runtime | Shared create + toggle | Filter Refresh + All on remount | Network recovery | API restart resets |
| --- | --- | --- | --- | --- | --- | --- |
| Web | Pending | `http://localhost:8081` | ☐ | ☐ | ☐ | ☐ |
| iOS Simulator | Pending | iPhone 17 Pro, iOS 26.5, Expo Go version pending | ☐ | ☐ | ☐ | ☐ |
