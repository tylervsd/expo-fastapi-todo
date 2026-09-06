# Phase 5: Complete CRUD and resilient server state

Phase 5 completes the persisted todo workflow on web and iOS. Users can create,
rename, complete, reactivate, and delete todos against the same PostgreSQL
database from Phase 4. The screen now treats one TanStack Query cache as the
only owner of the remote todo collection, retries a safe GET once, reconciles
every write against a confirming GET, and locks writes while its view is not
known to match the server.

## Complete HTTP CRUD

The todo contract grows rename and delete operations. No migration is needed:
the existing table already stores every field.

| Operation | Request | Success | Client error |
| --- | --- | --- | --- |
| `GET /todos` | no body | `200` and ordered `Todo[]` | none |
| `POST /todos` | `{"title": string}` | `201` and active `Todo` | `422` invalid body |
| `PATCH /todos/{id}` | exactly one of `{"title": string}` or `{"completed": boolean}` | `200` and updated `Todo` | `404` absent; `422` invalid ID/body |
| `DELETE /todos/{id}` | no body | `204` with an empty body | `404` absent; `422` invalid ID |

PATCH remains an idempotent assignment, never a toggle command. Supplying
neither field, both fields, either field as `null`, a wrong type, or an extra
field returns `422`. Title updates apply the same canonical ECMAScript trim,
NUL and unpaired-surrogate rejection, and 1–120-code-point rule as creation.
Rename, completion, and reactivation preserve the internal identity and
creation order. DELETE physically removes one UUID-backed row; repeating it
returns exact `404 {"detail":"Todo not found."}`. Database outages keep the
exact `503 {"detail":"Database unavailable."}` behavior, and `GET /health`
stays database-independent.

The TypeScript client adds `setTodoTitle`, `deleteTodo`, and
`normalizeTodoTitle`. The last is the single client-side title implementation
used by the response guard and by create/rename validation. `deleteTodo`
accepts only an empty `204` and never parses a response body.

## One cache owner and explicit freshness

`App` creates one `QueryClient` for its lifetime and wraps `TodoScreen` in
`QueryClientProvider`. The query cache key is exactly `['todos']`, and its
cached `Todo[]` is the only remote collection in the client. All, Active, and
Completed remain render-time filters. Draft text, the selected filter, the open
editor or delete confirmation, focus signals, and error copy stay local React
state.

The provider uses an explicit policy:

| Setting | Value | Reason |
| --- | --- | --- |
| `staleTime` | `Infinity` | Data stays fresh until the app invalidates it |
| `gcTime` | `300_000` ms | An inactive list is reused for five minutes |
| `refetchOnMount` | `true` | An invalidated cache reconciles on remount |
| `refetchOnWindowFocus` / `refetchOnReconnect` | `false` | Recovery is explicit, identical on web and iOS |
| query `retry` | once, only for unavailable errors | A transient GET gets one second attempt |
| `retryDelay` | `500` ms | Visible in tests, gentle on the API |
| mutation `retry` | `false` | Repeating a write can duplicate or hide a result |

There is no polling and no persisted device cache. A fresh cache renders
immediately on remount; an invalidated cache refetches on remount.

## Invalidation, locks, and uncertain writes

Every mutation cancels the active `['todos']` GET first so an older response
cannot overwrite the result, and every mutation shares the key
`['todos', 'write']` so the screen can disable controls from one shared count.
On success the screen updates the cache from the authoritative response
(append create, replace rename/completion, remove delete), marks `['todos']`
stale, and awaits the confirming GET. Writes stay disabled until that GET
settles. If the confirming GET fails, the returned change stays visible with
**Could not refresh todos.**, and the stale cache keeps writes locked until a
**Refresh** succeeds. A failed refresh can never leave an Infinity-stale cache
looking fresh, because every cached **Refresh** invalidates before refetching.

An unavailable or invalid-data mutation result may hide a committed write, so
the screen rolls back any optimistic change, keeps prior rows and drafts,
shows **The result may be unknown. Refresh before making more changes.**, and
invalidates without refetching. A `404` shows **That todo no longer exists.
Refresh the list.** with the same lock. Only a successful fresh GET unlocks,
including across screen remounts. Create or rename `422` is a known rejection:
**Check the todo title and try again.**, draft and editor retained, cache left
fresh, correction permitted. Another client can change PostgreSQL without this
client knowing; **Refresh** is the explicit way to observe cross-client
changes. This phase does not claim real-time consistency.

## One optimistic mutation

Only completion/reactivation is optimistic: the desired Boolean, target UUID,
and prior list are already known, so the cache updates immediately and
restores one exact snapshot on any failure. Create is pessimistic because the
server assigns the UUID and canonical title, and a failed response can hide a
committed duplicate. Rename is pessimistic because the server canonicalizes
the title. Delete is pessimistic because removing the row before an uncertain
response would hide the item the user must reconcile.

## Deliberate non-goals

There is no offline mutation queue, no persisted device storage, no background
polling, no conflict versions or idempotency keys, no undo, and no automated
browser/iOS E2E (the later cross-platform E2E phase owns that). The screen
explains uncertainty and asks for an explicit refresh instead of pretending to
sync.

## Run focused checks

Start the disposable database once before API integration tests:

```bash
pnpm db:test:up
uv run --directory apps/api python -m pytest tests/test_persistence.py tests/test_todos.py tests/test_validation.py -v
pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts
pnpm --dir apps/mobile test --runInBand src/TodoScreen.test.tsx App.test.tsx
```

Run the complete repository gate after focused work:

```bash
pnpm quality
```

The lockfile pins exact `@tanstack/react-query` `5.102.8` with no other new
direct dependency. Mobile component tests construct a fresh `QueryClient` per
case with the production policy, use fake timers only for the single retry
case, and unref TanStack's minute-scale GC timeouts so they never hold Jest's
event loop open (production cache behavior is unchanged).

## Recover from an outage

Stop FastAPI during a refresh to observe retained rows with a write lock, then
restart it and select **Refresh** to recover. Stop it during a mutation to
observe the uncertain-result lock, remount `TodoScreen`, and confirm no write
is accepted until a fresh GET succeeds.

## Manual CRUD journey

Begin with the migrated development database. Use the recognizable duplicate
title `Phase 5 duplicate` so acceptance rows stay distinguishable.

1. On web, create a `Phase 5 duplicate`, rename it, optimistically
   complete and reactivate it, then cancel one delete and confirm another.
2. On iOS, **Refresh**, observe the same persisted rows, and perform the same
   edit/delete controls. Confirm web needs **Refresh** to see the
   second-client change.
3. Stop FastAPI after rows are cached: verify one GET retry, retained rows
   after refresh failure, and disabled writes. Restart and **Refresh** to
   unlock.
4. Stop FastAPI for a mutation, verify the uncertain copy, remount the screen,
   and confirm no write is accepted until a fresh GET succeeds.

## Phase 5 acceptance record

| Target | Date/runtime | CRUD | Cache/retry | Rollback | Outage/remount recovery |
| --- | --- | --- | --- | --- | --- |
| Web | — | ☐ | ☐ | ☐ | ☐ |
| iOS Simulator | — | ☐ | ☐ | ☐ | ☐ |
