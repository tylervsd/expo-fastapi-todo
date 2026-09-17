# Phase 21 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Updated for the learner-approved tracing direction on 2026-09-17. Implementation complete locally (Tasks 1–4, each review-clean); Task 5 integration run observed 2026-09-17. Cloud acceptance has not started.

**Goal:** Follow one suggestion across API, database operations, Cloud Tasks, worker, provider, and saved result in a single Cloud Trace waterfall.

**Architecture:** Explicit OpenTelemetry spans with durable trace context on the existing suggestion row; structured logs remain a fallback. Native Google Monitoring supplies dashboards and operational alerts. Direct Cloud Trace export uses runtime ADC, with bounded flushing suitable for Cloud Run request-based CPU allocation.

**Tech Stack:** Python 3.14, FastAPI/ASGI, SQLAlchemy/PostgreSQL/Alembic, OpenTelemetry API/SDK and Google Cloud Trace exporter, pytest, Terraform 1.14.7 and Google provider 8.2.0.

**Spec:** [Revised Phase 21 design](../specs/2026-09-17-observability-design.md).

## Global constraints

- No AI token/cost collection, per-user analytics, daily allowance table, quota UI, new quota response, or counter cleanup.
- Keep existing provider limits, queue throughput/retry limits, provider-account spending controls, and cloud budget alerts.
- Preserve task version 1/body, deterministic names, fingerprints, claim permanence, transaction ordering, and all existing HTTP/domain outcomes.
- Logs and spans must omit content, credentials, SQL text/parameters, and raw exception messages/events.
- Application sampling: 10% steady state, 100% for bounded acceptance; health probes excluded; alerts work without sampled traces.
- Flush budget: 2 seconds before final response completion, with bounded exporter work; telemetry failure cannot change business outcomes.
- Allow only tracing dependencies justified by this design; no collector, generic exporter abstraction, browser tracing, or additional service.
- CI uses fake providers/in-memory spans, never cloud credentials or paid calls.

## Execution setup

- [ ] Read the spec, root `AGENTS.md`, and Guides 19/20. Use the worktree skill at execution time; proposed branch `codex/phase-21-observability`, worktree `.worktrees/phase-21-observability`.
- [ ] Preserve unrelated `.pi/` and `AGENTS.md` changes. Use Astra medium for architecture, Luna for bounded tasks, Terra for integration/debugging, and Sol medium for significant/final review.
- [ ] Establish relevant existing test baselines. Return architecture questions to the controller rather than expanding the scope in an implementation task.

## Task 1: Establish safe tracing and logging lifecycle

**Create:** `apps/api/app/tracing.py`, `apps/api/app/observability.py`, `apps/api/tests/test_tracing.py`, `apps/api/tests/test_observability.py`.

**Modify:** `apps/api/pyproject.toml`, `uv.lock`, `app/main.py`, `app/worker.py`, and `Dockerfile`; check adopted Terraform command overrides before changing entrypoints.

**Produces:** lifespan-owned tracer/exporter setup, request-scoped spans/log context, explicit safe event/span helpers, and an injectable in-memory exporter seam. Use standard OpenTelemetry propagation rather than custom trace-ID parsing.

- [ ] Confirm the Google exporter and SDK resolve on Python 3.14, pin compatible versions in the lockfile, and prove a span can be exported to the in-memory test seam. If the selected exporter is incompatible, report the blocker before choosing another architecture.
- [ ] Write failing tests for actual serialized log/span output containing sentinel body/query/header/SQL/exception secrets. Assert no automatic exception event or third-party logging path bypasses the allowlist.
- [ ] Test overlapping requests and threadpool calls, repeated application creation, malformed headers, health exclusions, SSE completion/disconnect, and context reset.
- [ ] Implement explicit ASGI request spans without consuming bodies or buffering streams. Use fixed names, safe attributes and active trace/span IDs in logs. Sanitize unexpected Uvicorn output and disable duplicate access logging in both deployed entrypoints.
- [ ] Test root sampling decisions and stored-parent sampling inheritance. Untrusted public flags must not override local sample policy.
- [ ] Prove span end/flush ordering before final response completion, a 2-second flush bound, shutdown cleanup, and bounded exporter RPC/retry behavior. Simulate exporter outage and verify successful business responses remain successful and background work does not accumulate without bound.
- [ ] Run `uv run --directory apps/api python -m pytest tests/test_tracing.py tests/test_observability.py tests/test_agent_protocol.py tests/test_health.py` and `pnpm lint:api`; commit.

