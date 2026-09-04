# Curriculum roadmap

This roadmap is provisional. Every phase receives its own approved spec before implementation; the spec defines goals, non-goals, user-visible behavior, contracts, error cases, accessibility considerations, and the intended testing-pyramid layer. The repository evolves on `main` with numbered guides and annotated checkpoint tags rather than permanent phase branches or duplicate repositories.

## 1. Mac developer environment

- **Learning goal:** Understand tool ownership, exact version pins, read-only verification, and safe troubleshooting on the reference Mac.
- **Visible outcome:** A learner can prepare macOS 26.6.2 on Apple Silicon, pass the doctor, and complete the manual acceptance journey.
- **New technology/pattern:** Homebrew, Volta, Corepack, pnpm, uv, Docker Desktop, GitHub CLI, and a modular POSIX doctor.
- **Testing-pyramid layer introduced:** Static checks and unit tests for shell contracts, with a small integration check and one manual acceptance journey.
- **Spec gate:** This phase received an approved spec before implementation; future maintenance changes also require an explicit approved spec when behavior changes.

## 2. Project foundation

- **Learning goal:** Establish the monorepo shape, Expo targets, FastAPI service boundary, local orchestration, and baseline CI.
- **Visible outcome:** A browser and iOS shell plus a FastAPI health endpoint run locally with a repeatable CI quality gate.
- **New technology/pattern:** Expo web/iOS, FastAPI, Docker Compose service boundaries, and workflow checks.
- **Testing-pyramid layer introduced:** First application unit/component tests and a service integration smoke test.
- **Spec gate:** Before implementation, this phase gets its own approved spec covering the app/service contracts and CI acceptance criteria.

## 3. Local todo experience

- **Learning goal:** Build an accessible todo interaction without coupling the UI to a backend.
- **Visible outcome:** A learner can view, add, complete, and filter local todos on web and iOS.
- **New technology/pattern:** React Native components, local state, forms, validation, and accessibility semantics.
- **Testing-pyramid layer introduced:** Many component and interaction tests around user-visible state transitions.
- **Spec gate:** Before implementation, this phase gets its own approved spec with behavior, accessibility, and state acceptance criteria.

## 4. API contract and vertical slice

- **Learning goal:** Connect one todo journey across a typed client and validated server contract.
- **Visible outcome:** The app creates and reads todos through FastAPI with generated OpenAPI documentation and clear errors.
- **New technology/pattern:** REST semantics, Pydantic validation, OpenAPI generation, and a typed TypeScript client.
- **Testing-pyramid layer introduced:** Contract and API integration tests, while keeping most behavior in unit/component tests.
- **Spec gate:** Before implementation, this phase gets its own approved spec for endpoints, schemas, error responses, and client/server acceptance.

## 5. Persistence

- **Learning goal:** Persist data reliably and explain transactions and migrations.
- **Visible outcome:** Todos survive service restarts in a local PostgreSQL database.
- **New technology/pattern:** PostgreSQL, SQLAlchemy, Alembic migrations, transactions, and repository boundaries.
- **Testing-pyramid layer introduced:** Focused database integration tests supporting a larger unit layer.
- **Spec gate:** Before implementation, this phase gets its own approved spec for data models, migrations, transaction behavior, and recovery cases.

## 6. Complete CRUD and resilient server state

- **Learning goal:** Finish the todo workflow and make network state understandable under loading, empty, error, retry, and offline-like conditions.
- **Visible outcome:** Users can edit and delete todos, with robust loading and error states and justified optimistic updates where useful.
- **New technology/pattern:** Server-state caching, retries, invalidation, resilient UI state, and explicit consistency tradeoffs.
- **Testing-pyramid layer introduced:** More component and integration coverage for failure states, with only critical journeys reserved for E2E.
- **Spec gate:** Before implementation, this phase gets its own approved spec for CRUD semantics, cache policy, retries, and optimistic-update rollback behavior.

## 7. Authentication and authorization

- **Learning goal:** Protect user data and explain identity, token handling, and authorization boundaries.
- **Visible outcome:** Users sign in and see only their own protected todos on web and iOS.
- **New technology/pattern:** Secure token handling, authenticated API requests, protected navigation, and per-user authorization.
- **Testing-pyramid layer introduced:** Unit and integration tests for identity boundaries, plus a small set of authenticated critical-path tests.
- **Spec gate:** Before implementation, this phase gets its own approved security-conscious spec for sessions, tokens, protected operations, and failure behavior.

## 8. Cross-platform E2E

- **Learning goal:** Validate the smallest set of critical user journeys across the browser and iOS Simulator.
- **Visible outcome:** A signed-in user can complete the core todo journey in web and iOS test environments.
- **New technology/pattern:** Browser E2E and iOS Simulator E2E with stable fixtures and environment-aware diagnostics.
- **Testing-pyramid layer introduced:** Thin end-to-end coverage at the top of the pyramid; web E2E runs on pull requests and iOS E2E runs on `main` once those suites exist.
- **Spec gate:** Before implementation, this phase gets its own approved spec for journeys, fixtures, platform differences, and CI scheduling.

## 9. Production hardening

- **Learning goal:** Prepare a maintainable application for operational use and deliberate upgrades.
- **Visible outcome:** Configuration, secrets, structured logs, observability, security checks, deployment concepts, and upgrade maintenance are documented and exercised.
- **New technology/pattern:** Environment management, observability, security automation, deployment workflows, and dependency maintenance.
- **Testing-pyramid layer introduced:** Static security checks and targeted integration/acceptance checks, preserving thin E2E coverage for critical journeys.
- **Spec gate:** Before implementation, this phase gets its own approved spec for operational requirements, threat boundaries, deployment acceptance, and rollback expectations.
