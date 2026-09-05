# Phase 3 API Contract and Vertical Slice Implementation Plan

**Status:** Implemented and locally accepted on 2026-09-05; release checkpoint pending

**Confirmed decision:** Keep completion and reactivation working through
`PATCH /todos/{id}`, as confirmed by the user on 2026-09-05.

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Expo's todo journey to a validated, process-local FastAPI
contract for list, create, and reversible completion.

**Architecture:** A FastAPI app factory closes over an ordered in-memory
collection and publishes its generated OpenAPI schema. A narrow handwritten
TypeScript client runtime-checks JSON; `TodoScreen` owns request state,
cancellation, reconciliation, and its existing local filters.

**Tech Stack:** Python 3.14, FastAPI 0.141.1, Pydantic, Expo SDK 57.0.19,
React 19.2.3, TypeScript 6.0.3, Jest 29.7.0, pytest.

**Spec:** `docs/superpowers/specs/2026-09-05-api-vertical-slice-design.md`

## Global constraints

- Start from `phase-02-local-todo`. Preserve Phase 1 health behavior and Phase
  2 safe-area, scrolling, iOS keyboard, web Space-key, filters, empty states,
  and accessibility behavior.
- Read the Expo SDK 57 docs required by `apps/mobile/AGENTS.md` before mobile
  edits. Add no dependency, database, auth, edit/delete, cache, storage/service
  layer, generator, optimistic mutation, or automatic mutation retry.
- Implement exactly GET/POST `/todos` and completed-only PATCH `/todos/{id}`.
  PATCH receives a strict desired Boolean, never a toggle instruction.
- Titles use a strict string, ECMAScript trim, no unpaired surrogate, and 1–120
  Unicode code points. The server canonicalizes and the client matches it.
- One app instance owns ordered state. Use standard-library random UUIDs.
- CORS permits `http://localhost:8081`, GET/POST/PATCH, explicit `Content-Type`,
  standard safelisted headers, and no credentials.
- Preserve the untracked root `AGENTS.md`. Sol owns architecture/review; Luna
  workers implement these interfaces and return scope questions to Sol.

## File map

- `apps/api/app/main.py`, `apps/api/tests/test_todos.py`, and `test_health.py`:
  app factory, models/routes, fresh-app contracts, OpenAPI, CORS regressions.
- `apps/mobile/src/todos/todoApi.ts` and `.test.ts`: typed operations, runtime
  validation, timeout/cancellation, and injected-fetch tests.
- `apps/mobile/src/TodoScreen.tsx`, `.test.tsx`, and `App.test.tsx`: remote
  state, one-operation gate, reconciliation, and preserved UI behavior.
- `docs/guides/03-api-vertical-slice.md`, `README.md`, and roadmap: teaching,
  observed acceptance, and checkpoint metadata.

### Task 1: Publish the FastAPI todo contract

**Files:** Modify `apps/api/app/main.py`, `apps/api/tests/test_health.py`; create
`apps/api/tests/test_todos.py`.

**Produces:** `Todo`, `TodoCreate`, `TodoCompletedUpdate`,
`create_app() -> FastAPI`, and exported `app = create_app()`.

- [x] **Write failing fresh-app tests.** A fixture creates
  `TestClient(create_app())`. Assert initial `200 []`; separate-app isolation;
  POST `201` canonical active todo with parseable UUID; duplicates in insertion
  order with distinct IDs; 120 emoji accepted and 121 rejected; and `422` for
  empty/non-string/missing/extra/surrogate input. PATCH true, repeated true, then
  false must return the canonical row without reordering; assert `0`, `1`,
  `"true"`, and `"false"` each return `422`. Malformed UUID/body is `422`, and
  an absent valid UUID is exactly `404 {"detail":"Todo not found."}`. Assert
  OpenAPI path methods/schema references, GET health preflight, POST/PATCH
  origin/method/`Content-Type` preflight, and no allow-origin for an unlisted
  origin. Change health tests to use a fresh factory.

- [x] **Run the red test.** Run
  `uv run --directory apps/api python -m pytest tests/test_todos.py tests/test_health.py -v`;
  expect failure because the factory and todo contract do not exist.

