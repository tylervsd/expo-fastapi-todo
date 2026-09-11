# Workflow and AI learning plan

## Status and scope

This is a planned curriculum extension after Phase 6, not an implementation guide or a claim that these features already exist. Each phase still needs its own approved spec before implementation. Keep the existing quick-add experience, authentication boundary, and `/todos` contract working throughout.

The [curriculum roadmap](curriculum-roadmap.md) adds Phase 7 for backend workflow modeling, Phase 8 for server-directed screens, and Phase 9 for workflow reliability. Phase 10 adds Python/OpenRouter suggestions, and Phase 11 adds assistant-ui/AG-UI interactions. A CI security baseline and cross-platform E2E follow before the provisional cloud curriculum in Phases 13–27. Existing guide numbers and checkpoint tags remain unchanged.

## Design principle

The backend decides which business action is valid and what happens next. The frontend renders a supported screen and submits the user's next action. A client request never gets to choose the next workflow state.

Use explicit Python transition logic and a small catalog of native screen templates. Do not begin with a workflow framework, arbitrary JSON layouts, a visual workflow editor, or background orchestration. This keeps the lessons about state transitions rather than framework configuration.

A backend-selected "new screen" means a different component the client already supports. Backend-only changes can alter question content and branching among supported templates; a genuinely new template still requires client implementation and a compatibility strategy.

## Running feature: guided todo creation

Add a separate "Help me plan a task" entry point. For the title "Plan birthday party", the deterministic Phases 7-9 teaching example follows this transition table. The state names and endpoint examples below are proposed contracts to refine in each approved phase spec.

| Current state | Accepted action | Next state and result |
| --- | --- | --- |
| Start | Submit a valid title | Persist a draft and enter `ASSESS_TASK`. |
| `ASSESS_TASK` | Answer yes | Enter `OFFER_BREAKDOWN`. |
| `ASSESS_TASK` | Answer no | Enter `REVIEW` with the original title. |
| `OFFER_BREAKDOWN` | Answer yes | Enter `COLLECT_TASKS`. |
| `OFFER_BREAKDOWN` | Answer no | Enter `REVIEW` with the original title. |
| `COLLECT_TASKS` | Submit valid task titles | Save the proposed titles and enter `REVIEW`. |
| `REVIEW` | Confirm | Create the proposed todos and enter `COMPLETED`. |
| Any nonterminal state | Cancel | Enter `CANCELLED` without creating todos. |
| Any state | Invalid or stale action | Do not change the workflow or create todos. |

`ASSESS_TASK` asks "Does this task involve multiple steps?" and `OFFER_BREAKDOWN` asks "Would you like to split it into smaller todos?" Both use the same yes/no template with different content and step identities. `COLLECT_TASKS`, `REVIEW`, and `COMPLETED` select different supported templates. A cancelled workflow displays a supported terminal view.

An unfinished workflow is a saved draft, not a set of committed todos. Completion is terminal; displaying or fetching a completed workflow must not repeat its writes. The server validates title lengths, task counts, empty inputs, and action payloads regardless of client validation. Exact limits belong in the phase spec.

## State ownership and component boundaries

| State or responsibility | Owner |
| --- | --- |
| Current business state, accepted answers, owner, and terminal status | Backend domain logic and PostgreSQL. |
| Mapping business state to a supported screen description | Backend presentation mapper, separate from transition rules. |
| Latest workflow snapshot received from the API | TanStack Query. |
| Unsubmitted text, focus, and submitting indicators | React component state. |
| Rendering templates, collecting input, and accessibility | Existing Expo/React Native client. |

Keep HTTP handling thin: authenticate, validate, call the workflow service, and return a typed response. The service coordinates transition rules with repository operations. Domain rules do not know React component names, navigation URLs, or layout details.

Keep workflow transitions pessimistic initially: show a submitting state and render the authoritative response. Do not duplicate backend branching rules to predict the next screen. Preserve the existing separation between authentication and application rendering, and clear user-specific cached workflows on sign-out. Prevent late responses from a previous session from repopulating another user's cache.

A workflow host can choose from a small template registry within the existing application shell. A new navigation library is not a prerequisite. For each newly issued question, use a fresh step identity so a reused component does not retain another question's unsubmitted answer. Define focus and announcement behavior for both web and iOS in the phase spec.

## Proposed current-view API

Return the workflow's current view after both fetching and advancing it. Avoid imperative responses such as "push this route" or "replace that text"; a current-view response can reconstruct the experience after refresh.

