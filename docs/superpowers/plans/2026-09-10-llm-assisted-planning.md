# LLM-Assisted Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add recoverable OpenRouter todo suggestions to the existing guided workflow while keeping every generated title editable and creating todos only after explicit confirmation.

**Architecture:** Store suggestion requests beside, rather than inside, Phase 9 workflow snapshots. Reserve each request in a short transaction, call a thin asynchronous OpenRouter client without database locks, and publish only the newest owner/revision/step-matching result; the existing `submit_tasks` and `confirm` actions remain the persistence and creation boundaries.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, httpx, SQLAlchemy/PostgreSQL/Alembic, React Native/Expo SDK 57, TanStack Query, Jest/pytest.

**Spec:** `docs/superpowers/specs/2026-09-10-llm-assisted-planning-design.md`

## Global Constraints

- Keep workflow definition version 1, existing workflow envelopes/templates, quick add, and `/todos` unchanged.
- Live calls require `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`; there is no default model and secrets never enter Expo.
- Send the canonical goal only; accept 2–10 canonical titles, 16 KiB maximum response, 400 requested tokens, hard 30-second coroutine deadline, and no automatic paid retry.
- Use OpenRouter JSON Schema structured output with `strict: true` and `provider.require_parameters: true`, then validate again in Python, including HTTP-200 error bodies.
- Preserve local drafts against late results using owner, session epoch, workflow, revision, step, request identity, and edit-counter checks.
- Normal CI uses an injected fake and makes no network or paid provider calls. Read Expo SDK 57 documentation before mobile implementation.

## File map

- `apps/api/app/suggestion_provider.py`: environment loading, exact OpenRouter request, bounded response parsing.
- `apps/api/app/workflow_repository.py`: suggestion-request row and strict persisted-record mapping.
- `apps/api/app/suggestion_service.py`: reserve/replay/finalize/get lifecycle around the unlocked provider call.
- `apps/api/app/main.py`: exact request/response models, dependency injection, routes, status/error mapping.
- `apps/mobile/src/todos/todoApi.ts`: suggestion transport and strict contract parser.
- `apps/mobile/src/todoWorkflows/pendingWorkflowWrite.ts`: exact persisted `suggest` request variant.
- `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx`: suggestion controls, recovery, and draft protection in the existing breakdown template.

---

### Task 1: Thin OpenRouter boundary

**Files:** Create `apps/api/app/suggestion_provider.py`, `apps/api/tests/test_suggestion_provider.py`, and `apps/api/.env.example`. Modify `apps/api/pyproject.toml` and `apps/api/uv.lock`.

**Interfaces:** Produce `OpenRouterConfig(api_key: str, model: str)`, `get_openrouter_config()`, and `async request_todo_suggestions(goal: str, config: OpenRouterConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> tuple[str, ...]`. Raise `SuggestionsNotConfigured`, `SuggestionTimeout`, `ProviderUnavailable`, or `InvalidSuggestionOutput`; exception text contains no provider body, prompt, key, or generated titles.

- [ ] Add focused tests using `httpx.MockTransport`. Assert the exact model/messages, `provider: {"require_parameters": true}`, strict JSON Schema, `max_tokens: 400`, Authorization header, 2/10-title boundaries, 16 KiB cap, malformed JSON/schema, noncanonical titles, non-2xx responses, and top-level `error` at HTTP 200. Example:

```python
assert request_json["response_format"]["json_schema"]["strict"] is True
assert request_json["provider"] == {"require_parameters": True}
with pytest.raises(ProviderUnavailable):
    await call(response={"error": {"code": 429, "message": "hidden"}})
```

- [ ] Run `uv run --directory apps/api python -m pytest tests/test_suggestion_provider.py -v`; verify RED for the missing module.
- [ ] Move `httpx` into runtime dependencies, lock without unrelated upgrades, document blank variable names only, and implement the smallest async client. Use `asyncio.timeout(30)` around the request and httpx connect/write/pool `5s`, read `25s`; stream and stop once the body exceeds 16 KiB before JSON/Pydantic validation, and reuse `create_submit_tasks` for title rules.
- [ ] Run the focused test green and `uv run --directory apps/api ruff check app/suggestion_provider.py tests/test_suggestion_provider.py`. Commit as `feat: add bounded OpenRouter suggestion client`.

