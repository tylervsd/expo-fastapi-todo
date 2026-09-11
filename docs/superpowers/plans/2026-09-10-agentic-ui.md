# Phase 11 Agentic UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one authenticated assistant-ui/AG-UI clarification-and-review flow that feeds the existing durable suggestion and explicit-confirm workflow.

**Architecture:** Expo mounts one workflow-scoped assistant-ui runtime around an authenticated `HttpAgent` that calls the existing FastAPI `/agent` endpoint directly. Python chooses one server-catalog clarification through OpenRouter and emits two allowlisted tools; native components submit clarification through Phase 10 suggestions and edited titles through Phase 9 transitions, leaving PostgreSQL authoritative.

**Tech Stack:** Expo SDK 57/React Native 0.86, `@assistant-ui/react-native` 0.1.40, `@assistant-ui/react-ag-ui` 0.0.58, `@ag-ui/client` 0.0.59, Python AG-UI protocol, FastAPI/Pydantic/httpx, OpenRouter, PostgreSQL, Jest/pytest. Node 24.20 remains Expo tooling only.

**Spec:** `docs/superpowers/specs/2026-09-10-agentic-ui-design.md`

## Global Constraints

- Integrate the validated npm versions exactly: `@assistant-ui/react-native` 0.1.40, `@assistant-ui/react-ag-ui` 0.0.58, and `@ag-ui/client` 0.0.59.
- Keep OpenRouter calls and all authorization/business validation in Python; the per-session agent sends only its bearer authorization directly to FastAPI.
- Keep exactly two server-owned tools: `clarify_plan` and `review_todo_suggestions`; reject client-defined names/arguments.
- End every HTTP run before human input; the public tool-part `addToolResult` continues through an automatic new request after `useAgUiSetState` synchronously installs the state that request needs.
- Use one runtime per workflow and session; set `HttpAgent.threadId` to the workflow UUID and abort/remount on workflow or session replacement.
- Preserve Phase 9/10 workflow, pending-write, suggestion, manual-entry, and explicit `confirm` behavior.
- Make no automatic LLM/provider retry and create no persisted conversation, worker, A2UI renderer, or second workflow store.
- Normal tests use deterministic provider/event fixtures and no paid/network calls. Read the exact Expo SDK 57 docs before mobile work.

## File map

- `apps/api/app/agent.py`: strict agent decision, input/tool-history validation, and AG-UI event stream.
- `apps/api/app/suggestion_provider.py` and `suggestion_service.py`: shared bounded OpenRouter transport plus optional clarification on Phase 10 requests.
- `apps/api/app/main.py`: authenticated `/agent` stream and backward-compatible suggestion request model.
- `apps/mobile/src/agent/AgentSessionProvider.tsx`: token-private authenticated `HttpAgent` factory scoped to a session epoch.
- `apps/mobile/src/agent/AgentRuntimeProvider.tsx`: one `useAgUiRuntime` and `AssistantRuntimeProvider` per workflow.
- `apps/mobile/src/agent/AgentWorkflowPanel.tsx`: render and respond to the two allowlisted native tool cards through public message-part clients.
- Existing workflow screen/API/auth/pending store: authoritative suggest, submit, confirm, and recovery paths.

---

### Task 1: Integrate the validated compatibility slice

**Files:** Create `apps/mobile/src/polyfills.ts`, `apps/mobile/src/agent/compatibility.test.tsx`, and `apps/api/tests/test_agent_protocol.py`. Modify `apps/mobile/package.json`, `apps/mobile/index.ts`, `apps/api/pyproject.toml`, `apps/api/uv.lock`, and `pnpm-lock.yaml`.

**Interfaces:** `apps/mobile/src/polyfills.ts` initializes `globalThis.crypto.getRandomValues` from `expo-crypto` before `App` loads. The pinned assistant-ui public surface is `AssistantRuntimeProvider`, `ThreadPrimitive`, `useAgUiRuntime`, `useAgUiSetState`, and tool-part `addToolResult`. The Python test proves the installed `RunAgentInput`, event classes, encoder, and streaming media type used by Task 3.

- [ ] Install the exact three npm versions above without unrelated upgrades and pin the Python AG-UI protocol package selected by its public `RunAgentInput` and event encoder. Commit both lockfiles as the version record.
- [ ] Port only the proven secure-random initializer from `spikes/assistant-ui-ag-ui/polyfills.ts`; import it first in `index.ts` and test that it uses `expo-crypto` without `Math.random`.

