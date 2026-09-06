# Phase 5 Complete CRUD and Resilient Server State Implementation Plan

**Status:** Locally accepted (2026-09-06)

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete persisted todo CRUD and give web/iOS one resilient,
explicitly consistent owner for cached server state.

**Architecture:** FastAPI extends its existing transactional repository with
atomic rename and delete operations. TanStack Query owns the only client todo
collection, retries safe GETs once, invalidates after writes, and applies
snapshot optimism only to completion; TodoScreen keeps only UI state.

**Tech Stack:** Python 3.14.7, FastAPI 0.141.1, Pydantic, PostgreSQL 18.6,
SQLAlchemy 2.x, Expo SDK 57.0.19, React 19.2.3, TypeScript 6.0.3, TanStack
Query 5.102.8, Jest 29.7.0, pytest.

**Spec:** `docs/superpowers/specs/2026-09-06-crud-server-state-design.md`

## Global constraints

- Start from current `main` at `8b5f45e`, which includes the post-Phase-4
  Pylance annotation fix; do not start from tag `phase-04-persistence`.
- Read the Expo SDK 57 documentation required by `apps/mobile/AGENTS.md` before
  mobile edits. Preserve web and iOS behavior, SafeAreaView, keyboard insets,
  create blur-then-focus, checkbox Space activation, and 44-point targets.
- Keep exact GET/POST and completed PATCH compatibility. PATCH accepts exactly
  one strict title or completed field; DELETE returns exact empty 204.
- Preserve UUIDs, duplicate titles, creation order, ECMAScript trim, NUL and
  surrogate rejection, the 1–120-code-point limit, route-owned transactions,
  PostgreSQL test guards, 503 mapping, health, and safe client errors.
- Add exact `@tanstack/react-query` `5.102.8`; add no other dependency or custom
  query scheduler. `['todos']` is the only todo key and its cached `Todo[]` is
  the only remote collection.
- Use `staleTime: Infinity`, `gcTime: 300_000`, `refetchOnMount: true`, no focus,
  reconnect, or interval refetch, one 500 ms retry only for unavailable queries,
  and no mutation retries or persistent cache.
- Cancel `['todos']` before every mutation. Await successful invalidation and
  refetch before permitting another write. Unknown and 404 mutation results must
  invalidate without refetch; stale state locks writes across screen remounts
  until a successful GET.
- Give every mutation key `['todos', 'write']`. Use shared mutation count plus
  the synchronous event guard across remounts, and keep cache settlement in
  `useMutation` options so unmount cannot drop reconciliation.
- Only completion/reactivation is optimistic, with one full-list snapshot and
  rollback on every error. Create, rename, and delete remain pessimistic.
- Render checkbox, Edit, and Delete as sibling controls; inline Save/Cancel and
  Confirm/Cancel controls may never be nested Pressables.
- Preserve the untracked root `AGENTS.md`. Sol owns architecture and review;
  Luna implementers must return scope or architecture concerns to Sol.

## File map

- `apps/api/app/main.py` and `apps/api/app/todo_repository.py`: exact-one-field
  PATCH, atomic rename/delete, transactions, 204/404/422/503, and DELETE CORS.
- `apps/api/tests/test_todos.py`, `test_persistence.py`, and `test_validation.py`:
  HTTP, repository, and title-model regression coverage; no migration changes.
- `apps/mobile/src/todos/todoApi.ts` and `.test.ts`: shared title normalization,
  rename transport, delete transport, runtime validation, and safe errors.
- `apps/mobile/package.json` and root `pnpm-lock.yaml`: exact TanStack Query pin.
- `apps/mobile/App.tsx` and `App.test.tsx`: one app-lifetime QueryClient provider.
- `apps/mobile/src/TodoScreen.tsx` and `.test.tsx`: query-cache ownership,
  mutation policy, resilient states, and complete accessible CRUD UI.
- `docs/guides/05-crud-server-state.md`, `README.md`, roadmap, this spec, and
  this plan: teaching, acceptance evidence, and checkpoint status.

### Task 1: Complete the persisted API and typed transport