### Task 2: Persisted request lifecycle without long locks

**Files:** Create `apps/api/alembic/versions/2026091001_add_workflow_suggestions.py`, `apps/api/app/suggestion_service.py`, and `apps/api/tests/test_workflow_suggestions.py`. Modify `apps/api/app/workflow_repository.py`, `apps/api/app/workflow_service.py`, `apps/api/tests/conftest.py`, and `apps/api/tests/test_workflow_persistence.py`.

**Interfaces:** Export `SuggestionSnapshot`, `SuggestionStatus`, and the repository row described by the spec. Rename the existing `_fingerprint` helper to `fingerprint_payload(payload: dict[str, Any]) -> str` and reuse it. Service exports:

`reserve_suggestion(session, owner_id, workflow_id, request_id, expected_revision, step_id)` returns `SuggestionReservation | SuggestionSnapshot`; `finish_suggestion(session, owner_id, workflow_id, request_id, *, titles, error_code)` returns `SuggestionSnapshot`; and `get_current_suggestion(session, owner_id, workflow_id)` returns `SuggestionSnapshot | None`. `titles` is `tuple[str, ...] | None`, and `error_code` is `SuggestionErrorCode | None`.

- [ ] Write migration/mapper tests for exact constraints, upgrade/downgrade preservation, cascade, round trips, and malformed JSONB. Write service tests proving owner-hidden lookup, `COLLECT_TASKS` only, exact revision/step, same-ID ready/failed replay, same-ID pending conflict, request-ID mismatch, newer-ID supersession, and current GET filtering.
- [ ] Add the smallest concurrency regression: reserve two IDs at one revision, finish the older after the newer, and assert the older raises `StaleSuggestion` while the current row remains the newer request. Assert no todo or workflow revision changed.

```python
older = reserve(request_id=old_id)
newer = reserve(request_id=new_id)
with pytest.raises(StaleSuggestion):
    finish(request_id=old_id, titles=("Invite guests", "Buy cake"))
assert get_current().request_id == new_id
```

- [ ] Run focused tests RED, implement one journal table with status/error/title cross-field checks, then implement reserve and finalize as separate `session.begin()` transactions. Lock only the owner-scoped workflow during each transaction; finalization verifies the newest internal request ID plus unchanged definition/state/revision/step. Never hold a transaction across the provider call.
- [ ] Test process-crash-shaped pending recovery and replay at the database boundary, run focused persistence/reliability/domain suites green, and commit as `feat: persist recoverable workflow suggestions`.

### Task 3: Authenticated suggestion API

**Files:** Modify `apps/api/app/main.py`, `apps/api/tests/test_workflows.py`, and `apps/api/tests/test_validation.py`.

**Interfaces:** Extend `create_app` with an optional async suggestion callable for deterministic tests. Add exact `TodoWorkflowSuggestionRequest`, `TodoWorkflowSuggestionResponse`, POST `/todo-workflows/{id}/suggestions`, and GET `/todo-workflows/{id}/suggestions`; call the provider only for a fresh reservation.

- [ ] Add API tests for exact request/response shapes, strict UUID/integer/extra-field rejection, authentication/owner-hidden 404, invalid state/revision/step, pending/superseded conflicts, ready `201` then replay `200`, saved failed replay, database `503`, and confirmation-only todo creation. Prove a ready replay succeeds after unsetting provider configuration and the provider spy remains at one call.
- [ ] Add an async deferred-provider test: reserve, verify a second session can read the workflow while the provider awaits, advance/cancel or supersede, release the provider, and assert `409 stale_suggestion` with no published titles.
- [ ] Implement route orchestration in order: reserve/replay; resolve configuration only for fresh work; await provider outside transactions; persist a safe failed category or validated titles; map exact `detail: {code, message}` errors. Do not place provider objects or output in workflow envelopes.
- [ ] Run `uv run --directory apps/api python -m pytest tests/test_suggestion_provider.py tests/test_workflow_suggestions.py tests/test_workflows.py tests/test_validation.py -v` and API lint green. Commit as `feat: expose workflow suggestion endpoints`.

### Task 4: Mobile request recovery and editable proposal UI

