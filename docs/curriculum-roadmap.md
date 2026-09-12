# Curriculum roadmap

This roadmap is provisional. Every phase receives its own approved spec before implementation; the spec defines goals, non-goals, user-visible behavior, contracts, error cases, accessibility considerations, and the intended testing-pyramid layer. The repository evolves on `main` with numbered guides and annotated checkpoint tags rather than permanent phase branches or duplicate repositories.

Phase numbers start at 0 to match the README, existing guides, and checkpoint convention. This revision expands the curriculum to 28 phases (0–27); it does not renumber existing guides or tags. The implementation on `main` includes Phase 11 and its acceptance follow-up. Merge status does not complete outstanding manual acceptance: see the numbered guides, especially Guide 09's partial iOS record. Phase 12 is implemented with local-runs + web-CI acceptance ([guide](guides/12-cross-platform-e2e.md)); native CI is manual-only after environment-attributed failures on free-tier runners. Phases 13–27 are provisional cloud curriculum.

Phases 7-9 build one guided-todo creation feature to teach backend-owned state transitions, server-directed screen templates, and reliable resumption. Phases 10 and 11 extend that feature with validated LLM suggestions and interactive agent-selected components, respectively. This keeps model integration separate from the agent/UI protocol lesson. The existing quick-add and `/todos` contract remain available. See the [workflow learning plan](workflow-learning-plan.md) for the proposed scenario, API examples, state ownership, failure cases, and phase exercises. That plan informs each future approved phase spec; it is not a substitute for the spec gate or an implementation guide.

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
- Spec gate: This phase received its approved spec before implementation, covering the transition table, state-ownership model, command/response examples, persistence boundary, accessibility behavior, error cases, and acceptance criteria. Implementation is merged; the phase guide still records pending web and iOS acceptance observations.

## 8. Server-directed screens and reusable templates

- Learning goal: Let the backend select the next supported screen and its content without putting business branching rules in React.
- Visible outcome: Two consecutive questions reuse one yes/no template with different content, and another transition selects a task-breakdown or review screen. The client can reconstruct the current view after a refresh.
- New technology/pattern: A separate backend presentation mapper, discriminated Pydantic response models, matching TypeScript types with runtime validation, a small template registry, and a distinct identity for each issued step.
- Testing-pyramid layer introduced: API contract tests and component tests for template selection, accessibility, submitting state, draft reset between questions, and unsupported-template handling.
- Learning experiment: Add another yes/no question and its branching rule in the backend without adding frontend workflow branching or a new screen component.
- Non-goals: Downloading executable UI, accepting arbitrary navigation URLs, server-defined layout trees, optimistic workflow advancement, and requiring Expo Router. New template types still need client support.
- Spec gate: This phase received its approved spec before implementation, covering the supported view/action contracts, state-to-view mapping, client rendering boundary, step identity rules, and unknown-contract fallback. Implementation is merged; the phase guide still records pending web and iOS acceptance observations.

## 9. Reliable, resumable workflows

- Learning goal: Advance a workflow correctly despite interrupted responses, duplicate submissions, stale answers, application restarts, and competing devices.
- Visible outcome: A user can find and resume unfinished workflows on web or iOS, retry an interrupted submission, and confirm without creating duplicate todos. A conflicting action returns a recoverable stale-step result.
- New technology/pattern: Atomically enforced revisions, submission idempotency, database uniqueness constraints, transactional completion, workflow-definition versioning, and explicit cache reconciliation. Build on the uncertain-write lessons from Phase 5.
- Testing-pyramid layer introduced: PostgreSQL integration tests for retry races, stale revisions, completion rollback, and ownership, with component tests for recovery. Reserve full cross-platform automation for Phase 12.
- Learning experiment: Commit a confirmation but lose its response, retry with the same submission identifier, and verify one completion result and one intended set of todos. Race different submissions against the same revision and verify only one advances.
- Non-goals: Offline-first synchronization, event sourcing, distributed exactly-once processing, external side effects, and background orchestration.
- Spec gate: Before implementation, approve the transaction boundary, idempotency scope and payload checks, atomic conflict behavior, active-workflow discovery, version compatibility, and failure/recovery matrix.
- Implementation status: Merged in PR #6 (`12cd7f5`). Guide 09 records the implementation verification and observed web acceptance. iOS acceptance is partial, including declined breakdown, cancellation, restart/resume, and lost-action retry; see its acceptance table for all remaining gaps.