- [x] **Implement the minimum direct routes.** Request models use strict field
  types and `extra="forbid"`; a title validator applies the explicit ECMAScript
  trim set and surrogate check before the 1–120 constraint. Use `StrictBool` for
  PATCH. `create_app` closes over one insertion-ordered dict. Direct `async def`
  handlers list, create with `uuid4`, and replace only `completed`; no storage
  abstraction. Decorators set POST `201`, response models, and CORS. Let FastAPI
  produce `/openapi.json`, `/docs`, and `422`, following
  [request bodies](https://fastapi.tiangolo.com/tutorial/body/),
  [validators](https://pydantic.dev/docs/validation/latest/concepts/validators/),
  and [CORS](https://fastapi.tiangolo.com/tutorial/cors/).

- [x] **Verify and commit.** Run the focused pytest command above, then
  `pnpm lint:api` and `git diff --check`. Stage the three listed API files and
  commit `feat: add in-memory todo API contract`.

### Task 2: Add the runtime-validated TypeScript client

**Files:** Create `apps/mobile/src/todos/todoApi.ts` and `todoApi.test.ts`.

**Produces:** `Todo`, `TodoApiError` with kind `validation | not-found |
unavailable | invalid-data`, `TodoRequestOptions` with optional API URL, timeout,
signal, and injected fetch, plus these functions:

```typescript
listTodos(options?: TodoRequestOptions): Promise<Todo[]>;
createTodo(title: string, options?: TodoRequestOptions): Promise<Todo>;
setTodoCompleted(id: string, completed: boolean,
  options?: TodoRequestOptions): Promise<Todo>;
```

- [x] **Write failing injected-fetch tests.** Assert URL, method, JSON header/body,
  statuses, and result. Exact runtime guards reject malformed arrays, extra or
  wrong-type todo keys, UUID/title violations, invalid JSON, and wrong success
  status. Assert `422 -> validation` with **Check the todo title and try again.**,
  PATCH `404 -> not-found` with **That todo no longer exists. Refresh the list.**,
  transport/other status `-> unavailable`, and malformed success `-> invalid-data`.
  The latter two use safe operation-specific copy. Fake timers prove five-second
  timeout includes body parsing and aborts transport. Caller abort must reject an
  `AbortError`, not `TodoApiError`; already-aborted input never fetches, and all
  paths remove timers/listeners.

- [x] **Run the red test.** Run
  `pnpm --dir apps/mobile test --runInBand src/todos/todoApi.test.ts`; expect a
  missing-module failure.

- [x] **Implement one private JSON request helper and three exports.** Follow
  `health/checkHealth.ts` for validated base URL, relayed abort, timeout, and
  cleanup, while leaving health source unchanged. Keep the helper inside the
  todo module. Validate exact response keys, UUID, canonical trim, code-point
  length, and Boolean completion. Never expose exception/server prose.

- [x] **Verify and commit.** Run the focused Jest command above,
  `pnpm lint:mobile`, `pnpm typecheck`, and `git diff --check`. Stage
  `apps/mobile/src/todos` and commit `feat: add typed todo API client`.

### Task 3: Drive TodoScreen from the server

**Files:** Modify `apps/mobile/src/TodoScreen.tsx`, `TodoScreen.test.tsx`, and
`apps/mobile/App.test.tsx`.

**Consumes:** An injected API with `list({signal})`, `create(title, {signal})`,
and `setCompleted(id, completed, {signal})`; defaults call Task 2 exports.

- [x] **Rewrite failing tests with deferred API promises.** Retain Phase 2
  validation, duplicates, filters, keyboard/Space, empty states, checkbox,
  selected-state, and alert assertions. Add initial **Loading todos…** with no
  writes, one GET, success, initial **Could not load todos.**/Retry without empty
  copy, and always-available Refresh after success. Cover POST and desired-Boolean
  PATCH with no optimistic change then canonical merge; a synchronous rapid-event
  gate; remote controls disabled while filters work; failed refresh preserving
  rows; exact validation/not-found copy; and unknown create/update copy
  **The result may be unknown. Refresh before making more changes.** retaining
  draft/list and disabling writes until successful Refresh. Refresh success keeps
  the draft and current filter; remount resets All. Suppress stale/AbortError
  results and abort on unmount. Mock Task 2 in `App.test.tsx`.

- [x] **Run the red tests.** Run
  `pnpm --dir apps/mobile test --runInBand src/TodoScreen.test.tsx App.test.tsx`;
  expect failure because the screen still owns mount-local mutations.

- [x] **Implement request state and reconciliation.** Keep one todo array and
  render-derived filters. A synchronous busy ref plus operation state accepts
  one remote action before rerender; attempt identity and AbortController block
  stale/unmounted updates. GET replaces, POST appends its canonical row, and
  PATCH replaces its row only after success. Unknown mutation locks writes until
  Refresh GET succeeds; retained create draft remains afterward, so the learner
  must inspect the refreshed list before resubmitting because duplication remains
  possible. Disable draft during create so success cannot erase newer text.
  Preserve SafeAreaView, keyboard ScrollView props, 44-point targets, ARIA state,
  and Space behavior.

- [x] **Verify and commit.** Run the focused Jest command above, then
  `pnpm test:mobile`, `pnpm lint:mobile`, `pnpm typecheck`, `pnpm build:web`, and
  `git diff --check`. Stage the three listed files and commit
  `feat: connect todo screen to API`.

### Task 4: Teach and accept the vertical slice

**Files:** Create `docs/guides/03-api-vertical-slice.md`; modify `README.md` and
`docs/curriculum-roadmap.md`.

- [x] **Write guide and entry points.** Explain endpoints/statuses, title rules,
  app-local lifetime, `/docs`, handwritten type plus runtime guard, request
  states/cancellation, unknown-write reconciliation and possible duplicate after
  manual resubmit, CORS, two-terminal startup, focused checks, and `pnpm quality`.
  Include the spec's exact journey and an unchecked web/iOS table for actual
  date/runtime, shared create/toggle, filter refresh versus All-on-remount,
  network recovery, and restart reset. Advance README to Phase 3 and Guide 03;
  mark only this roadmap spec gate complete.

- [x] **Lint, perform, and record manual acceptance.** Run `pnpm lint:markdown`
  and `pnpm lint:links`, then run `pnpm dev:api` and `pnpm dev:mobile` in
  separate terminals. Inspect `/docs`; execute the journey on localhost web and
  the reference iPhone 17 Pro Simulator. Stop the API before the failure case.
  Record only observed results, restarting the API for the final empty proof.

- [x] **Final gate and documentation commit.** Run `pnpm quality`,
  `git diff --check`, and `git status --short`. Stage the three listed docs and
  commit `docs: add API vertical slice guide`.

- [ ] **Review and checkpoint.** Obtain final whole-branch Sol review. After
  reviewed integration and passing CI, tag `phase-03-api-vertical-slice` on the
  integrated commit, never before.

## Spec coverage check

- Server contract/lifetime/OpenAPI/errors/CORS: Task 1.
- Typed transport/runtime validation/timeout/abort: Task 2.
- Loading/mutations/filter/gate/reconciliation: Task 3.
- Guide/two-target acceptance/quality/checkpoint: Task 4.

Persistence and richer server-state behavior remain in their roadmap phases.