**Files:** Modify `apps/mobile/src/todos/todoApi.ts`, `apps/mobile/src/todos/todoApi.test.ts`, `apps/mobile/src/auth/authenticatedApi.ts`, `apps/mobile/src/auth/authenticatedApi.test.ts`, `apps/mobile/src/todoWorkflows/pendingWorkflowWrite.ts`, `apps/mobile/src/todoWorkflows/pendingWorkflowWrite.test.ts`, `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx`, and `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx`.

**Interfaces:** Add `WorkflowSuggestionRequest`, exact version-1 `WorkflowSuggestion`, `getWorkflowSuggestion(id, options)`, and `suggestWorkflowTodos(id, request, {...options, timeoutMs: 35_000})`. Extend every `PendingWorkflowWrite` validator, serializer, owner check, dispatcher, retry, discard, clear, and error branch with `{operation: "suggest", workflowId, body}`; it must never fall through to `advance`.

- [ ] Write transport/store RED tests for exact POST body, strict response/status parsing, 35-second override only on suggestion POST, GET 404, typed error codes, Unicode persistence, cross-owner/session rejection, exact saved-body retry, and discard. Assert suggestion dispatch calls only `suggestWorkflowTodos`.
- [ ] Write component RED tests for button availability from supported `view.type === "task_breakdown"` without client business-state branching; loading/live announcements; ready seeding and focus; edit/remove/empty-draft preservation; the unchanged 2–10 title submit bound; saved-ready refresh without POST; pending check; failed/manual fallback; explicit new-ID retry warning; retained request retry/discard; and zero todos until the existing confirmation.
- [ ] Add deferred-result tests capturing the edit counter, then type before resolution and assert the draft wins. Repeat for step advance, sign-out, same-owner re-login epoch change, superseded request, and unmount. Offer **Apply saved suggestions** for a saved proposal; test that replacing edited text requires explicit replacement confirmation and never happens automatically.

```ts
fireEvent.press(getByLabelText("Suggest todos"));
fireEvent.changeText(getByLabelText("Todo titles (one per line)"), "My own task");
provider.resolve(readySuggestion);
expect(getByDisplayValue("My own task")).toBeTruthy();
```

- [ ] Read the Expo SDK 57 docs required by `apps/mobile/AGENTS.md`, implement the transport/store union and minimal existing-template controls, and keep Phase 9 mutation reconciliation intact. Disable writes while suggestion persistence/request/reconciliation is unresolved; refetch workflow before retry or discard unlocks work.
- [ ] Run focused mobile tests, all mobile tests, and typecheck green. Commit as `feat: review recoverable AI todo suggestions`.

### Task 5: Verification, live smoke, guide, and checkpoint honesty

**Files:** Create `docs/guides/10-llm-assisted-planning.md`. Modify `README.md` and `docs/curriculum-roadmap.md` only after observed results justify each status statement.

- [ ] Run PostgreSQL-backed backend suites, all mobile suites, then `pnpm quality`, `git diff --check`, Markdown lint, and local-link checks. CI remains credential-free and uses no provider network.
- [ ] With user-supplied `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`, manually smoke the documented structured-output endpoint once. Record model identifier/date and whether it supports required parameters/schema; do not commit or print the key, and do not substitute an invented model.
- [ ] Record web and iOS Simulator observations for birthday-party suggestions, edit/remove, refresh without regeneration, manual fallback, timeout/invalid output, lost response, superseded late result, sign-out isolation, accessibility focus/announcements, and explicit confirmation. Leave unobserved rows incomplete.
- [ ] Write Guide 10 from verified behavior: configuration, data sent, schema plus Python validation, short transaction boundaries, request identity/replay, 30s/35s timeouts, exactly-once billing limitation, recovery exercise, tests, and honest synchronous/pending limits.
- [ ] Dispatch the required Sol whole-branch review against `12cd7f5...HEAD`; route integration redesign or difficult debugging to Terra, apply findings through receiving-code-review, and rerun affected checks. Update status docs only from final evidence; do not tag until integrated CI and checkpoint criteria pass.

## Coverage check

Provider/schema/bounds/errors are Tasks 1 and 3; owner/revision/request/stale-result persistence is Task 2; editable review, local-draft protection, and Phase 9 recovery reuse are Task 4; deterministic provider compatibility and both-platform acceptance are Task 5. Agents, streaming, workers, autonomous writes, model layouts, fixed model names, and production quotas remain excluded.