## 10. LLM-assisted planning with Python and OpenRouter

- Learning goal: Integrate an LLM call into an existing Python service and treat generated output as an untrusted proposal.
- Visible outcome: A signed-in user enters a goal such as "birthday party", requests suggested todos, edits or removes suggestions, and confirms creation through the existing workflow.
- New technology/pattern: Server-side OpenRouter requests, a compatible model's structured output, Pydantic validation, bounded requests, saved proposals, and explicit provider failure handling. Keep the existing deterministic screens for this lesson.
- Testing-pyramid layer introduced: Unit and API tests with mocked provider responses for valid suggestions, malformed output, timeouts, ownership, and stale results. Normal CI does not require provider credentials or paid model calls.
- Learning experiment: Return invalid model output or simulate a timeout and verify that the draft remains recoverable and no todos are created. Resume a saved suggestion set without generating it again.
- Non-goals: Agent frameworks, streaming UI, background workers, autonomous todo creation, and model-generated layouts. API keys stay in Python-side configuration; validation and bounded usage begin here rather than waiting for hardening.
- Spec gate: Before implementation, approve the provider/model contract, prompt and output limits, edit/review behavior, request timeout and retry policy, stale-result handling, data sent to the provider, and web/iOS acceptance criteria.
- Implementation status: Merged in PR #7 (`e1e2cac`). The PostgreSQL-backed API suite (398/398), mobile suite (375/375), quality gate, and one configured `openrouter/free` structured-output smoke passed on 2026-09-10. Guide 10 records these results and leaves interactive web and iOS acceptance rows unobserved; merge status does not complete those acceptance rows.

## 11. Interactive AI workflows with assistant-ui and AG-UI

- Implementation status: Merged in PR #8 (`e99eca0`), with the acceptance follow-up in `61fb30c`. [Guide 11](guides/11-agentic-ui.md) records 501 passing API tests, 522 passing mobile tests, 14 live provider calls, and completed web and iOS interactive journeys; its remaining acceptance limits are still explicit.

- Learning goal: Connect a Python agent to interactive frontend components through AG-UI events while preserving backend authority over workflow state and persistence.
- Visible outcome: The agent requests relevant context through a registered clarification form, presents an editable suggestion checklist, and waits for user confirmation before the existing backend creates todos.
- New technology/pattern: assistant-ui React Native primitives and tool-result rendering, AG-UI event transport, typed tool arguments, and human-in-the-loop interaction. Reuse Phase 10's Python/OpenRouter integration and registered application components.
- Testing-pyramid layer introduced: Recorded-event contract and component tests for form/tool rendering, invalid arguments, interrupted runs, cancellation, and confirmation, plus targeted backend tests for ownership and duplicate-write prevention.
- Learning experiment: Change the goal and observe the agent select a relevant supported interaction; reject an unsupported tool or stale confirmation without advancing the workflow.
- Non-goals: Arbitrary generated code or layouts, replacing the workflow domain with chat state, and requiring A2UI. A2UI is an optional later exercise in declarative UI composition; it can complement AG-UI.
- Integration gate: Use the validated assistant-ui/AG-UI versions and existing FastAPI server as the sole backend service. Carry the native secure-random initialization into the app, then verify real session authentication, Python event encoding, tool contracts, state reconciliation, accessibility, and recovery on web and iOS. Keep model calls and business logic in Python. Android and deployed application acceptance are not established by the spike.

## Cross-phase security baseline before Phase 12

