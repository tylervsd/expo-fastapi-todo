# Curriculum roadmap

This roadmap is provisional. Every phase receives its own approved spec before implementation; the spec defines goals, non-goals, user-visible behavior, contracts, error cases, accessibility considerations, and the intended testing-pyramid layer. The repository evolves on `main` with numbered guides and annotated checkpoint tags rather than permanent phase branches or duplicate repositories.

Phase numbers start at 0 to match the README, existing guides, and checkpoint convention. This revision expands the curriculum to twelve phases (0-11); it does not renumber existing guides or tags. The implemented checkpoint remains Phase 6. Phases 7-11 below are planned, not completed features.

Phases 7-9 build one guided-todo creation feature to teach backend-owned state transitions, server-directed screen templates, and reliable resumption. The existing quick-add and `/todos` contract remain available. See the [workflow learning plan](workflow-learning-plan.md) for the proposed scenario, API examples, state ownership, failure cases, and phase exercises. That plan informs each future approved phase spec; it is not a substitute for the spec gate or an implementation guide.

## 0. Mac developer environment

- **Learning goal:** Understand tool ownership, exact version pins, read-only verification, and safe troubleshooting on the reference Mac.
- **Visible outcome:** A learner can prepare macOS 26.6.2 on Apple Silicon, pass the doctor, and complete the manual acceptance journey.
- **New technology/pattern:** Homebrew, Volta, Corepack, pnpm, uv, Docker Desktop, GitHub CLI, and a modular POSIX doctor.
- **Testing-pyramid layer introduced:** Static checks and unit tests for shell contracts, with a small integration check and one manual acceptance journey.
- **Spec gate:** This phase received an approved spec before implementation; future maintenance changes also require an explicit approved spec when behavior changes.

## 1. Project foundation

- **Learning goal:** Establish the monorepo shape, Expo targets, FastAPI service boundary, local orchestration, and baseline CI.
- **Visible outcome:** A browser and iOS shell plus a FastAPI health endpoint run locally with a repeatable CI quality gate.
- **New technology/pattern:** Expo web/iOS, FastAPI, separate host-process service boundaries, and workflow checks.
- **Testing-pyramid layer introduced:** First application unit/component tests, in-process API contract tests, and mobile component tests.
- **Spec gate:** Before implementation, this phase gets its own approved spec covering the app/service contracts and CI acceptance criteria.

## 2. Local todo experience

- **Learning goal:** Build an accessible todo interaction without coupling the UI to a backend.
- **Visible outcome:** A learner can view, add, complete, and filter local todos on web and iOS.
- **New technology/pattern:** React Native components, local state, forms, validation, and accessibility semantics.
- **Testing-pyramid layer introduced:** Many component and interaction tests around user-visible state transitions.
- **Spec gate:** This phase received its approved spec before implementation.

## 3. API contract and vertical slice

- **Learning goal:** Connect one todo journey across a typed client and validated server contract.
- **Visible outcome:** The app creates and reads todos through FastAPI with generated OpenAPI documentation and clear errors.
- **New technology/pattern:** REST semantics, Pydantic validation, OpenAPI generation, and a typed TypeScript client.
- **Testing-pyramid layer introduced:** Contract and API integration tests, while keeping most behavior in unit/component tests.
- **Spec gate:** This phase received its approved spec before implementation.

## 4. Persistence

- **Learning goal:** Persist data reliably and explain transactions and migrations.
- **Visible outcome:** Todos survive service restarts in a local PostgreSQL database.
- **New technology/pattern:** PostgreSQL, SQLAlchemy, Alembic migrations, transactions, and repository boundaries.
- **Testing-pyramid layer introduced:** Focused database integration tests supporting a larger unit layer.
- **Spec gate:** This phase received its approved spec before implementation.

## 5. Complete CRUD and resilient server state

- **Learning goal:** Finish the todo workflow and make network state understandable under loading, empty, error, retry, and offline-like conditions.
- **Visible outcome:** Users can edit and delete todos, with robust loading and error states and justified optimistic updates where useful.
- **New technology/pattern:** Server-state caching, retries, invalidation, resilient UI state, and explicit consistency tradeoffs.
- **Testing-pyramid layer introduced:** More component and integration coverage for failure states, with only critical journeys reserved for E2E.
- **Spec gate:** This phase received its approved spec before implementation, covering CRUD semantics, cache policy, retries, and optimistic-update rollback behavior.

## 6. Authentication and authorization

- **Learning goal:** Protect user data and explain identity, token handling, and authorization boundaries.
- **Visible outcome:** Users sign in and see only their own protected todos on web and iOS.
- **New technology/pattern:** Secure token handling, authenticated API requests, protected navigation, and per-user authorization.
- **Testing-pyramid layer introduced:** Unit and integration tests for identity boundaries, plus a small set of authenticated critical-path tests.
- **Spec gate:** This phase received its approved spec before implementation, covering sessions, tokens, protected operations, and failure behavior.

