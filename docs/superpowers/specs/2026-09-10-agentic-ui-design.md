# Phase 11: Agentic UI Design

**Status:** Draft for review

**Base:** Phase 10 merged in PR #7 at `e1e2cac`, plus `78cedcf`

**Checkpoint:** `phase-11-agentic-ui` only after implementation, verification, acceptance, integration, and CI

## Goal

A signed-in user at the existing **Break it into smaller todos** step can ask
an OpenRouter-backed Python agent for help. The agent chooses one relevant
question from a fixed clarification catalog, assistant-ui renders that question
as a native form, and the submitted answer produces a durable Phase 10
suggestion request. A later AG-UI run renders the saved titles as an editable
checklist. Accepting the edits uses the existing `submit_tasks` transition;
only the existing explicit `confirm` transition creates todos.

This phase teaches assistant-ui's React Native primitives and AG-UI runtime,
typed human-in-the-loop tools, and an authenticated direct agent connection
while the Python workflow service and PostgreSQL remain authoritative.

## Validated compatibility baseline

The repository spike in `spikes/assistant-ui-ag-ui` validated this exact release
set on September 10, 2026:

- `@assistant-ui/react-native` 0.1.40;
- `@assistant-ui/react-ag-ui` 0.0.58; and
- `@ag-ui/client` 0.0.59.

All three published packages declare the MIT license. With Expo SDK 57.0.19,
React Native 0.86.3, and React 19.2.3, the public
`AssistantRuntimeProvider`, `ThreadPrimitive`, `useAgUiRuntime`, `HttpAgent`,
and tool-part APIs rendered and streamed on Expo web and the iOS Simulator.
Calling a public tool-part client's `addToolResult` started the automatic
second AG-UI POST, and cancellation stopped the active response. Inspection of
the installed public source also confirmed that `useAgUiSetState` synchronously
updates the state used by the next run; Task 5 must prove that ordering in the
real flow. The spike also proved a bearer header reaches FastAPI and that no
hosted assistant-ui service or deployed Node process is involved.

Native startup required `crypto.getRandomValues`. Import a small initializer
before `App` from `index.ts` and supply it with the app's existing
`expo-crypto` dependency. Never add a `Math.random` fallback. Add a streaming
fetch polyfill or Metro workaround only if a new reproduced failure requires
one; do not use package patches or private imports.

The spike used literal fixture SSE. Task 1 must still prove the Python AG-UI
SDK's `RunAgentInput`, event classes, encoder, media type, and disconnect
cancellation in this FastAPI application before feature work proceeds. Web and
iOS are the observed targets. Android, physical devices, deployment, token
refresh during a run, and live-model behavior remain unobserved until their
acceptance rows are run; do not infer them from package support claims.

## Chosen architecture

Expo mounts an assistant-ui `AssistantRuntimeProvider` around one
`useAgUiRuntime` instance for the selected workflow. Its pinned `HttpAgent`
calls the existing FastAPI service at `${EXPO_PUBLIC_API_URL}/agent` with
`threadId` set to that workflow UUID. Node remains Expo tooling only. There is
no runtime service, proxy, second port, new public URL, client-selected agent
URL, hosted assistant-ui dependency, or frontend model call. The same direct
path is available in development and production builds.

FastAPI exposes authenticated `POST /agent`. It accepts standard AG-UI
`RunAgentInput`, requires `threadId` to equal the workflow UUID, and accepts
the opaque safe `runId` emitted by assistant-ui (1–128 ASCII letters, digits,
underscores, or hyphens). The run ID only correlates this request's events and
tool calls; it is not a workflow identity. The server loads that owner-scoped
workflow and validates the current
definition, revision, step, and expected `COLLECT_TASKS` or
review-acknowledgement state before emitting events. Client tool schemas and
arbitrary message instructions are never authority.
The server has exactly two tool names and constructs every tool argument.
The route caps the encoded body at 32 KiB, accepts at most 12 messages, caps
each text item at 1,000 code points and each tool result at 4 KiB, and rejects
unknown state fields before a provider call.

`RunAgentInput.state` is the exact object
`{contract_version: 1, expected_revision, step_id,
suggestion_request_id: string | null}`; `threadId` carries the workflow UUID.
A non-null suggestion ID that is not the current ready owner/workflow/revision/
step proposal fails closed and never falls through to a new model call.

The first run asks OpenRouter for one strict structured decision:

```json
{"field":"date"}
```