- **Learning goal:** Detect common security mistakes before cloud credentials or production data enter the repository.
- **Visible outcome:** Pull requests, `main`, and a scheduled run scan Git history for secrets, lockfiles for known vulnerable dependencies, and Python/TypeScript for common code-level weaknesses.
- **New technology/pattern:** GitHub secret scanning and push protection where available, Gitleaks for Git-history secret scanning, Trivy for high/critical dependency vulnerabilities in `pnpm-lock.yaml` and `uv.lock`, and default CodeQL queries.
- **Enforcement:** A real credential always fails the gate. Initially fail dependency and code scans only on actionable high or critical findings; every exception needs a reason, owner, and expiry date.
- **Later expansion:** Phase 14 scans the built container, Phase 18 scans Terraform, Phase 19 makes the checks deployment gates, and Phase 23 reviews Google Artifact Analysis and Security Command Center findings.
- **Status:** Implemented in `.github/workflows/security.yml`; activate the documented `main` ruleset after the workflow's first GitHub run makes its checks selectable.

## 12. Cross-platform E2E

- **Learning goal:** Validate the smallest set of critical user journeys across the browser and iOS Simulator.
- **Visible outcome:** A signed-in user can complete core todo, guided creation, and AI-assisted review/confirmation journeys in web and iOS test environments using deterministic provider/event fixtures.
- **New technology/pattern:** Browser E2E and iOS Simulator E2E with stable fixtures and environment-aware diagnostics.
- **Testing-pyramid layer introduced:** Thin end-to-end coverage at the top of the pyramid; web E2E runs on pull requests and iOS E2E runs on `main` once those suites exist.
- **Spec gate:** Before implementation, this phase gets its own approved spec for journeys, fixtures, platform differences, and CI scheduling.
- **Status:** In progress on `codex/phase-12-cross-platform-e2e` ([guide](guides/12-cross-platform-e2e.md)). Toolchain, isolated harness, four browser and four native journeys, and platform CI are implemented; local double-runs pass on both platforms. Remote acceptance (browser PR job, native CI run) is pending. No checkpoint until that CI evidence exists.

## 13. Google Cloud foundations and cost safety

- **Learning goal:** Understand the Google Cloud resource hierarchy and create a safe learning environment before deploying application code.
- **Visible outcome:** A learner can create and identify a sandbox project, configure `gcloud` and Application Default Credentials, enable APIs deliberately, select a region, inspect quotas, set labels, create a budget, and clean up resources.
- **New technology/pattern:** Projects, billing accounts, regions and zones, API enablement, IAM vocabulary, quotas, labels, Cloud Shell, `gcloud`, and budget alerts or supported spend caps.
- **Verification emphasis:** Read-only inventory commands, billing-scope checks, and a cleanup checklist prove which project and principal each command targets.
- **Learning experiment:** Switch the active `gcloud` project to a harmless second configuration and verify that the guard commands prevent provisioning into the wrong project.
- **Non-goals:** Organization-wide policy, shared VPC, production IAM, Terraform, and application deployment.
- **Spec gate:** Approve the account/billing prerequisites, cost ceiling, supported region, resource naming, cleanup behavior, and commands that require explicit learner confirmation.

## 14. Containers, Artifact Registry, and Cloud Run

- **Learning goal:** Package FastAPI as a portable container and understand Cloud Run's request-driven execution model.
- **Visible outcome:** The same API image runs locally and from Artifact Registry, and a public Cloud Run URL returns the existing health response.
- **New technology/pattern:** Minimal container images, `.dockerignore`, Artifact Registry, Cloud Run services, `$PORT`, stateless filesystems, request concurrency, timeouts, cold starts, min/max instances, revisions, and request-based billing.
- **Verification emphasis:** Container build checks, local smoke tests, deployed health checks, startup failure diagnosis, and an initial container vulnerability scan.
- **Learning experiment:** Scale the service to zero, observe a cold request, deploy a second revision with no traffic, and inspect both revisions without involving the database.
- **Non-goals:** Cloud SQL, production secrets, custom domains, load balancers, Kubernetes, and automated delivery.
- **Spec gate:** Approve the base image, runtime user, exposed port, image naming, region, public-ingress boundary, resource limits, health semantics, and cleanup procedure.