## 7. Backend workflow modeling

- Learning goal: Separate workflow states, user actions, collected context, and transition rules from HTTP handling, persistence, and rendering.
- Visible outcome: A signed-in user can start guided todo creation, take a branching path, review proposed todos, and confirm or cancel. Unfinished workflows persist as owner-scoped drafts; todos are created only on confirmation.
- New technology/pattern: Explicit Python transition logic, a service/domain boundary, persisted workflow instances, and command-oriented API operations. Begin with dedicated frontend screens rather than a generic renderer.
- Testing-pyramid layer introduced: Table-driven transition unit tests and targeted API/PostgreSQL tests for saved progress, validation, ownership, cancellation, and commit/rollback behavior.
- Learning experiment: Submit an action that is invalid in the current state and verify that the backend rejects it without advancing the workflow or creating todos.
- Non-goals: A general-purpose workflow engine, arbitrary JSON layouts, a new navigation library, background workers, and concurrency/retry guarantees that belong to Phase 9.
- Spec gate: Before implementation, approve a transition table, state-ownership model, command/response examples, persistence boundary, accessibility behavior, error cases, and acceptance criteria.

## 8. Server-directed screens and reusable templates

- Learning goal: Let the backend select the next supported screen and its content without putting business branching rules in React.
- Visible outcome: Two consecutive questions reuse one yes/no template with different content, and another transition selects a task-breakdown or review screen. The client can reconstruct the current view after a refresh.
- New technology/pattern: A separate backend presentation mapper, discriminated Pydantic response models, matching TypeScript types with runtime validation, a small template registry, and a distinct identity for each issued step.
- Testing-pyramid layer introduced: API contract tests and component tests for template selection, accessibility, submitting state, draft reset between questions, and unsupported-template handling.
- Learning experiment: Add another yes/no question and its branching rule in the backend without adding frontend workflow branching or a new screen component.
- Non-goals: Downloading executable UI, accepting arbitrary navigation URLs, server-defined layout trees, optimistic workflow advancement, and requiring Expo Router. New template types still need client support.
- Spec gate: Before implementation, approve the supported view/action contracts, state-to-view mapping, client rendering boundary, step identity rules, and unknown-contract fallback.

## 9. Reliable, resumable workflows

- Learning goal: Advance a workflow correctly despite interrupted responses, duplicate submissions, stale answers, application restarts, and competing devices.
- Visible outcome: A user can find and resume unfinished workflows on web or iOS, retry an interrupted submission, and confirm without creating duplicate todos. A conflicting action returns a recoverable stale-step result.
- New technology/pattern: Atomically enforced revisions, submission idempotency, database uniqueness constraints, transactional completion, workflow-definition versioning, and explicit cache reconciliation. Build on the uncertain-write lessons from Phase 5.
- Testing-pyramid layer introduced: PostgreSQL integration tests for retry races, stale revisions, completion rollback, and ownership, with component tests for recovery. Reserve full cross-platform automation for Phase 10.
- Learning experiment: Commit a confirmation but lose its response, retry with the same submission identifier, and verify one completion result and one intended set of todos. Race different submissions against the same revision and verify only one advances.
- Non-goals: Offline-first synchronization, event sourcing, distributed exactly-once processing, external side effects, and background orchestration.
- Spec gate: Before implementation, approve the transaction boundary, idempotency scope and payload checks, atomic conflict behavior, active-workflow discovery, version compatibility, and failure/recovery matrix.

## 10. Cross-platform E2E

- **Learning goal:** Validate the smallest set of critical user journeys across the browser and iOS Simulator.
- **Visible outcome:** A signed-in user can complete the core todo journey in web and iOS test environments.
- **New technology/pattern:** Browser E2E and iOS Simulator E2E with stable fixtures and environment-aware diagnostics.
- **Testing-pyramid layer introduced:** Thin end-to-end coverage at the top of the pyramid; web E2E runs on pull requests and iOS E2E runs on `main` once those suites exist.
- **Spec gate:** Before implementation, this phase gets its own approved spec for journeys, fixtures, platform differences, and CI scheduling.

## 11. Production hardening

- **Learning goal:** Prepare a maintainable application for operational use and deliberate upgrades.
- **Visible outcome:** Configuration, secrets, structured logs, observability, security checks, deployment concepts, and upgrade maintenance are documented and exercised.
- **New technology/pattern:** Environment management, observability, security automation, deployment workflows, and dependency maintenance.
- **Testing-pyramid layer introduced:** Static security checks and targeted integration/acceptance checks, preserving thin E2E coverage for critical journeys.
- **Spec gate:** Before implementation, this phase gets its own approved spec for operational requirements, threat boundaries, deployment acceptance, and rollback expectations.