```ts
import { getRandomValues } from "expo-crypto";

if (!globalThis.crypto) {
  Object.defineProperty(globalThis, "crypto", { value: {} });
}
if (!globalThis.crypto.getRandomValues) {
  Object.defineProperty(globalThis.crypto, "getRandomValues", {
    value: getRandomValues,
  });
}
```

- [ ] Write a focused Python protocol test that constructs `RunAgentInput`, encodes `RUN_STARTED`, `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`, and `RUN_FINISHED`, parses the resulting SSE, and asserts the order and documented response media type. Add a disconnect-cancellation test at the route boundary in Task 3.
- [ ] Port the smallest fixture runtime into `compatibility.test.tsx` so the real mobile app resolves the pinned imports, streams recorded tool events, renders through `MessagePrimitive.Parts`, and proves the public call below automatically sends a second request with the tool result.

```ts
runtime.thread
  .getMessageById(message.id)
  .getMessagePartByToolCallId(part.toolCallId)
  .addToolResult(result);
```

- [ ] Run the focused tests, mobile typecheck, production web export, and iOS export from the real mobile app. Add fetch/TextEncoder polyfills or Metro configuration only for a reproduced defect; do not add package patches, private imports, or another backend service. Commit as `build: add assistant-ui AG-UI runtime`.

### Task 2: Add bounded clarification to Phase 10 suggestions

**Files:** Modify `apps/api/app/suggestion_provider.py`, `apps/api/app/suggestion_service.py`, `apps/api/app/main.py`, `apps/api/tests/test_suggestion_provider.py`, `apps/api/tests/test_workflow_suggestions.py`, and `apps/api/tests/test_workflows.py`.

**Interfaces:** Add `ClarificationField = Literal["date", "location", "people", "budget", "constraints"]` and immutable `Clarification(field, value)`. Extend `request_todo_suggestions(..., clarification: Clarification | None = None)` and `reserve_suggestion(..., clarification: Clarification | None = None)`. Add optional exact API field `clarification`; omission retains the Phase 10 fingerprint and behavior.

- [ ] Write failing tests for 1/200-code-point bounds, enum/extra-key rejection, fingerprint mismatch on changed clarification, no-context replay compatibility, and exact provider data. Assert no raw provider output enters logs/storage and no clarification text enters server storage; the existing local pending write retains the answer only until exact retry resolves or is discarded.

```python
first = reserve(clarification=Clarification("date", "next Saturday"))
with pytest.raises(RequestIdReused):
    reserve(clarification=Clarification("budget", "under $50"))
assert first.goal == "weekend hike"
```

- [ ] Run the focused tests RED. Implement normalization once in `suggestion_service.py`, include the canonical object in the fingerprint only when supplied, and add one short labeled line to the provider prompt; absent context must produce Phase 10's exact old fingerprint. Extract one narrow bounded/redacted OpenRouter JSON request helper in `suggestion_provider.py`, make the existing suggestion call delegate to it, and reuse it in Task 3.
- [ ] Run provider/service/API suggestion suites and Ruff green. Commit as `feat: accept bounded suggestion clarification`.

### Task 3: Stream the authenticated Python AG-UI agent

**Files:** Create `apps/api/app/agent.py` and `apps/api/tests/test_agent.py`. Modify `apps/api/app/main.py` and `apps/api/tests/test_validation.py`.

**Interfaces:** Export `async choose_clarification(goal, config, *, transport=None) -> ClarificationField` and `agent_events(run_input, owner_id, session, choose=choose_clarification) -> AsyncIterator[BaseEvent]`. `POST /agent` accepts library `RunAgentInput`, with exact state `{contract_version: 1, expected_revision: int, step_id: str, suggestion_request_id: UUID | None}`, and returns its event encoder's documented streaming media type; `threadId` is the workflow UUID.

- [ ] Write RED tests for UUID `threadId`/`runId`, exact state/body/message bounds, owner-hidden workflow lookup, current definition/state/revision/step, exact event order, catalog-only model choice, malformed/provider error, cancellation, duplicate tool ID, unknown tool/result, stale history, and title reload from the current saved suggestion. Prove a stale supplied suggestion ID fails without a choice call, a current ready ID is handled before history and without a choice call, and retrying the same interrupted run ID may call the model again because there is no run journal.

```python
events = [event async for event in agent_events(run, owner.id, session, choose=fake)]
assert [event.type for event in events] == ["RUN_STARTED", "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "RUN_FINISHED"]
assert json.loads(events[2].delta)["field"] == "location"
assert count_todos(session, owner.id) == 0
```