## 15. Service identities and Secret Manager

- **Learning goal:** Separate human, deployment, runtime, and service-to-service identities while keeping credentials out of images and source control.
- **Visible outcome:** Cloud Run reads the OpenRouter credential from Secret Manager through a dedicated least-privilege runtime service account; an unauthorized identity is demonstrably denied.
- **New technology/pattern:** Service accounts as principals and resources, predefined IAM roles, resource-level bindings, Application Default Credentials, Secret Manager versions, mounted versus environment secrets, and audit logs.
- **Verification emphasis:** Positive and negative permission checks, secret-redaction tests, rotation without source changes, and confirmation that Terraform and application logs contain no secret values.
- **Learning experiment:** Remove the runtime identity's secret accessor role, observe the controlled deployment or startup failure, restore the binding, and rotate to a new secret version.
- **Non-goals:** Cloud KMS, long-lived service-account keys, organization policy, custom IAM roles, and storing frontend secrets.
- **Spec gate:** Approve the identity matrix, exact roles and resource scopes, secret injection method, rotation/revocation path, audit expectations, and recovery procedure.

## 16. Cloud SQL for PostgreSQL and migrations

- **Learning goal:** Move the existing PostgreSQL boundary to a managed database and relate application concurrency to finite database connections.
- **Visible outcome:** The deployed API persists todos in Cloud SQL, applies Alembic migrations through a finite Cloud Run Job, and recovers data from a tested backup or point-in-time recovery exercise.
- **New technology/pattern:** Cloud SQL for PostgreSQL, Cloud SQL connectors or authenticated connections, connection pooling, Cloud Run concurrency and instance caps, Cloud Run Jobs, automated backups, point-in-time recovery, maintenance windows, and zonal versus regional availability.
- **Verification emphasis:** Migration checks, deployed database integration tests, pool exhaustion behavior, restart recovery, backup verification, and a restore drill against non-production data.
- **Learning experiment:** Configure an unsafe Cloud Run/database connection combination, observe the failure mode under bounded load, then set defensible pool, concurrency, and maximum-instance limits.
- **Non-goals:** Read replicas, cross-region failover, sharding, Spanner, production-scale high availability, and analytics queries against the application database.
- **Spec gate:** Approve PostgreSQL compatibility, region/availability choice, connectivity, credentials, pool budget, migration ownership, backup retention, recovery objective, deletion protection, and cost ceiling.

## 17. Cloudflare Pages and the hosted web application

- **Learning goal:** Deploy Expo's static web output separately from the API and understand the browser boundary between two cloud providers.
- **Visible outcome:** Cloudflare Pages builds the web application from the monorepo, preview and production deployments use the intended Cloud Run URL, and a user completes an authenticated deployed journey through a custom web origin.
- **New technology/pattern:** Expo static export, Pages Git integration, monorepo build roots, build-time `EXPO_PUBLIC_` configuration, preview deployments, custom domains, DNS/TLS, redirects, cache behavior, security headers, and production CORS allowlists.
- **Verification emphasis:** Static export checks, preview smoke tests, production CORS tests, deep-link behavior, header inspection, cache validation, and deployed critical-path E2E.
- **Learning experiment:** Point a preview build at the sandbox API, confirm its origin is rejected by the production allowlist, then add the explicit preview policy without using a wildcard.
- **Non-goals:** Pages Functions, Cloudflare Workers, server-side rendering, frontend secrets, Cloud CDN, and moving the FastAPI backend to Cloudflare.
- **Spec gate:** Approve the Pages build command/output, environment mapping, allowed origins, preview policy, domain/DNS ownership, security headers, rollback behavior, and deployed acceptance journey.

## 18. Terraform and reproducible Google infrastructure