**Files:** Modify `apps/api/app/main.py`, `apps/api/app/todo_repository.py`,
`apps/api/tests/test_todos.py`, `apps/api/tests/test_persistence.py`,
`apps/api/tests/test_validation.py`, `apps/mobile/src/todos/todoApi.ts`, and
`apps/mobile/src/todos/todoApi.test.ts`.

**Interfaces:** Preserve existing exports and add:

```python
class TodoUpdate(BaseModel):
    title: StrictStr | None = None
    completed: StrictBool | None = None

set_title(session: Session, public_id: UUID, title: str) -> TodoRow | None
delete_todo(session: Session, public_id: UUID) -> bool
```

```typescript
export function normalizeTodoTitle(input: string): string | null;
export function setTodoTitle(id: string, title: string,
  options?: TodoRequestOptions): Promise<Todo>;
export function deleteTodo(id: string,
  options?: TodoRequestOptions): Promise<void>;
```

- [ ] **Write focused failing repository, model, and HTTP tests.** Prove
  `set_title` and `delete_todo` use caller-owned transactions, return missing
  results, persist across a fresh session, and do not reorder survivors. Prove
  PATCH canonical title success and exact-one-field `422` for `{}`, both fields,
  `null`, wrong types, and extras. Prove DELETE returns empty `204`, a repeated
  delete returns exact `404`, unavailable PostgreSQL returns exact `503`, OpenAPI
  publishes `TodoUpdate` plus DELETE, and browser preflight allows DELETE.

- [ ] **Run the red API checks.** Run `pnpm db:test:up`, then
  `uv run --directory apps/api python -m pytest tests/test_persistence.py tests/test_todos.py tests/test_validation.py -v`.
  Expect missing rename/delete repository and route contracts.

- [ ] **Implement the minimum atomic operations and routes.** Extract the
  existing title canonicalizer so `TodoCreate` and `TodoUpdate` share it. Use a
  model-level validator to require exactly one supplied, non-null field. Keep
  the existing completion repository operation; add one
  `update(...).returning(TodoRow)` for title and one
  `delete(...).returning(TodoRow.public_id)` for deletion. Dispatch PATCH to the
  matching concrete function inside `with session.begin()`. DELETE commits
  before returning `Response(status_code=204)`. Add DELETE to CORS and to the
  existing database-unavailable boundary. Do not add a migration, service, or
  generic repository interface.

- [ ] **Write focused failing client tests.** Assert rename sends exact PATCH
  JSON and validates the returned Todo. Assert delete sends no body, accepts only
  empty 204 without calling `json()`, and maps 404, 503, timeout, and unexpected
  status to existing safe categories; delete unavailability is exactly **Could
  not delete todo.** Move title trim, code-point, NUL, and surrogate cases to
  exported `normalizeTodoTitle`; prove the response guard uses it. Task 2 uses
  the same export for create and rename input.

- [ ] **Extend the existing private request helper.** Add DELETE and a no-content
  success path without introducing a second transport helper. Keep five-second
  timeout, caller cancellation, URL validation, listener/timer cleanup, exact
  response guards, and non-disclosure of server/exception text. `setTodoTitle`
  uses the update operation messages; `deleteTodo` uses exact **Could not delete
  todo.** and maps 404 to `not-found`.

- [ ] **Verify and commit Task 1.** Run the API command above,
  `pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts`,
  `pnpm lint:api`, `pnpm lint:mobile`, `pnpm typecheck`, and `git diff --check`.
  Stage only Task 1 files and commit `feat: complete persisted todo API`.

### Task 2: Replace screen-owned server state and finish the CRUD UI

**Files:** Modify `apps/mobile/package.json`, `pnpm-lock.yaml`,
`apps/mobile/App.tsx`, `apps/mobile/App.test.tsx`,
`apps/mobile/src/TodoScreen.tsx`, and `apps/mobile/src/TodoScreen.test.tsx`.

**Interfaces:** `App` constructs one `QueryClient` per app lifetime and provides
it. `TodoScreenApi` becomes:

```typescript
export type TodoScreenApi = {
  list: (options: { signal: AbortSignal }) => Promise<Todo[]>;
  create: (title: string) => Promise<Todo>;
  rename: (id: string, title: string) => Promise<Todo>;
  setCompleted: (id: string, completed: boolean) => Promise<Todo>;
  remove: (id: string) => Promise<void>;
};
```

- [ ] **Pin the query dependency and write the failing provider/cache tests.**
  Install exact `@tanstack/react-query@5.102.8`. Update App tests to prove the
  default screen receives a provider and one initial GET. In TodoScreen tests,
  wrap each case in a fresh QueryClient. Prove production defaults: an
  unavailable GET retries exactly once after 500 ms, invalid-data does not retry,
  fresh cached rows render on a screen remount without GET, and invalidated rows
  refetch on remount. Cached manual Refresh invalidates before fetching; failure
  remains invalidated across remount and success alone makes it fresh. Use fake
  timers only for the retry case.

- [ ] **Write failing resilient-mutation tests.** Group tests around behavior,
  not library internals: successful create/rename/delete remains visually
  unchanged until its response, updates from the response/204, then starts one
  confirming GET and stays write-disabled until it settles. Completion changes
  immediately, uses the requested Boolean, and restores the exact prior list on
  any error. An unknown or 404 mutation must restore/preserve rows, invalidate
  without an immediate GET, keep the draft or edit text, show exact safe copy,
  and remain locked after TodoScreen remount and failed GET; one successful
  Refresh replaces rows and unlocks. A failed confirming GET after a successful
  mutation keeps the returned change visible with **Could not refresh todos.**
  Remount during a deferred mutation and prove its shared mutation count blocks
  a new write; settle it after unmount and prove hook-level callbacks still
  reconcile or invalidate the cache.

- [ ] **Write failing interaction and accessibility tests.** Prove one
  synchronous gate across rapid Add/submit, checkbox press/Space, Save, and
  Confirm delete events. Prove inline edit Save/Cancel, inline delete
  Confirm/Cancel, one open row action at a time, pessimistic edit/delete, local
  normalization including NUL, filters during cached error states, contextual
  empty text, button/checkbox roles and disabled state, sibling actionable
  controls, 44-point targets, and no lost Phase 3 create blur-before-disable or
  post-render success focus.

- [ ] **Create the app-lifetime QueryClient.** In `App.tsx`, use lazy React state
  so one QueryClient survives screen rerenders. Configure exact global values
  from the spec. The retry predicate is
  `failureCount < 1 && error instanceof TodoApiError && error.kind === "unavailable"`;
  mutations set `retry: false`. Wrap the existing TodoScreen in
  `QueryClientProvider`. Add no React Native focus or connectivity adapter.

- [ ] **Replace the manual scheduler with direct TanStack Query calls.** Remove
  local `todos`, load-state, mounted, attempt, active-controller, loaded, and
  write-lock ownership. Read and filter `query.data ?? []`. Derive initial load,
  cached refresh, initial error, refetch error, and write-disabled state from the
  query plus mutation state; a stale query always disables writes. Keep only one
  synchronous busy ref for the pre-render event gap. Give every mutation
  `mutationKey: ['todos', 'write']`; derive pending state with `useIsMutating`
  and reject events while `queryClient.isMutating` is nonzero, including after a
  screen remount. Pass the query function's `signal` to `api.list`; do not build
  wrapper hooks or another scheduler.

- [ ] **Implement the exact mutation policy.** Before each write, set the busy
  ref and await `cancelQueries({queryKey: ['todos']})`. On create/rename/delete
  success, append/replace/remove in `setQueryData`, then invalidate and await the
  active GET. For completion, snapshot the full list and change only the target
  Boolean before transport; restore the snapshot on every error, or replace the
  row with the response on success. On success, invalidate and await refetch. On
  unknown or 404 error, perform rollback first, then
  `invalidateQueries({queryKey: ['todos'], refetchType: 'none'})`; do not call
  `setQueryData` afterward because that would clear invalidation. A successful
  fresh GET is the only reconciliation unlock. Validation leaves the cache fresh.
  Put cache callbacks in each hook's `useMutation` options, never per-call
  `mutate` callbacks. A cached Refresh first invalidates with
  `refetchType: 'none'`, then refetches once, so failure cannot make a stale
  Infinity-stale-time cache appear fresh.