| Operation | Proposed endpoint | Purpose |
| --- | --- | --- |
| Start | `POST /todo-workflows` | Create an owner-scoped draft from a valid title. |
| Discover | `GET /todo-workflows?status=active` | Find the signed-in user's unfinished workflows. |
| Resume | `GET /todo-workflows/{workflow_id}` | Return the saved current view without advancing it. |
| Advance | `POST /todo-workflows/{workflow_id}/actions` | Validate and apply a user action, then return the resulting view. |

The following response includes fields taught across all three phases. Identifiers are illustrative opaque strings, not a prescribed identifier format.

```json
{
  "workflow_id": "wf_123",
  "revision": 2,
  "step_id": "step_002",
  "status": "active",
  "view_contract_version": 1,
  "view": {
    "type": "yes_no",
    "title": "Break this task into smaller todos?",
    "question": "Would you like to split 'Plan birthday party' into smaller tasks?",
    "actions": [
      { "id": "yes", "label": "Yes" },
      { "id": "no", "label": "No" }
    ]
  }
}
```

The client submits what the user did, not a requested `next_state`:

```json
{
  "step_id": "step_002",
  "expected_revision": 2,
  "submission_id": "submission_456",
  "action_id": "yes"
}
```

A new `yes_no` view with a new `step_id` changes the content of an existing template. A `task_breakdown`, `review`, or `completion` view selects a different supported component. Terminal responses describe completed or cancelled outcomes and do not advertise further business transitions.

Use discriminated Pydantic response models, corresponding TypeScript types, and runtime response validation. Validate action payloads against the current state on the server, even when the action was not advertised by the client. Unknown templates or unsupported contract versions produce a safe fallback with recovery guidance; they must not execute server-supplied code or arbitrary navigation instructions.

## Phase 7: backend workflow modeling

Build the first vertical slice with one branching question: answer yes to enter `COLLECT_TASKS`, or no to enter `REVIEW`. Add confirmation and cancellation. Phase 8 inserts `OFFER_BREAKDOWN` to demonstrate two consecutive uses of one template. This intentional progression keeps the first transition model small.

Persist the owner, state, accepted context, and terminal result between requests. Separate state/action validation and transition decisions from HTTP, rendering, and SQL. Use dedicated frontend components first; do not introduce the generic template registry yet. Save a transition and its database changes transactionally. Multi-device conflict detection and safe automatic resubmission are not promised until Phase 9.

Most tests are table-driven unit tests for valid and invalid transitions. Add targeted API/database tests for authenticated ownership, validation, saved progress, cancellation, and rollback. An invalid action must not advance the workflow. Fetching a workflow must not cause business writes.

**Experiment:** call the API directly with an action valid only in another state and show that the backend rejects it without changing stored progress.

**Guide after implementation:** `docs/guides/07-backend-workflows.md`. Write it from verified behavior rather than creating a placeholder guide now.

## Phase 8: server-directed screens and reusable templates

Insert the second yes/no question and introduce a separate state-to-view mapper. Add the small registry of `yes_no`, `task_breakdown`, `review`, and `completion` templates. Teach the difference between a business state, a template type, and an issued step identity.

Use one response shape for resume and advance, with typed contracts and runtime validation. Preserve draft values only for the same issued step. An unsupported view produces a recoverable fallback, not a silent guess or an application crash. Do not move business branching into the renderer.

Add contract tests and component tests for template selection, changing content, reset between questions, submitting state, accessibility, and unsupported views. Loading or redisplaying a view is not a new transition. Invalidate the todo query when a confirmed completion creates todos.

**Experiment:** add another yes/no question and branch entirely in the backend without adding frontend branching or another component.

**Guide after implementation:** `docs/guides/08-server-directed-ui.md`.

## Phase 9: reliable, resumable workflows

Extend the uncertain-write lessons from Phase 5. Introduce a revision that changes on an accepted transition and enforce its comparison atomically in PostgreSQL. A read-then-check in Python followed by an unguarded update is not sufficient. Different submissions racing against one revision must not both advance the workflow.

Give each intended submission an identifier that survives network retries. Scope its record to the authenticated owner and workflow, store the request fingerprint and accepted outcome, and enforce uniqueness in the database. The same identifier with different input is a conflict. Check a previously committed identical submission before rejecting its now-old revision; otherwise a successful retry would incorrectly look stale. Cover workflow creation with an equivalent owner-scoped idempotency contract to avoid duplicate drafts after a lost start response.

Commit the revision change, accepted context, created todos, terminal status, and idempotency outcome in one transaction for this database-only exercise. Handle simultaneous identical submissions with database constraints and a defined replay path, not just a preliminary lookup. This is not a promise of distributed exactly-once processing.