- **Learning goal:** Convert the manually understood Google environment into reviewable, reproducible infrastructure as code.
- **Visible outcome:** Terraform adopts or recreates the sandbox's enabled APIs, registry, identities, IAM, secret containers, Cloud Run service and job, Cloud SQL resources, budgets, and basic monitoring, then produces an empty plan against the intended configuration.
- **New technology/pattern:** Terraform CLI, pinned Google providers, resources, data sources, variables, outputs, imports, drift, plans, applies, dependency graphs, a versioned and locked GCS state backend, and deletion protection.
- **Verification emphasis:** `terraform fmt -check`, `terraform validate`, speculative plans, an infrastructure misconfiguration scan, drift detection, state recovery, and guarded destruction of disposable resources.
- **Learning experiment:** Change one harmless Cloud Run setting in the console, observe the Terraform drift, reconcile it in code, and return to an empty plan.
- **Non-goals:** Premature reusable modules, Terraform-managed secret values, committing state or saved plans, Terraform workspaces as an environment-isolation shortcut, and Cloudflare infrastructure as code.
- **Spec gate:** Approve the documented state-bucket bootstrap boundary, provider/version policy, resource ownership, import strategy, state access and recovery, secret handling, deletion guards, environment layout, and drift policy.

## 19. Continuous delivery, revisions, and rollback

- **Learning goal:** Deliver application and infrastructure changes through one auditable pipeline without long-lived Google credentials or competing deployment owners.
- **Visible outcome:** GitHub Actions tests and scans the repository, builds an immutable image, authenticates through Workload Identity Federation, runs a reviewed Terraform plan, applies migrations, deploys by image digest, smoke-tests the revision, and can roll back.
- **New technology/pattern:** GitHub OIDC, Workload Identity Federation, least-privilege deploy identities, immutable image digests, protected environments, plan/apply separation, Cloud Run traffic management, release metadata, and rollback.
- **Verification emphasis:** Required status checks, security gates, no-traffic revision tests, migration compatibility checks, post-deploy smoke tests, failure injection, and rollback rehearsal.
- **Learning experiment:** Deploy a revision that fails its smoke check, verify that it receives no production traffic, then restore the last known-good image and configuration.
- **Non-goals:** Service-account JSON keys, unreviewed production applies, two tools owning the same Cloud Run fields, multi-region delivery, and a general deployment platform.
- **Spec gate:** Approve federation claims and conditions, pipeline permissions, artifact provenance, plan review, migration ordering, traffic policy, rollback trigger, environment protection, and failure notifications.

## 20. Cloud Tasks and Cloud Scheduler

- **Learning goal:** Move slow provider work beyond the request lifetime while preserving the workflow's existing ownership, revision, and idempotency guarantees.
- **Visible outcome:** The API reserves a suggestion request and enqueues it; an authenticated private Cloud Run handler completes it through Cloud Tasks, while Cloud Scheduler invokes one bounded recurring cleanup operation.
- **New technology/pattern:** Cloud Tasks queues, explicit HTTP targets, OIDC-authenticated invocation, task names, at-least-once delivery, retries and backoff, rate limits, queue observability, poison-task handling, and authenticated schedules.
- **Verification emphasis:** Duplicate delivery, lost enqueue response, stale/cancelled work, handler timeout, retry exhaustion, queue throttling, schedule replay, and no duplicate provider result or todo creation.
- **Learning experiment:** Cause the handler to succeed but lose its response, allow Cloud Tasks to deliver it again, and verify that the saved result and provider-side effect policy remain correct.
- **Non-goals:** Exactly-once execution or billing, Pub/Sub fan-out, arbitrary background workers, distributed workflow engines, and cron logic inside Cloud Run instances.
- **Spec gate:** Approve enqueue/transaction ordering, payload limits, task identity, handler authentication, idempotency scope, retry and timeout policy, queue limits, cleanup schedule, recovery UI, and cost bounds.

## 21. Observability, alerts, and cost control

