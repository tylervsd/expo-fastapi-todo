# Phase 5 Complete CRUD and Resilient Server State Design

**Status:** Locally accepted (2026-09-06)

## Outcome

Phase 5 completes the persisted todo workflow. On web and iOS, users can create,
rename, complete, reactivate, and delete todos. The screen keeps useful cached
rows visible during refresh failures, explains when a write may be uncertain,
and accepts another write only after its view is known to match a successful
fresh GET.

The phase teaches one established server-state cache, explicit query retry and
invalidation policy, one justified optimistic mutation with rollback, and the
difference between local UI state and server-owned data.

## Scope

This phase adds title updates and deletion to the existing FastAPI and typed
client contracts. It replaces TodoScreen's hand-written request scheduler and
local todo array with TanStack Query 5.102.8. Draft text, the selected filter,
the open editor or delete confirmation, focus signals, and visible safe error
copy remain local React state.

It does not add authentication, users, pagination, sorting, timestamps, soft
deletion, bulk actions, undo, an offline queue, persisted device storage,
background polling, push synchronization, conflict versions, idempotency keys,
generated clients, a generic data layer, or automated browser/iOS E2E. The later cross-platform E2E phase
still owns automated end-to-end coverage. There is no schema migration because the existing
table already stores every field required by complete CRUD.

## Chosen architecture

Add the exact `@tanstack/react-query` version `5.102.8`, the current stable npm
release when this spec was written. `App` creates one `QueryClient` for its
lifetime and wraps `TodoScreen` in `QueryClientProvider`. `TodoScreen` uses the
existing typed todo API directly through `useQuery` and `useMutation`; no custom
cache, repository hook, event bus, or second todo collection is added.

The query cache is the only owner of `Todo[]`. Its key is exactly `['todos']`.
The API and cache always store the full creation-ordered collection; All,
Active, and Completed remain render-time filters. The screen may inject a
`TodoScreenApi` in component tests, but production still uses the direct client
functions.

The provider uses this explicit query policy:

| Setting | Value | Reason |
| --- | --- | --- |
| `staleTime` | `Infinity` | Data stays fresh until this app explicitly invalidates it |
| `gcTime` | `300_000` ms | An inactive in-memory list can be reused for five minutes |
| `refetchOnMount` | `true` | An invalidated cache reconciles when the screen remounts |
| `refetchOnWindowFocus` | `false` | Web and iOS have the same taught behavior without platform adapters |
| `refetchOnReconnect` | `false` | Recovery is explicit and does not require native connectivity plumbing |
| query `retry` | one retry only for `TodoApiError('unavailable')` | A transient GET gets one safe second attempt; contract errors do not loop |
| `retryDelay` | `500` ms | The retry is visible in tests and does not immediately hammer the API |
| mutation `retry` | `false` | Repeating a write can duplicate or conceal an uncertain result |

There is no polling or persistent cache. A fresh cache can render immediately
when TodoScreen remounts under the same provider. A full App remount creates a
new in-memory client and loads again. TanStack Query supplies query cancellation,
request deduplication, retry state, inactive-cache lifetime, and stale-result
protection instead of preserving the existing attempt counters and mounted
guards.

## HTTP and persistence contracts

The response remains exactly:

```json
{"id":"6fc33b84-16a8-4d8e-ae94-fc50bb457d72","title":"Buy milk","completed":false}
```

The full contract becomes:

| Operation | Request | Success | Client error |
| --- | --- | --- | --- |
| `GET /todos` | no body | `200` and ordered `Todo[]` | none |
| `POST /todos` | `{"title": string}` | `201` and active `Todo` | `422` invalid body |
| `PATCH /todos/{id}` | exactly one of `{"title": string}` or `{"completed": boolean}` | `200` and updated `Todo` | `404` absent; `422` invalid ID/body |
| `DELETE /todos/{id}` | no body | `204` and no response body | `404` absent; `422` invalid ID |

PATCH remains an idempotent assignment, not a toggle command. Supplying neither
field, both fields, either field as `null`, a wrong type, or an extra field is
`422`. Title updates apply the existing canonical ECMAScript trim, NUL and
unpaired-surrogate rejection, and 1–120-code-point rule. Rename, completion,
and reactivation preserve the internal identity and creation order. DELETE
physically removes one UUID-backed row; repeating it returns exact
`404 {"detail":"Todo not found."}`.

`TodoUpdate` replaces `TodoCompletedUpdate` in generated OpenAPI. It reuses one
module-level title canonicalizer with `TodoCreate`. The repository keeps its
concrete functions and adds only:

```python
set_title(session: Session, public_id: UUID, title: str) -> TodoRow | None
delete_todo(session: Session, public_id: UUID) -> bool
```

Both execute one atomic SQL statement. `set_title` uses `UPDATE ... RETURNING`;
`delete_todo` uses `DELETE ... RETURNING`. Routes own the transaction and commit
before returning `200` or `204`. Database operational and pool timeout failures
keep the exact `503 {"detail":"Database unavailable."}` behavior. CORS adds
`DELETE`; health and the database schema remain unchanged.

The TypeScript client adds:

```typescript
setTodoTitle(id: string, title: string,
  options?: TodoRequestOptions): Promise<Todo>;
deleteTodo(id: string, options?: TodoRequestOptions): Promise<void>;
normalizeTodoTitle(input: string): string | null;
```

`deleteTodo` accepts only exact `204` and never parses a response body. PATCH and
DELETE `404` map to the existing `not-found` category. A delete transport
failure, 503, or unexpected status uses exact safe copy **Could not delete
todo.** Other operations and invalid success data retain safe operation-specific
errors. `normalizeTodoTitle` becomes the one client-side implementation used by
the response guard, create, and rename validation, including NUL and surrogate
rejection.

## Cache, invalidation, and consistency

Before every mutation, cancel the active `['todos']` GET so an older response
cannot overwrite the mutation result. Every mutation uses the shared key
`['todos', 'write']`. `useIsMutating` disables rendered controls, while
`queryClient.isMutating` and a synchronous busy ref close the rapid-event and
screen-remount gaps before React renders pending state. TanStack Query owns the
remaining request lifecycle.

After a successful mutation, update the cached collection from the authoritative
response: append create, replace rename/completion, or remove delete. Then mark
`['todos']` stale and await its active refetch. The mutation remains pending and
writes stay disabled until that GET settles. A successful GET replaces the
whole cache and makes it fresh. If the mutation succeeded but the confirming GET
fails, the returned change remains visible, **Could not refresh todos.** appears,
and the stale query keeps writes locked until Refresh succeeds.

Cache mutation, rollback, and invalidation callbacks live in the options passed
to `useMutation`, not in callbacks passed to an individual `mutate` call. They
therefore finish cache reconciliation if the initiating screen unmounts.

An unavailable or invalid-data mutation result may conceal a committed write.
Rollback any optimistic display change, preserve the prior rows and drafts, show
**The result may be unknown. Refresh before making more changes.**, and invalidate
without refetching. A `404` also rolls back, shows **That todo no longer exists.
Refresh the list.**, and invalidates without refetching. In both cases the query's
stale state, rather than a screen-only Boolean, keeps writes locked. Remounting
TodoScreen under the same provider immediately refetches the invalidated cache;
a failed refetch retains the rows and lock, while a successful fresh GET is the
only event that clears reconciliation. Every user Refresh with cached data first
invalidates with `refetchType: 'none'` and then starts one refetch. A failed GET
therefore cannot leave an Infinity-stale-time cache looking fresh. Initial load
and Retry without cached data use the query's already-stale state.

Create or rename `422` is a known rejection: show **Check the todo title and try
again.**, retain the draft/editor, leave the cache fresh, and permit correction.
Queries retry; mutations never do. Another client can change PostgreSQL without
this client knowing, so users still select Refresh to observe cross-client
changes. This phase does not claim real-time consistency.

## Optimistic-update policy

Only completion/reactivation is optimistic. Its desired Boolean, target UUID,
and prior full list are already known, so the cache can update immediately and
restore one exact snapshot on failure. The mutation cancels an active list GET,
captures the current collection, changes only `completed`, and returns the
snapshot. Any failure restores the snapshot before applying the invalidation
and error policy above. Success replaces the optimistic row with the server row
before invalidation.

Create is pessimistic because the server assigns its UUID and canonical title,
and a failed response can hide a committed duplicate. Rename remains pessimistic
because the server canonicalizes the title and is authoritative for validation.
Delete remains pessimistic because removing the row before an uncertain response
would hide the exact item a user must reconcile. This one optimistic mutation is
enough to teach rollback without inventing temporary IDs, tombstones, or an undo
protocol.

## Screen behavior

With no cached data, the screen displays **Loading todos…** through the original
GET and its one automatic retry. Exhaustion displays **Could not load todos.**
and Retry, without an empty message. Retry starts one new query cycle, which may
again make at most two GET attempts. With cached data, a refetch displays
**Refreshing todos…** and keeps rows and filters visible. A failed refetch shows
**Could not refresh todos.**, preserves rows, and disables writes until another
Refresh succeeds. Filters remain usable in every cached-data state.