## Task 2: Carry durable trace context across the queue

**Create:** `apps/api/alembic/versions/2026091701_suggestion_trace_context.py` (verify available revision ID/current migration head).

**Modify:** `apps/api/app/workflow_repository.py`, `suggestion_service.py`, `suggestion_tasks.py`, `main.py`, `worker.py`; extend `tests/test_suggestion_tasks.py`, `test_suggestion_worker.py`, `test_workflow_suggestions.py`, and persistence tests.

**Consumes:** Task 1 context/propagation helpers. **Produces:** nullable `trace_parent` metadata on the existing suggestion row and task-header propagation without a task-body change.

- [ ] Add migration tests for old rows with null context and new rows with canonical version-00 W3C context of at most 55 characters. Trace metadata must not enter request fingerprints or idempotency keys.
- [ ] Test new reservation context is committed alongside the row; same-ID replay preserves it, including enqueue repair from another API request/trace.
- [ ] Extend the reservation/enqueue seams minimally to pass stored context explicitly, including threadpool boundaries and injected fakes. Emit `traceparent` and `X-Suggestion-Traceparent` with the same validated value; no baggage.
- [ ] Build an API-to-worker integration test with separate tracer providers sharing an in-memory test sink. Assert API/reserve/enqueue/process/claim/finalize spans share a trace ID, have distinct span IDs, and preserve expected parent relationships without process-local context sharing.
- [ ] Deliver twice: each delivery gets a new span ID; provider is still called at most once. Test lost enqueue response/replay, live-claim retry, and terminal no-work delivery.
- [ ] Test absent, malformed, mismatched, and intermediary-modified trace headers. Stored context controls processing lineage where available; observability input never grants access or rejects valid work. Link separate receipt/replay traces where needed.
- [ ] Run the affected suggestion, task, worker, and persistence test files; commit.

## Task 3: Trace meaningful operations and truthful saved outcomes

**Modify:** `apps/api/app/main.py`, `suggestion_service.py`, `suggestion_provider.py`, `agent.py`, `worker.py`; extend existing provider/worker/agent/workflow tests and `test_tracing.py`.

**Produces:** the waterfall and event semantics defined in the spec. No usage parsing or frontend changes.

- [ ] Add explicit spans for reservation, task enqueue, worker processing, database claim/finalization, and shared provider transport. Measure database operation boundaries rather than emitting SQL statements or installing broad query capture.
- [ ] Test provider success, timeout, HTTP failure, invalid output, and cancellation for both suggestions and clarification; preserve callable seams, deadlines, size/token bounds, and no-retry behavior.
- [ ] Add a late-result regression: finalizer returns no saved result; report `discarded`, never saved `ready`. Distinguish actual committed supersession from a no-op.
- [ ] Return transition metadata from claim/expiry transaction helpers and emit terminal logs after commit. Expiry of a traced row creates `suggestion.expire` in its original trace and links to the independent maintenance trace; no duplicate terminal event on replay.
- [ ] Record database-clock queue delay at first claim; show delay as timing/attribute, not a fabricated managed-service span. Keep HTTP and database transactions closed while queued.
- [ ] Cover semantic errors inside HTTP 200 agent streams and HTTP 204 task acknowledgements. Log safe failures regardless of sampling; configure sanitized Error Reporting for unexpected faults.
- [ ] Run `uv run --directory apps/api python -m pytest tests/test_tracing.py tests/test_suggestion_provider.py tests/test_suggestion_worker.py tests/test_workflow_suggestions.py tests/test_agent.py tests/test_agent_protocol.py`; commit.