A replay can return its recorded historical response. The client must not replace a newer cached revision with that older snapshot; compare revisions and refetch the current view when necessary. Distinguish view-contract versions from workflow-definition versions. Persist the latter and specify how supported older definitions finish before changing their transition rules; do not silently reinterpret saved drafts under incompatible rules.

| Failure scenario | Required behavior and test |
| --- | --- |
| The app closes mid-flow | Discover active workflows and resume the saved step, including from another device. |
| The API restarts | Accepted progress survives in PostgreSQL. |
| A successful start or action response is lost | Retry with the same identifier and recover the recorded result without duplicate writes. |
| Confirmation is double-tapped | One intended set of todos is created. |
| Two devices submit different answers to one revision | One advances; the other receives a stale-step conflict and can refresh. |
| Two requests carry the same submission identifier | One effect and a consistent replay, including concurrent requests. |
| An identifier is reused with different content | Reject it rather than apply a different action or replay unrelated content. |
| A completion write fails | Roll back todos, workflow changes, and the submission result together. |
| Another user's workflow identifier is submitted | Preserve owner-scoped access without exposing its contents. |
| A response arrives after sign-out or after a newer response | Do not populate the wrong user's cache or regress a newer revision. |
| An older client encounters an unsupported contract | Use the documented safe fallback without submitting a guessed action. |

Use real PostgreSQL integration tests for transactions, uniqueness, and races, plus component tests for recovery. Disabling a button is helpful interaction design, not a substitute for server correctness. Keep full cross-platform automation in Phase 12.

**Experiment:** commit confirmation, discard its response, retry with the same identifier, and verify the exact intended todo count. Then race distinct actions against the same revision and verify one accepted transition.

**Guide after implementation:** `docs/guides/09-workflow-reliability.md`.

## Phase 10: LLM-assisted planning with Python and OpenRouter

Extend "Help me plan a task" with a "Suggest todos" action. A user enters "birthday party"; Python calls OpenRouter and validates a structured list of suggested titles before saving it as an owner-scoped proposal. The user can edit or remove suggestions and confirm through the existing workflow. Todos are created only on confirmation. Keep the existing deterministic frontend screens so learners can isolate the model integration from the next phase's UI protocol.

Use a model/provider combination that supports the chosen JSON Schema response format, then apply Pydantic and existing title/count validation in Python. Schema compliance does not establish relevance or authorize writes. Keep credentials in backend configuration, send only the context needed for the request, bound input/output and request duration, and provide a clear failure state with manual entry or explicit retry. Do not log credentials or complete prompts by default.

Keep the external call outside a long-running database transaction or row lock. Apply its validated result only if the owner, workflow revision, and active request still match; late results must not overwrite newer edits or revive cancelled workflows. Persist accepted suggestions so refresh/resume does not trigger another paid call. Phase 9's database idempotency does not guarantee exactly-once provider execution or billing; the spec must define request identity and retry behavior explicitly.

Use mocked provider responses for normal tests, including malformed output, excessive titles, timeouts, stale results, and confirmation-only writes. A separately documented manual live-provider smoke check can verify the chosen model, without making CI depend on paid calls or exact generated wording.

**Experiment:** simulate a timeout or invalid output, recover through manual entry or explicit retry, then refresh a successful draft and verify that its saved suggestions remain available without another model call.

**Guide after implementation:** `docs/guides/10-llm-assisted-planning.md`.

## Phase 11: interactive AI workflows with assistant-ui and AG-UI

Build on the same Python/OpenRouter integration. Register a small set of frontend interactions: a clarification form and an editable suggestion checklist. The agent chooses a supported interaction and supplies validated arguments; the user supplies missing context or reviews proposed todos. Python validates every resulting business action against the authenticated workflow before saving anything.

Teach the layers explicitly: assistant-ui provides frontend hooks and tool rendering; AG-UI carries agent events and interactions; the existing Python service and PostgreSQL remain authoritative for accepted workflow state. Begin with a fixed event fixture and registered component, then connect the model's tool selection. Rendering, replaying, or reconnecting to an interaction must not itself create todos.

The [Phase 11 design](superpowers/specs/2026-09-10-agentic-ui-design.md) uses assistant-ui React Native primitives and the AG-UI runtime adapter connected directly to the existing FastAPI server. The isolated [compatibility spike](../spikes/assistant-ui-ag-ui/README.md) validated tool rendering, tool-result continuation, streaming, and cancellation on Expo web and iOS Simulator. Integrate its pinned versions and secure-random initialization, then verify real session authentication, Python event encoding, and workflow recovery in the application. No separate Node backend or hosted UI service is required. Keep OpenRouter calls and business rules in Python; full application acceptance remains pending.