- [ ] Implement a strict OpenRouter JSON-schema response containing only catalog `field` by importing Task 2's bounded transport/config/error mapping; do not copy an HTTP client. Map that field to fixed local prompt/label copy; never accept model/client question copy, schemas, URLs, or action names.
- [ ] Check a supplied ready proposal first, then parse only a structurally matching immediately preceding tool call/result. Re-read the owner workflow and saved suggestion before constructing exact arguments and use `{runId}:{tool}:0` IDs. A valid review result against an authoritative `REVIEW` snapshot emits no-write start/finish events; other non-collect states and invalid inputs emit safe errors. Never call `advance_workflow` here.
- [ ] Add the authenticated route through existing `get_current_user`; ensure disconnect cancellation closes provider work and no transaction spans streaming or human input. Run focused tests and Ruff green; commit as `feat: add authenticated AG-UI agent stream`.

### Task 4: Add session-private, workflow-scoped runtimes

**Files:** Create `apps/mobile/src/agent/AgentSessionProvider.tsx`, `apps/mobile/src/agent/AgentSessionProvider.test.tsx`, `apps/mobile/src/agent/AgentRuntimeProvider.tsx`, and `apps/mobile/src/agent/AgentRuntimeProvider.test.tsx`. Modify `apps/mobile/src/auth/AuthProvider.tsx` and `apps/mobile/src/auth/AuthProvider.test.tsx`.

**Interfaces:** Define `type AgentState = { contract_version: 1; expected_revision: number; step_id: string; suggestion_request_id: string | null }`. `AgentSessionProvider({token, sessionEpoch, children})` exposes `createAgent(workflowId): HttpAgent` through a private app context; the closure creates `${EXPO_PUBLIC_API_URL}/agent` agents with the exact bearer header and `threadId: workflowId`. `AgentRuntimeProvider({workflowId, initialState, children})` creates one stable agent, calls `useAgUiRuntime({agent})`, and mounts `AssistantRuntimeProvider`. An inner state gate calls `useAgUiSetState<AgentState>()` and does not enable its children until the initial state is installed. The provider remounts and aborts on workflow/session replacement and adds no new environment variable.

- [ ] Write RED tests proving the existing API URL plus `/agent`, exact bearer header, no cookie/client URL, `HttpAgent.threadId === workflowId`, stable identity for one workflow/session, different instances for different workflows, and abort on workflow change, token/epoch replacement, logout, or unmount.

```ts
expect(agent.url).toBe(`${apiUrl}/agent`);
expect(agent.headers).toEqual({ Authorization: "Bearer tok" });
expect(agent.threadId).toBe(workflow.workflow_id);
```

- [ ] Implement the session factory only inside `AuthProvider`'s signed-in branch, keyed by session epoch and given its private current token. Test restore/login/replacement/logout and that tokens never enter `TodoExperience`, query keys, agent state, pending storage, or logs.
- [ ] Implement the workflow provider with the public `useAgUiRuntime` and `AssistantRuntimeProvider`. Inside that provider, use the public state setter and keep the agent action disabled until the exact initial `AgentState` is installed; do not rely on `HttpAgent.initialState`, which the inspected adapter does not copy into its runtime state. Mount above the step templates so it remains alive for the `COLLECT_TASKS` to `REVIEW` acknowledgement, and cancel the thread plus abort the agent during cleanup.
- [ ] Prove an initial request body carries the workflow UUID in `threadId`, never `"main"`, and that switching workflows cannot carry messages, tool results, or state into the next runtime. Run provider/auth tests, typecheck, and web export green. Commit as `feat: connect workflow-scoped agent runtimes`.

### Task 5: Render clarification and editable review in the workflow

**Files:** Create `apps/mobile/src/agent/AgentWorkflowPanel.tsx` and `apps/mobile/src/agent/AgentWorkflowPanel.test.tsx`. Modify `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx` and its test, `apps/mobile/src/todos/todoApi.ts` and its test, `apps/mobile/src/auth/authenticatedApi.ts` and its test, and `apps/mobile/src/todoWorkflows/pendingWorkflowWrite.ts` and its test.

**Interfaces:** `AgentWorkflowPanel` receives current `userId`, workflow snapshot, authenticated API, pending store, UUID generator, session epoch guard, and `submitTasks(titles, requestId)`. `MessagePrimitive.Parts` renders only `clarify_plan` and `review_todo_suggestions` with exact version-1 parsers. `useAgUiSetState<AgentState>()` updates state synchronously; the public message-part client then calls `addToolResult(result)` once.