`field` must be one of `date`, `location`, `people`, `budget`, or
`constraints`. This is a real model choice based on the canonical workflow
goal; it is not a keyword switch presented as an agent. Python maps the field
to fixed local copy and emits `clarify_plan`. Invalid/provider-failed decisions
end with a safe AG-UI error and leave the manual Phase 10 path available.
The decision sends only the canonical goal and reuses Phase 10's bounded,
redacted OpenRouter transport: 400 requested output tokens, a 16 KiB response
cap, a hard 30-second deadline, 5-second connect/write/pool timeouts, and a
25-second read timeout.

The form submits one 1–200-code-point answer. While that pending tool card is
in its local submitting state, the client creates a Phase 10 suggestion request
using the current workflow identity and the chosen `{field, value}`. That
request keeps Phase 10's short
transactions, OpenRouter limits, durable result, explicit retry, and no
automatic paid retry. Its fingerprint and provider prompt gain this optional
clarification object only when supplied. When absent, the canonical fingerprint
is byte-for-byte the Phase 10 input, so old retries retain their exact hash and
behavior. Pending-record parsing remains backward compatible.

After suggestion success, the client synchronously calls the public
`useAgUiSetState` setter with the current workflow identity and
`suggestion_request_id`, then calls that tool part's public `addToolResult`
exactly once with the same ID. `addToolResult` automatically starts a second
AG-UI POST after the first run has settled, and that POST observes the updated
state. It starts no hidden workflow transition. On every later AG-UI request,
Python first checks the state-provided request ID against the
owner-scoped current ready Phase 10 proposal. A match emits
`review_todo_suggestions` from persisted titles without prior conversation
history or another model call. This branch precedes clarification choice and
history parsing, so reload can recover a ready proposal. Without a current
ready ID, structurally matching clarification call/result messages may
continue, but client history does not prove that the server issued a call and
cannot authorize a write. The owner, workflow, revision, step, request ID, and
database proposal remain authority. The checklist's **Use these suggestions** submits edited titles through
the existing `advance` API with `submit_tasks`. The next authoritative snapshot
renders Phase 9's existing confirmation screen.

The workflow-scoped runtime remains mounted while the screen moves from
`COLLECT_TASKS` to `REVIEW`. After `submit_tasks` returns, the client first
sets agent state to the returned revision and step, then adds the exact review
tool result. Its automatic continuation therefore runs against `REVIEW`;
Python validates the structural result against the authoritative snapshot and
emits only `RUN_STARTED` then `RUN_FINISHED`. It neither regenerates
suggestions nor performs a write. Other non-`COLLECT_TASKS` invocations fail
closed. If the workflow or session unmounts first, cancellation wins and no
late result or continuation is sent.

No HTTP stream or database transaction waits for a person. Each tool request
is followed by `RUN_FINISHED`; submitting a tool result starts a separate run.

## Event and tool contract

Every run emits `RUN_STARTED`, balanced message/tool-call events, then exactly
one `RUN_FINISHED` or `RUN_ERROR`. Tool-call IDs are
`{runId}:clarify_plan:0` or `{runId}:review_todo_suggestions:0`; a repeated ID
within a run fails closed. Text events are optional status copy and never carry
workflow state.

`clarify_plan` arguments are an exact object:

```json
{"contract_version":1,"workflow_id":"uuid","expected_revision":2,
 "step_id":"uuid:COLLECT_TASKS","field":"date"}
```

Its result is exact and bounded:

```json
{"contract_version":1,"suggestion_request_id":"uuid"}
```

`review_todo_suggestions` repeats `contract_version`, workflow identity,
revision, step, and suggestion request ID, and adds `titles` with Phase 10's
2–10 canonical-title bounds. Unknown names, versions, extra keys, malformed
arguments, mismatched IDs, stale revisions/steps, and unsupported fields render
a safe recovery message and cannot call `advance`.

Its exact result is
`{"contract_version":1,"request_id":"uuid","accepted_revision":3}`.

The client renderer accepts only these canonical server-owned names and exact
argument shapes. The Python endpoint ignores client-supplied tool definitions,
rejects tool results that do not structurally match the immediately preceding
call, and re-reads the current owner-scoped suggestion before rendering titles.
Rendering, replay, reconnection, and completion events never create or confirm
todos.

## Authentication and state ownership