- [ ] **Render inline CRUD controls and verify.** Replace the whole-row
  Pressable with a row View and sibling checkbox/Edit/Delete controls. Keep one
  central editing ID/draft and one confirming ID. Save uses
  `normalizeTodoTitle`; Cancel performs no request. Delete asks **Delete
  “{title}”?** before **Confirm delete**. Preserve filters, safe area, scrolling,
  keyboard behavior, duplicates, create blur/focus, web Space handling, roles,
  labels, and minimum targets. Delete obsolete tests for manual attempt IDs and
  cancellation guards after equivalent query-cache behavior is covered. Run
  `pnpm --dir apps/mobile test --runInBand src/TodoScreen.test.tsx App.test.tsx`,
  `pnpm test:mobile`, `pnpm lint:mobile`, `pnpm typecheck`, `pnpm build:web`, and
  `git diff --check`. Commit `feat: add resilient complete CRUD experience`.

### Task 3: Teach, accept, integrate, and checkpoint Phase 5

**Files:** Create `docs/guides/05-crud-server-state.md`; modify `README.md`,
`docs/curriculum-roadmap.md`, this spec, and this plan.

**Interfaces:** Produce the Phase 5 guide and observed web/iOS acceptance record;
make no source contract changes during this task.

- [ ] **Write Guide 05 and update entry points.** Explain complete HTTP CRUD,
  title/delete semantics, the one in-memory query cache, Infinity freshness,
  five-minute inactive lifetime, one GET-only retry, explicit Refresh,
  success invalidation, optimistic completion rollback, pessimistic other
  writes, stale-cache write lock, remount reconciliation, and why offline queue,
  persistence, and real-time sync are absent. Advance README to Phase 5 and Guide
  05; mark only this roadmap spec gate approved. Start an unchecked table for
  web and the reference iOS Simulator covering CRUD, cache/retry, rollback, and
  outage/remount recovery.

- [ ] **Run automated acceptance.** Start the guarded test database with
  `pnpm db:test:up`; run the focused API and mobile commands from Tasks 1–2,
  then `pnpm quality` and `git diff --check`. Confirm the lockfile has exact
  TanStack Query 5.102.8 and no other new direct dependency.

- [ ] **Perform the two-target manual journey.** Run `pnpm db:up`,
  `pnpm db:migrate`, `pnpm dev:api`, and `pnpm dev:mobile`. On web create and
  rename a duplicate, observe immediate completion/reactivation, cancel one
  delete and confirm another, and verify order. On iOS Refresh, observe the
  persisted result, edit/delete with the same inline controls, and confirm web
  needs Refresh to see the second-client change. Stop FastAPI after rows are
  cached: verify one GET retry, retained rows after refresh failure, and disabled
  writes. Restart and Refresh to unlock. Stop it for a mutation, verify uncertain
  copy, remount the screen, and confirm no write is accepted until a fresh GET
  succeeds. Record only observed date/runtime/results.

- [ ] **Finalize, review, and checkpoint.** Change spec/plan status to locally
  accepted with the observed date, run Markdown/link lint and `pnpm quality`, and
  commit `docs: add CRUD server-state guide`. Obtain final whole-branch Sol review
  and resolve every finding. Integrate reviewed commits, wait for GitHub quality
  CI to pass on that exact integrated commit, then create annotated tag
  `phase-05-crud-server-state`; never tag pending or failing CI.

## Spec coverage check

- Rename/delete HTTP, persistence, validation, OpenAPI, CORS, and transport:
  Task 1.
- Single cache owner, exact retry/freshness/invalidation, and remount lock:
  Task 2.
- Optimistic completion rollback and pessimistic create/rename/delete: Task 2.
- Loading, empty, cached refresh/error, retry, uncertainty, UI, and accessibility:
  Task 2.
- Guide, web/iOS acceptance, review, integration, CI, and checkpoint: Task 3.

Authentication, persisted offline behavior, real-time sync, and automated E2E
remain in their roadmap phases.