## Task 4: Provision native trace access, dashboard, and alerts

**Create:** `infra/terraform/sandbox/observability.tf`, `infra/terraform/sandbox/tests/observability.tftest.hcl`.

**Modify as needed:** `variables.tf`, `outputs.tf`, `terraform.tfvars.example`, `operations.tf`, `services.tf`, `iam.tf`, `run.tf`, and `tasks.tf` in the same root. Preserve adopted addresses and release ownership.

- [ ] Inspect the pinned provider schema; add mock-plan tests for default-disabled additions, least-privilege grants, filters/aggregation, bounded labels, sample configuration, and preserved existing resources.
- [ ] Enable Cloud Trace API and grant API/worker runtime accounts `roles/cloudtrace.agent`. Add project/service/revision/export/sample configuration; grant no trace role to task invoker or clients. No service-account key files.
- [ ] Add the three specified log metrics: provider calls, provider duration, committed suggestion outcomes. Do not add token/cost or per-user metrics.
- [ ] Build one dashboard with trace/log/runbook links, native API/worker/queue/SQL signals, and operational provider/suggestion signals. Native request status and saved outcome remain distinct.
- [ ] Add explicit application-failure log alert (3600-second notification throttle, 86400-second auto-close), queue depth greater than 0 for 300 seconds, and SQL connections above the chosen capacity threshold for 300 seconds. Align queue/SQL to 60-second maxima and sum SQL connection series for the selected instance. Validate missing-data behavior; absence is not proof of health.
- [ ] Inventory/reuse the actual email channel, budget, uptime resources, log bucket and any existing trace storage configuration. Preserve existing budget/provider limits. Record separate trace/log retention; do not assume 30-day logs impose 30-day traces.
- [ ] Review logging/export behavior under current Cloud Run request-based CPU allocation; preserve that billing mode and instance limits. Do not enable always-allocated CPU as an undocumented fix.
- [ ] Run `terraform -chdir=infra/terraform/sandbox fmt -check`, `validate`, and `test`; commit. Live apply is a separate reviewed step.

## Task 5: Integrated verification and learner acceptance

**Modify:** [Guide 21](../../guides/21-observability.md), `README.md`, `docs/curriculum-roadmap.md`, and `docs/workflow-learning-plan.md` to reflect actual status.

- [ ] Self-review every spec requirement, especially durable propagation, separate retries, sampling, safe exceptions, export failure, migration compatibility, and truthful saved outcomes.
- [ ] Run `pnpm test:api`, `pnpm lint:api`, the focused Terraform checks, and the existing web E2E regression once after integration. No new UI feature or quota tests are required.
- [ ] Obtain Sol medium significant/final review under `AGENTS.md`; resolve findings and rerun checks affected by changes.
- [ ] Document migration-first deployment, tracing enablement after IAM, legacy fallback, and compatible two-service rollback. Keep the additive trace column during rollback.
- [ ] Follow existing authorization requirements for cloud changes, notification tests, paid calls, and disruptive drills; do not request already-granted authorization again.
- [ ] Execute the walkthrough: single-trace success, deliberate queue delay, duplicate/retry context, redaction, export during idle/scale-down, failure/backlog emails, SQL threshold test, Error Reporting, and cost/retention inventory. Record actual trace URLs and span IDs without sensitive content.
- [ ] Restore sample rate and all drill configuration; verify queue/Scheduler health and final Terraform state. Keep live acceptance pending until observed and learner-signed-off; preserve unrelated Phase 20 gaps.

## Ordering

Tasks 1–3 establish tracing and safe events. Task 4 can proceed independently once event/configuration contracts are settled. Task 5 integrates and verifies. AI usage analytics is future Phase 26/28 work; enforcement remains a separate future decision, not an implicit analytics dependency.