Each displayed row becomes a plain `View` containing sibling controls; no
Pressable is nested inside another Pressable:

- A checkbox preserves checked semantics, 44-point target, press behavior, and
  web Space activation with default prevention.
- **Edit** opens one inline editor initialized with the canonical title. **Save
  changes** validates and sends PATCH; **Cancel edit** restores the row. Failure
  retains the edit draft. Only one row can be edited or confirmed at a time.
- **Delete** opens inline text **Delete “{title}”?** with **Confirm delete** and
  **Cancel delete** sibling buttons. Confirmation is required once; success
  removes the row after the 204 response and cache update.

Create remains pessimistic and keeps its current iOS focus fix: blur before the
pending request disables the input, then clear and focus only after the created
row is committed to the rendered cache. All new controls use explicit button or
checkbox roles, accessible labels, disabled state, and at least 44-point targets.
Safe area, scrolling, keyboard insets, filters, empty messages, duplicate titles,
and canonical returned titles remain unchanged.

## Deterministic testing

PostgreSQL-backed repository and API tests prove title update, physical delete,
order preservation, transaction visibility, rollback, exact 204/404/422/503,
OpenAPI, and DELETE CORS. They reuse the existing guarded test database and add
no migration test because the schema does not change.

Injected-fetch client tests prove rename and delete methods, URLs, JSON, exact
success statuses, no 204 body parse, safe 404/unavailable mapping, and shared
title normalization. Existing timeout, cancellation, response validation, and
cleanup coverage remains.

Component tests use a fresh QueryClient and deferred API promises. They prove
the single safe GET retry, fresh-cache reuse, success invalidation/refetch,
stale-row display and write lock, remount after an uncertain mutation, successful
fresh-GET unlock, remount during a pending mutation, hook-level cache settlement,
the one optimistic completion plus rollback, pessimistic
create/rename/delete, rapid-event gating, inline confirmation, exact errors,
focus, web Space behavior, accessibility, filters, and empty states. Obsolete
assertions about the removed attempt-counter implementation are deleted rather
than recreated around TanStack Query.

## Documentation and acceptance

Guide 05 explains full CRUD, the single cache owner, freshness and garbage
collection, safe GET-only retry, mutation invalidation, optimistic completion,
uncertain-write recovery, and the explicit lack of offline or real-time sync.
README advances to Phase 5 and the roadmap records this spec as approved only
after approval.

Manual acceptance begins with the existing migrated development database. On
web, create, rename, optimistically complete/reactivate, and confirm then cancel
and confirm deletion. On iOS, Refresh sees the same persisted rows and performs
the same edit/delete controls. Verify a second client changes only appear after
Refresh. Stop FastAPI during a refresh to observe retained rows and a write lock;
restart it and Refresh to recover. Stop it during a mutation to observe the
uncertain-result lock; remount TodoScreen and prove a fresh GET is still required
before another write. Record actual web and reference-Simulator runtimes.

Phase 5 completes after focused and full checks pass, both-target acceptance is
recorded, Sol whole-branch review has no unresolved findings, the reviewed work
is integrated, CI passes on that exact commit, and only then the commit is tagged
`phase-05-crud-server-state`.

## Alternatives considered

A custom `useTodos` cache would duplicate cancellation, stale tracking, retries,
deduplication, garbage collection, and mutation coordination already supplied by
one focused dependency. Keeping the current local todo array beside TanStack
Query would create two authorities and reconciliation bugs. A persisted offline
cache and mutation queue would require connectivity detection, durable intent,
idempotency, and conflict policy beyond this phase. The in-memory TanStack Query
cache with one optimistic Boolean update is the smallest design that teaches all
roadmap goals.

## Sources

- [TanStack Query React Native example](https://tanstack.com/query/latest/docs/framework/react/examples/react-native)
- [TanStack Query important defaults](https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults)
- [TanStack Query retries](https://tanstack.com/query/latest/docs/framework/react/guides/query-retries)
- [TanStack Query cancellation](https://tanstack.com/query/latest/docs/framework/react/guides/query-cancellation)
- [TanStack Query invalidation](https://tanstack.com/query/latest/docs/framework/react/guides/query-invalidation)
- [TanStack Query optimistic updates](https://tanstack.com/query/latest/docs/framework/react/guides/optimistic-updates)
- [npm release for `@tanstack/react-query`](https://www.npmjs.com/package/@tanstack/react-query)