- **Learning goal:** Diagnose deployed behavior and cost using signals that preserve user privacy.
- **Visible outcome:** A learner can follow one request and async task through structured logs, inspect Cloud Run/Cloud SQL/Cloud Tasks metrics, respond to an error or backlog alert, and explain current cloud and AI spend.
- **New technology/pattern:** Cloud Logging, Cloud Monitoring, Error Reporting, trace correlation, dashboards, service-level indicators, log-based metrics, alerts, retention, redaction, quotas, budgets, and provider usage/cost diagnostics.
- **Verification emphasis:** Synthetic failures, alert delivery tests, dashboard queries, redaction assertions, task-backlog and database-connection alerts, and a cost-review checklist.
- **Learning experiment:** Inject one traceable suggestion failure, locate it without searching for user content, correlate API and task events, and verify the alert links to a useful runbook.
- **Non-goals:** A commercial observability platform, logging prompts or todo titles by default, exhaustive SRE policy, multi-region SLOs, and vanity dashboards.
- **Spec gate:** Approve signal names, correlation identifiers, sensitive-field rules, retention, alert thresholds and recipients, service objectives, provider quota/cost reporting, and runbooks.

## 22. Cloud KMS and encryption lifecycle

- **Learning goal:** Distinguish default Google encryption, customer-managed encryption keys, application-layer envelope encryption, and secret storage.
- **Visible outcome:** A contained lab encrypts and decrypts a non-production fixture, rotates its key, reads ciphertext produced by an older version, tests disable/restore, and documents safe destruction checks.
- **New technology/pattern:** Key rings, cryptographic keys and versions, IAM separation of duties, automatic symmetric rotation, envelope encryption, CMEK integration, audit logs, disable/restore/destroy states, and re-encryption responsibilities.
- **Verification emphasis:** Old-version decryptability, denied decrypt permissions, rotation behavior, backup/state dependencies, restoration during the destruction window, and a no-data-loss destruction checklist.
- **Learning experiment:** Rotate a key and demonstrate that rotation changes the primary version without automatically re-encrypting existing ciphertext.
- **Non-goals:** Encrypting ordinary todo fields without a threat-model need, HSM/EKM, asymmetric PKI, inventing cryptographic primitives, and destroying an in-use key version.
- **Spec gate:** Approve the concrete data classification and use case, key location and purpose, IAM roles, rotation period, ciphertext metadata, re-encryption plan, disable/destroy approvals, recovery, and cost.

## 23. Resilience and production operations

- **Learning goal:** Turn deployment, database, security, and observability knowledge into rehearsed recovery procedures.
- **Visible outcome:** The learner restores a non-production database, recovers from a failed migration and bad revision, rotates a secret, reviews Artifact Analysis and Security Command Center findings, and records recovery evidence.
- **New technology/pattern:** Runbooks, recovery point/time objectives, expand/contract migrations, Cloud SQL regional high availability, maintenance planning, incident roles, audit evidence, vulnerability triage, dependency maintenance, and game days.
- **Verification emphasis:** Timed restore and rollback drills, old-client compatibility, in-flight workflow handling, secret revocation, security-finding triage, and one complete incident exercise.
- **Learning experiment:** Ship the expand half of a schema change, run old and new revisions safely, complete the contract half later, and recover from a deliberately failed intermediate deployment.
- **Non-goals:** Unrehearsed production claims, multi-region active/active architecture, compliance certification, a staffed on-call program, and infrastructure justified only by hypothetical scale.
- **Spec gate:** Approve availability and recovery objectives, HA cost, backup evidence, migration protocol, incident/runbook ownership, security severity policy, maintenance cadence, and production-readiness checklist.

## 24. Cloud Storage and direct uploads

- **Learning goal:** Store large immutable objects outside PostgreSQL and keep application authorization in control of access.
- **Visible outcome:** A user uploads and downloads a bounded attachment through short-lived signed URLs while the API owns metadata, authorization, expiry, and cleanup.
- **New technology/pattern:** Cloud Storage buckets and objects, uniform bucket-level access, signed URLs, upload constraints, CORS, lifecycle rules, checksums, object metadata, event consistency, and orphan cleanup.
- **Verification emphasis:** Ownership, expired signatures, content-type and size rejection, checksum mismatch, abandoned upload cleanup, object deletion, and browser/iOS upload behavior.
- **Learning experiment:** Request an upload URL, let it expire, confirm rejection, upload with a fresh URL, and verify another user cannot obtain a download URL.
- **Non-goals:** Public buckets, proxying large files through FastAPI, storing binary data in Cloud SQL, media processing, and a general asset-management system.
- **Spec gate:** Approve the attachment use case, limits, bucket location, naming, signing identity, authorization flow, CORS, lifecycle/retention, malware boundary, cleanup, and deletion behavior.