Map run/tool identities to the existing workflow and step/revision boundaries. Reconcile agent events with authoritative API snapshots rather than allowing agent state, TanStack Query, and persisted workflow state to become competing sources of truth. Define reconnect, cancellation, late-event, unknown-tool, malformed-argument, and sign-out behavior. Retain a recoverable manual workflow when the agent interaction fails.

Use deterministic event fixtures and component tests for clarification, editing, approval, accessibility, and recovery. Add backend checks proving that unsupported tools, stale actions, and repeated confirmation cannot bypass authorization or create duplicate todos.

**Experiment:** compare "birthday party" with "weekend hiking trip" and observe different context requests through supported components; inject an unsupported tool call and verify a safe fallback without a business transition.

**Guide after implementation:** `docs/guides/11-agentic-ui.md`.

### Optional later exercise: A2UI

A2UI describes declarative UI; AG-UI carries agent/application interactions. They can be combined, but A2UI is not required for Phase 11. A later exercise can compare agent-selected registered components with model-composed layouts from an approved A2UI catalog. Keep this separate from the core lesson and verify renderer/platform compatibility before adopting it.

### Integration references

- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [assistant-ui React Native](https://www.assistant-ui.com/docs/react-native)
- [assistant-ui AG-UI quickstart](https://www.assistant-ui.com/docs/runtimes/ag-ui/quickstart)
- [AG-UI and generative UI specifications](https://docs.ag-ui.com/concepts/generative-ui-specs)

## Phase 12 and cloud-curriculum follow-through

Phase 12 retains the core todo E2E journey and adds a small guided-creation set: the simple path, the breakdown path, and one resume/recovery journey on the supported platforms. Add a thin AI-assisted clarification/review/confirmation journey using deterministic provider and AG-UI event fixtures. Keep exhaustive branches and races in lower layers. Retain the planned scheduling boundary: web E2E on pull requests and iOS Simulator E2E on `main` once those suites exist.

The pre-Phase 12 security baseline scans Git history with Gitleaks, blocks high/critical dependency vulnerabilities with Trivy, and runs CodeQL over Python and JavaScript/TypeScript. It must not send real provider credentials to pull-request code or turn paid model calls into CI dependencies. After the workflow has run on GitHub, protect `main` with required `Secrets` and `Dependencies` checks plus a CodeQL code-scanning rule set to **High or higher**.

Phases 13–19 establish the deployed environment and delivery path without changing workflow authority: Cloud Run hosts the API, Cloud SQL stores workflow state, Cloudflare Pages hosts the static web application, Terraform owns Google infrastructure, and the delivery pipeline retains the existing test and acceptance gates.

Phase 20 moves suggestion generation to Cloud Tasks. Reuse the existing persisted request identity and processing state: the API reserves and enqueues work, an authenticated Cloud Run handler eventually records success or failure, and the client continues polling the authoritative saved result. Test duplicate delivery, stale/cancelled work, retry exhaustion, and the gap between database idempotency and provider billing. Queues, external side effects, and background orchestration remain outside Phases 7–9.

Phase 21 owns measured workflow and provider hardening. Prefer correlation identifiers, state/transition names, durations, and error categories over logging answers, todo titles, session tokens, or entire request bodies. Add per-user usage limits, provider cost/latency/error diagnostics, and explicit retention/redaction policies for AI context and event data.

Phase 23 specifies treatment of in-flight definitions, unsupported clients, cancelled/abandoned drafts, migrations, rollback, and recovery drills before making production-readiness claims. Later Cloud Storage, Pub/Sub/Eventarc, BigQuery, and notification phases must preserve the same owner scope, minimal-data policy, idempotent consumption, and authoritative database boundaries.

## Documentation and checkpoint acceptance

This curriculum revision changes documentation only. It must not claim that new endpoints, templates, tests, guides, or checkpoints already exist. Do not change the current Phase 6 implementation status or renumber existing guides and tags.

Before each implementation phase, approve its design spec with a transition table, state-ownership boundaries, request/response examples, error and compatibility behavior, accessibility expectations, tests, and observable acceptance criteria. After implementation, write the numbered guide from the validated feature, run the required checks and supported-platform acceptance, and follow the existing integration and checkpoint release process. A curriculum addition by itself does not earn a feature checkpoint tag.