`AuthProvider` keeps the bearer token private. Its signed-in branch exposes an
opaque authenticated agent factory keyed by session epoch; the token remains
inside that closure. For the selected workflow, the workflow screen creates
one stable `HttpAgent` with `${EXPO_PUBLIC_API_URL}/agent`, the current
`Authorization` header, and `threadId: workflow_id`, then mounts one
`useAgUiRuntime`. Switching workflow IDs remounts the runtime, clears its
messages and state, and aborts the old agent. Token replacement, logout, or
unmount does the same. One runtime never carries messages or state between
workflows or sessions.

PostgreSQL workflow/suggestion records are durable authority. TanStack Query
holds authoritative snapshots; assistant-ui messages hold only the current UI
conversation. Agent events may propose rendering but never patch workflow
cache directly. After form or checklist work, the client refetches/reconciles
through the existing Phase 9/10 paths before enabling another write.

The client captures owner, session epoch, workflow, revision, step, run, tool,
and suggestion request identities around asynchronous work. Sign-out,
replacement login, unmount, cancellation, or a newer snapshot discards late
events and results. The provider remount clears in-memory agent history.
On reload the client fetches the current workflow and existing suggestion API
before starting an agent run, then places that current ready request ID in
state so review recovery does not depend on conversation history.

## Recovery and accessibility

Cancellation aborts the active transport and does not invoke another model or
workflow action. An interrupted clarification run has no durable agent state;
**Try agent again** explicitly starts a new paid choice request. An interrupted
suggestion request keeps Phase 10's pending write/request ID. **Retry saved
request** first recovers that exact outcome; it never silently creates a new
provider request. If titles were saved but review events were lost, a new AG-UI
run reads and renders them without another model call.

There is deliberately no durable agent-run journal. Run and tool IDs correlate
one request and reject duplicates within it; they are not model-call
idempotency keys. Retrying even the same run ID after an interrupted
clarification or process restart can repeat the decision call and its cost.
Recovery is always an explicit user action and the UI says so.

There is no persisted conversation or background run resumer. Reload between
clarification and its result restarts the agent interaction, while the durable
workflow and any reserved/saved suggestion remain recoverable through the
existing screen. There is no automatic LLM retry after timeout, malformed
output, cancellation, disconnect, or uncertain completion.

Both allowlisted components use native controls, visible labels, 44-point
targets, focus movement, alert/live announcements, disabled duplicate-submit
states, and non-color status. Manual title entry and the Phase 10 suggestion
button remain usable whenever the agent layer fails.
The clarification answer exists only in the owner-scoped local pending write
until its exact suggestion retry resolves or is discarded. The server stores
only its request fingerprint; saved titles retain Phase 10's existing storage.

## Testing and acceptance

Start with recorded AG-UI fixtures before the live model path. Python tests
cover decision validation, owner hiding, authorization, argument allowlists,
run/tool identities, stale state, replay, unknown tools, cancellation, and
duplicate-write prevention. Provider tests prove the existing API URL,
workflow UUID `threadId`, exact per-session header, per-workflow isolation,
and session teardown. Component tests cover streamed arguments, unresolved and
resolved tool parts, one response, editing/removal, stale/session guards,
recovery, accessibility, and zero todos before existing confirmation.

Normal CI uses deterministic provider/event fixtures and no network or paid
call. Manual acceptance records web and iOS separately: relevant question
selection for two goals, form submission, editable suggestions, interruption
recovery, unsupported-tool fallback, sign-out isolation, and explicit confirm.
Passing automated tests is not evidence that either interactive target works.

## Non-goals and limits

- No A2UI, arbitrary generated UI/code, chat product, persisted conversation,
  background worker, general agent framework, or autonomous workflow action.
- No new todo creation endpoint, workflow definition, or competing cache.
- No model-selected URLs, headers, schemas, action names, or raw database tool.
- FastAPI's existing exact Expo web CORS policy covers `/agent`; no wildcard or
  second service origin is added. Native clients are not subject to browser CORS.
- No production quota, pruning, telemetry, or exactly-once provider billing;
  Phase 13 owns those measured hardening needs.
- Phase 12 owns full cross-platform E2E. Phase 11 records bounded manual
  acceptance plus contract/component/integration tests.

## Validated references

- [assistant-ui AG-UI quickstart](https://www.assistant-ui.com/docs/runtimes/ag-ui/quickstart)
- [assistant-ui React Native primitives](https://www.assistant-ui.com/docs/react-native/primitives)
- [assistant-ui repository](https://github.com/assistant-ui/assistant-ui)
- [AG-UI repository](https://github.com/ag-ui-protocol/ag-ui)
- [Expo Crypto](https://docs.expo.dev/versions/v57.0.0/sdk/crypto/)