## 25. Pub/Sub and Eventarc

- **Learning goal:** Distinguish an event notification from explicit task invocation and decouple multiple reactions to one business event.
- **Visible outcome:** Workflow completion publishes a minimal event that independently drives an analytics consumer and a notification fixture through authenticated Cloud Run targets.
- **New technology/pattern:** Pub/Sub topics and subscriptions, Eventarc triggers, push delivery, acknowledgements, retries, dead-letter topics, schema/version discipline, fan-out, ordering limits, and idempotent consumers.
- **Verification emphasis:** Duplicate and out-of-order events, unavailable consumers, dead-letter routing, replay, schema compatibility, publisher transaction boundaries, and privacy-safe payloads.
- **Learning experiment:** Take one consumer offline, complete workflows, verify the other consumer continues, then recover or replay the failed subscription without duplicate outcomes.
- **Non-goals:** Replacing Cloud Tasks, event sourcing, Kafka, Dataflow, global ordering, and putting full workflow or user content in events.
- **Spec gate:** Approve event names/schema, publish timing, payload privacy, consumer identities, retry/dead-letter policy, idempotency keys, replay controls, retention, and observability.

## 26. BigQuery product analytics

- **Learning goal:** Separate transactional application data from analytical workloads and define product metrics without copying sensitive content unnecessarily.
- **Visible outcome:** Privacy-conscious events support SQL analysis of signup, workflow completion, suggestion outcome, and latency funnels without analytical scans against Cloud SQL.
- **New technology/pattern:** BigQuery datasets and tables, partitioning, clustering, batch or event ingestion, retention/expiration, query-cost controls, views, data location, and least-privilege analyst access.
- **Verification emphasis:** Schema validation, duplicate event handling, metric-definition tests, retention checks, row-count reconciliation, access denial, and bounded query bytes.
- **Learning experiment:** Calculate a workflow-completion funnel, discover how duplicate deliveries distort it, and correct the query using the event identity contract.
- **Non-goals:** A customer-data platform, copying todo titles or prompts by default, real-time BI requirements, Dataflow, BigQuery ML, and replacing PostgreSQL.
- **Spec gate:** Approve metric definitions, lawful data set, event linkage, dataset location, retention/deletion, ingestion path, access roles, query-cost limits, and validation queries.

## 27. Firebase Cloud Messaging

- **Learning goal:** Deliver useful cross-platform notifications without treating notification delivery as authoritative application state.
- **Visible outcome:** An opted-in user receives a bounded reminder or completed-work notification on a supported device, and tapping it opens the app to state fetched from the API.
- **New technology/pattern:** Firebase projects and app registration, FCM registration tokens, APNs integration, permission prompts, platform-specific payloads, token rotation/removal, foreground/background handling, deep links, and Tasks or Pub/Sub delivery.
- **Verification emphasis:** Consent, invalid/rotated tokens, signed-out users, duplicate messages, stale deep links, denied permissions, redacted payloads, and deterministic notification fixtures before live-device acceptance.
- **Learning experiment:** Invalidate a device token, send a notification, verify the failure removes or disables the token safely, and confirm no business state depends on receipt.
- **Non-goals:** Growth campaigns, notification tracking profiles, mandatory permission prompts, storing sensitive content in payloads, and replacing in-app recovery UI.
- **Spec gate:** Approve the user value, opt-in UX, supported platforms, token ownership/lifecycle, payload privacy, delivery trigger, retry policy, deep-link behavior, analytics, and deletion handling.