- [ ] Add recorded-event component tests for streamed/incomplete arguments, unresolved and resolved tool parts, exact/unknown/malformed/stale arguments, one response, catalog copy, 1–200 answer validation, editable 2–10 checklist titles, removal, focus/live announcements, 44-point controls, and manual fallback.
- [ ] Extend transport, auth wrapper, and pending-write types/parsers for optional exact clarification. Accept both the old three-key suggestion body and the new four-key body, preserving the answer and exact request on retry; reject all other extra keys. On mount/reload, fetch workflow and the existing current suggestion before the first append; initialize exact agent state with the authoritative workflow identity and ready request ID. Verify no stream remains open while the user types.
- [ ] Test clarification submission saves before calling the API, awaits the durable suggestion, calls `setAgentState` with the current revision/step and returned request ID, then calls `addToolResult` with that same ID. Assert the automatic continuation POST sees the updated state and occurs once; an uncertain failure retains the saved request and sends neither a result nor a new request ID.

```ts
fireEvent.changeText(getByLabelText("Your answer"), "next Saturday");
fireEvent.press(getByRole("button", { name: "Continue" }));
await waitFor(() => expect(api.suggestWorkflow).toHaveBeenCalledTimes(1));
expect(setAgentState.mock.invocationCallOrder[0]).toBeLessThan(
  addToolResult.mock.invocationCallOrder[0],
);
expect(api.advanceWorkflow).not.toHaveBeenCalled();
```

- [ ] Test **Use these suggestions** persists the existing `advance/submit_tasks` pending write and reconciles the returned workflow. While the workflow-scoped provider remains mounted, set agent state to the returned `REVIEW` revision/step before adding `{contract_version: 1, request_id, accepted_revision}` as the result. Its automatic continuation emits no write and no regeneration. If workflow/session cleanup wins first, abort and omit the late result. Re-rendering/replaying the tool must not repeat it; repeated request identity must replay; todos remain zero until the unchanged confirmation button succeeds.
- [ ] Add deferred tests for edit, newer revision, cancellation, unmount, sign-out, and same-owner relogin. Late results do not respond, mutate query data, replace titles, or enable a stale action. **Retry saved request** reuses the stored ID; no path automatically retries an LLM call.
- [ ] Implement with native controls, `ThreadPrimitive.MessagesFlatList`, `MessagePrimitive.Parts`, and public tool-part clients. Do not add the optional assistant-ui compiler/toolkit. Disable competing workflow/suggestion writes only while this panel owns an unresolved write; preserve Phase 10 manual entry/suggestion recovery. Run focused tests, all mobile tests, typecheck, and web export; commit as `feat: add agent clarification and review UI`.

### Task 6: Verify behavior, document evidence, and review

**Files:** Create `docs/guides/11-agentic-ui.md`. Modify `README.md` and `docs/curriculum-roadmap.md` only when observed status justifies it.

- [ ] Run PostgreSQL-backed API tests, all mobile tests/typecheck, `pnpm quality`, `git diff --check`, Markdown lint, and local-link checks. CI remains credential-free.
- [ ] With separate user authorization and a stated bounded budget, run two decision requests (one per goal) plus the corresponding suggestion requests. Record model/date and observed fields; never print/store the key, prompts, answers, or titles.
- [ ] Record web and iOS Simulator rows separately for question selection, form response, editable/removable suggestions, interruption/replay, malformed/unknown tool fallback, sign-out isolation, accessibility, and existing explicit confirm. Leave unobserved rows incomplete.
- [ ] Write Guide 11 from evidence: topology, pinned compatibility, header flow, exact contracts, authoritative-state reconciliation, separate-run HITL lifecycle, manual fallback, and honest conversation/billing/recovery limits.
- [ ] Dispatch the required Sol whole-branch review against `78cedcf`; route integration failures to Terra, apply valid findings through receiving-code-review, and rerun affected checks. Do not tag until integrated CI and checkpoint criteria pass.

## Coverage check

Compatibility is Task 1; bounded context and Phase 10 durability are Task 2;
Python choice/events/authority are Task 3; session-private authentication and
workflow isolation are Task 4; allowlisted native interactions, editing,
recovery, and confirm-only creation are
Task 5; supported-platform evidence and review are Task 6. Arbitrary UI,
persisted chat, background resumption, extra tools, autonomous writes, and
production hardening remain excluded.
