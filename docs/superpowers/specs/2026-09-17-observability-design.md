# Phase 21: Observability, alerts, and cost control

**Status:** Revised on 2026-09-17 following learner approval of the tracing-focused direction. Implementation and live acceptance have not started.

**Context:** Inspected `main` at `081ad8b` on 2026-09-17. The learner selected a low-traffic learning sandbox with email alerts. No live cloud inventory or account billing was inspected for this proposal.

**Related:** [Implementation proposal](../plans/2026-09-17-observability.md), [learner walkthrough](../../guides/21-observability.md), [Phase 20](../../guides/20-cloud-tasks-scheduler.md).

## Outcome and approach

Follow one suggestion from its API reservation through enqueue, delivery, provider work, and saved result using identifiers. Diagnose failures, queue backlog, and database pressure; receive an email with recovery instructions; review cloud spend and existing provider spending controls without exposing user content.

Use OpenTelemetry spans exported to Cloud Trace, alongside structured logs and native Cloud Monitoring. The main acceptance outcome is one application trace covering the API, database operations, task enqueue, worker processing, provider request, and saved result.

Scope is deliberately limited to backend suggestion execution and the existing clarification call. No frontend instrumentation, commercial platform, collector service, Redis, generic telemetry framework, automatic provider retry, billing warehouse, or public diagnostics endpoint. Datadog RUM remains Phase 29.

AI token/cost collection, per-user usage reporting, and attribution move to Phase 26, with analytical dashboards in Phase 28. Daily allowance enforcement is separately deferred: no usage table, quota middleware/UI, new 429 behavior, or allowance cleanup job in Phase 21. Keep existing provider token/deadline bounds, queue limits, provider-account spending controls, and cloud budget alerts.

## Findings from the repository

| Existing implementation | Consequence for this phase |
| --- | --- |
| `worker.py` emits safe `extra` fields, but production has no application JSON formatter or INFO logger setup | Existing fields are not a dependable structured production signal; test log capture alone does not prove production output |
| API reservation commits before enqueue; deterministic task names use the suggestion row and fingerprint | Reuse `suggestion_id` for the async chain; preserve task version 1 and enqueue ordering |
| Worker acknowledges expected provider failures with HTTP 204 | HTTP success and queue removal do not mean a usable suggestion was saved |
| Worker ignores the return value from `finish_claimed_suggestion` | Its current `ready`/`failed` log can describe a discarded late result; correct the observation at this boundary |
| `_post_openrouter_json` serves suggestions and `choose_clarification` | Trace latency and safe failures on both paths; defer usage accounting |
| Provider calls already have a 30-second deadline, 400 output-token limit, and 16 KiB response limit | Preserve these; do not add token/cost extraction in this phase |
| `operations.tf` supports optional budget, uptime check, and uptime alert resources | Inventory and extend existing resources; do not assume the optional resources are deployed |
| Cloud Tasks is limited to 1 dispatch/second and 2 concurrent dispatches, with 5 attempts; worker max instances is 1 | Preserve throughput bounds; these are not total demand or dollar limits |
| SQLAlchemy pools allow 2 connections per engine with no overflow | Account for all API/worker instances, revisions, migration jobs, and operator connections when choosing the database alert threshold |
| Suggestion input snapshots and replay journals persist in PostgreSQL | Log retention does not erase workflow content; preserve replay semantics and document the distinction |

## 1. Structured logs and truthful outcomes

Create one small `app/observability.py` using `logging`, `json`, `contextvars`, and a monotonic clock. Configure it in both application factories. Emit one JSON object per line to stdout, with application INFO enabled and no duplicate handlers on repeated factory construction.

Use an explicit field allowlist. Common fields are `event`, `severity`, fixed `message`, `service`, `revision`, `http_request_id`, `duration_ms`, `outcome`, and bounded `error_code`. Operation fields are `workflow_id`, `suggestion_request_id`, `suggestion_id`, `task_id`, `operation`, `attempt_id`, bounded `model`, trace ID, and span ID. IDs are diagnostic fields, never metric labels. Do not emit account identity or usernames.

Generate a fresh server HTTP request ID and derive log trace/span fields from the active OpenTelemetry context. A pure ASGI wrapper observes response completion, including streamed `/agent` responses, without consuming bodies or buffering SSE. Reset context on errors/cancellation. Trace headers are untrusted diagnostic input, never authentication.

For async work, retain `suggestion_id` as a fallback lookup key. Log the deterministic task ID when available, never the fingerprint or task body. Propagate trace context explicitly as described below; correlate application logs to their active spans using the [Cloud Run logging fields](https://docs.cloud.google.com/run/docs/logging?authuser=610). Platform-generated request spans may differ from the application's trace and are not required to form the application waterfall.

Events:

| Event | Meaning |
| --- | --- |
| `http_request` | Completed HTTP exchange with method, route template, status, and duration; no raw URL/query |
| `suggestion_reserved` | One newly committed reservation; a replay is not another reservation |
| `suggestion_enqueue` | Enqueue accepted/deduplicated or unavailable; acceptance is not proof of eventual execution |
| `suggestion_delivery` | Claim/delivery outcome including `no_work`, `live_claim_retry`, `claim_unavailable`, and `discarded` |
| `suggestion_finished` | Committed transition to `ready`, `failed`, or `superseded`; emit after commit, including expiry and claim-time timeout transitions |
| `provider_call` | One actual transport attempt, its latency and safe outcome, identified by `attempt_id` |
| `ai_output_rejected` | Transport returned a response but the application rejected its content; separate from transport success |
| `agent_finished` | Semantic agent outcome, including errors inside an HTTP 200 stream |
| `maintenance_finished` | Existing expiry counts, duration, and safe failure category |

Do not equate attempted finalization with a saved result. Inspect finalizer return values; emit `discarded` when no state change was committed. Sweep/claim helpers must return committed transition metadata so callers can emit each actual terminal transition. Preserve existing lock order, expiry rules, HTTP responses, and permanent provider claim semantics.

Application logs must exclude goals, titles, clarification values, prompts, responses, tool arguments, bearer tokens, cookies, credentials, SQL parameters, and raw exception text. Test the serialized stdout/stderr, not just `caplog.text`. Disable duplicate Uvicorn access output in deployed API and worker entrypoints; sanitize unexpected exception output rather than allowing a second raw traceback through Uvicorn. Third-party log records must not bypass the output policy. Preserve safe error category and code location for diagnosis.

Cloud Run platform request logs are separate and can contain URLs and client metadata; do not claim the application formatter redacts platform logs. Keep content and credentials out of URLs, and record platform log access and retention during inventory.

For unexpected faults, emit a sanitized `ReportedErrorEvent` with a fixed message, service/revision, and code location. Expected provider outages remain categorized operational events, not arbitrary exception dumps. Google documents [Error Reporting's structured format](https://docs.cloud.google.com/error-reporting/docs/formatting-error-messages).

## 2. One distributed application trace

Instrument application boundaries with the OpenTelemetry API/SDK, using explicit spans rather than broad automatic capture. This keeps database statements, bind values, HTTP bodies, exception strings, and credentials out of exported attributes/events. Use the same allowlist policy for logs and traces; disable automatic exception recording and add only a safe error category/status. Fixed span names, not user content or IDs, identify operations.

```text
POST /todo-workflows/{workflow_id}/suggestions
  db.reserve_suggestion
  cloudtasks.enqueue
  suggestion.process (later delivery, same trace)
    db.claim_suggestion
    provider.suggestions
    db.finish_suggestion
```

The tree describes parent relationships, not nested wall-clock lifetimes: the API span ends when its response completes. Worker spans can start after their parent ends. Never keep an HTTP request, database transaction, or in-memory root span open across the queue wait. Record `queue_wait_ms` from the stored database enqueue timestamp to first claim; show the visible timeline gap without inventing a Google-internal queue span. Database spans measure the application's operation including pool wait/transaction work, not individual server-side SQL execution or lock internals. Provider spans measure the outbound request, not the provider's internal computation.

### Propagation, replay, and retries

Use the OpenTelemetry W3C propagator for trace IDs, parent IDs, and sampling flags. [Google's trace-context guidance](https://docs.cloud.google.com/trace/docs/trace-context) makes propagation the application's responsibility; do not assume Cloud Tasks does it automatically.

- Persist an optional canonical `trace_parent` (W3C `traceparent`, maximum 55 characters for version 00) on the existing suggestion row in the reservation transaction. Capture the API server span context, not an uncommitted database child span. Validate nonzero IDs and flags with the propagator; store no baggage or arbitrary `tracestate`. This is an additive trace-metadata migration, not an analytics table.
- A same-ID replay never changes the stored context. Enqueue repair uses the original context; a replay HTTP request keeps its own trace and links to the stored one. Deterministic task naming, request fingerprints, idempotency, and task body version 1 remain unchanged.
- Send the stored context in the task's `traceparent` and a bounded application-owned `X-Suggestion-Traceparent` header. The second header preserves application lineage if a managed intermediary changes standard headers. Both carry the same validated value, and neither grants authority.
- Worker middleware uses that application context for its server span; once the row is read, verify it agrees with persisted context. Missing/mismatched context must not reject otherwise valid work or change claims: continue business processing, log a safe diagnostic, and use stored context for `suggestion.process` (linking the receipt span if it belongs to another trace). Never copy arbitrary incoming baggage.
- Each delivery/processing attempt creates a new span ID in the original trace. Duplicates and live-claim retries record their actual outcome without another provider call. Transport acceptance is separate from saved business success.
- Legacy rows/tasks without context remain executable and start a fresh trace with the suggestion ID. Do not promise historical trace reconstruction. When the expiry sweep closes a row with context, create a short `suggestion.expire` span under that stored context and link it to the separate Scheduler sweep trace. Batch maintenance must not merge different suggestions into one transaction trace.
- Inline suggestion execution and agent clarification keep ordinary request-child spans. Separate frontend calls/polling are not automatically one workflow-wide trace; the acceptance unit is one suggestion execution, including its retries.

### Export, sampling, and runtime lifecycle

Use a small `app/tracing.py` alongside the logging helper. Configure service name and revision as resource attributes. Start with the OpenTelemetry SDK and Google's [Cloud Trace exporter](https://google-cloud-opentelemetry.readthedocs.io/en/latest/cloud_trace/cloud_trace.html), using ADC and direct Cloud Trace API export. This supported option avoids a collector and hand-written authentication; Google's broader [instrumentation guidance](https://docs.cloud.google.com/trace/docs/setup) also describes OTLP alternatives. Verify Python 3.14 and locked dependency compatibility in the first implementation task. Do not build an exporter or silently add a collector if compatibility fails; report the specific issue and revise that choice.

Grant only the API and worker runtime identities `roles/cloudtrace.agent` and enable the Cloud Trace API through Terraform. Do not grant trace-writing rights to the task invoker or browser. Test with an in-memory exporter; ordinary local runs export nothing unless explicitly enabled. Production exporter initialization is lifespan-owned, idempotent, and closed on shutdown.

Set `TRACE_SAMPLE_RATE` to 0.1 for ordinary sandbox operation and temporarily 1.0 for acceptance drills. Apply the local root decision at the public application boundary rather than letting arbitrary client sampling flags force capture; descendants honor the stored decision. Exclude successful health/readiness probes from spans. Keep failure logs independent of trace sampling: an unsampled failed request still needs an alert. Record that head sampling can omit failures and managed Google services make their own sampling decisions.

Cloud Run request-based CPU allocation means background batch export cannot be assumed to run after a response. End application spans and perform a bounded, off-event-loop flush before final response completion, including worker 204 and SSE terminal completion; also flush on graceful shutdown. Limit the request flush budget to 2 seconds, bound exporter RPC/retries, and test unreachable-exporter behavior. Verify no unbounded thread/task accumulation under export failure and no provider retry, rollback of committed results, or replacement of a successful response due to telemetry failure. Record export overhead separately from business-stage duration. Hard termination can still lose spans; keep logs and database state as fallback evidence.

### Provider operations only

The shared transport produces a `provider_call` event and span for suggestions and clarification with duration and safe outcome. Content-validation failures remain distinct from transport success, and saved results remain distinct from both. No token totals, reported costs, per-user attribution, generation accounting, or reconciliation pipeline is added. Preserve existing provider and queue limits; review current provider-account controls manually without prescribing a new spending allowance in this phase.

## 3. Dashboard, alerts, and learning objectives

Extend the existing Terraform root with `observability.tf` and one optional configuration object. Reuse a chosen email notification-channel resource name; create/import a channel only if none exists. The actual recipient and SQL connection threshold are deployment inputs, not values to guess or commit to examples. Keep Terraform 1.14.7 and Google provider 8.2.0.

One dashboard contains API/worker HTTP errors and latency, queue depth and task attempt outcomes, SQL connections/CPU/memory, provider calls/latency, and saved suggestion outcomes. Include links to Cloud Trace, diagnostic logs, billing views, Error Reporting, and the runbooks. Cloud Run's native request latency is not browser-perceived latency and its metric has no useful route label; keep streaming and inline calls out of claims about ordinary endpoint latency.

Only three application log-based metrics initially:

1. `phase21_provider_calls`: counter of `provider_call`, bounded operation/outcome labels.
2. `phase21_provider_duration_ms`: distribution of provider duration, bounded operation label.
3. `phase21_suggestion_outcomes`: counter of committed `suggestion_finished`, bounded outcome/error-code labels.

Use native service/resource dimensions for infrastructure metrics. No user, workflow, task, request, generation, or attempt ID metric labels. Provider call counts are reliability diagnostics, not AI consumption or billing analytics. Cost review uses existing account dashboards.

| Alert | Proposed starting condition | First response |
| --- | --- | --- |
| Existing uptime | Preserve the adopted policy; verify email delivery | Follow the existing API readiness/deployment runbook |
| Actionable application failure — new | A matching failure event; at most one notification/hour for this policy | Open linked logs; distinguish enqueue, saved provider failure, expiry, agent failure, and unexpected fault |
| Queue backlog — new | Selected queue depth greater than 0 continuously for 5 minutes | Check intentional pause, worker IAM/revision, and task responses; resume only after diagnosis |
| SQL connections — new | Sum instance connections greater than 80% of observed usable connection capacity for 5 minutes | Check revisions, instance counts, migrations, and pool pressure before changing capacity |
| Existing cloud budget | Preserve amount; propose 50%, 80%, and 100% actual-spend notifications if absent | Review spend by service and recent changes |

The application failure filter is an explicit event/outcome allowlist. Exclude normal 4xx, expected live-claim retries, and discarded late work. Include actual saved failures, enqueue unavailability, malformed worker tasks, maintenance failure, and unexpected faults. Do not infer failure solely from severity or double-alert transport and saved-outcome logs. Attach the guide's runbook URL, service/queue identity, and a ready-to-use log filter. Log-alert auto-close is 24 hours; it is not proof that a failure recovered.

Use `cloudtasks.googleapis.com/queue/depth` and `queue/task_attempt_count`; use `cloudsql.googleapis.com/database/postgresql/num_backends` summed across database/state series for the selected instance. These are documented [Google Cloud metrics](https://docs.cloud.google.com/monitoring/api/metrics_gcp_c). Queue depth can detect a paused backlog; dispatch delay alone cannot. Allow for metric ingestion delay; five minutes is not an email-delivery guarantee. Absence of data is unknown, not healthy or a reason to page an idle sandbox.

Learning objectives, not production commitments: investigate any reserved suggestion that has not settled within 2 minutes; aim for 95% ready among observed ready/failed outcomes over 30 days, explicitly excluding superseded/discarded work. Show numerator, denominator, and sample count; fewer than 20 outcomes is insufficient evidence. Log gaps are a limitation; the database is authoritative for a particular workflow. Do not implement SLO burn-rate alerts or claim an availability guarantee.

## 4. Retention and cost review

| Data | Proposed policy |
| --- | --- |
| Application/container and ordinary request logs | 30 days in the existing project log bucket; verify current location, routing, retention, and any sinks before adopting/changing it |
| Required audit logs | Preserve provider-mandated retention; do not try to force them to 30 days |
| User-defined metric time series and Error Reporting records | Document their service-managed retention separately; raw-log expiry is not a blanket telemetry deletion guarantee |
| Trace spans | Verify and record Cloud Trace storage retention separately; a 30-day log policy does not set trace retention |
| Persisted suggestion trace context | Retain with the existing suggestion/replay row; IDs only, no user content |
| Workflow title, AI input snapshots, proposals, and replay journals | Retain with the workflow under existing product semantics; no time-based deletion in this phase |
| Agent message/tool history | Do not copy it into telemetry or add server-side history persistence |
| Provider-side prompts and responses | Review the selected provider/account data policy; local logging rules do not control external retention |

Retained workflow content is an explicit sandbox limitation. Do not clear snapshots or remove old suggestion rows as a shortcut: current database constraints and replay checks depend on them. A time-bounded product-content deletion feature needs its own design. Backups can outlive primary-row deletion and must be included in any future deletion promise.

Google documents configurable [log bucket retention](https://docs.cloud.google.com/logging/docs/buckets?authuser=0&hl=en). Import an existing bucket only after inspecting it; avoid a second sink/bucket and duplicate ingestion.

For costs, preserve the current cloud budget amount and review Cloud SQL baseline, Cloud Run API/worker, registry images, logs/metrics/traces, and task/scheduler usage. The existing Terraform budget is an alerts-only control; it does not shut services down. [Current budget documentation](https://docs.cloud.google.com/billing/docs/how-to/budgets?authuser=89) distinguishes alerts-only budgets from newer spend-cap features. No automatic billing disablement or blanket claim that all Google budgets work identically.

## 5. Verification, rollout, and approval

Local checks use the isolated PostgreSQL database, fake providers, in-memory span export, and existing HTTP seams. Verify serialized log/span redaction, context isolation across async/threadpool work, SSE completion/cancellation, cross-process propagation, replay/duplicate span identities, missing/malformed context fallback, sampled/unsampled behavior, bounded exporter failure, truthful finalization/expiry events, and unchanged provider-call counts and business outcomes.

Deploy the additive trace-context migration before the compatible API/worker release. Old rows remain valid, and older revisions ignore the nullable column; retain it during rollback. Enable export after IAM/API setup. Do not rewrite task bodies, reset provider claims, or disturb release-owned image/revision/traffic fields.

Acceptance requires one real API → database reservation → enqueue → worker → database claim → provider → database save waterfall with a single application trace ID. Also require a retry/no-work demonstration, a visible queue delay, span/log privacy checks, sampling/flush verification, received emails, backlog/expiry drill, SQL threshold drill, Error Reporting fixture, and cost/retention inventory. Mark missing spans or unperformed drills honestly; Phase 20's unrelated acceptance gaps stay pending.

The learner approved the tracing-focused scope and analytics deferral. Operational defaults remain proposed: 10% steady-state application traces and 100% during bounded drills; 2-second flush budget; 30-day application logs; backlog threshold 5 minutes; SQL threshold 80% of usable capacity; failure email throttle 1 hour; existing cloud budget and provider limits retained. Exact channel and SQL capacity are deployment inputs. This document update does not authorize cloud mutation, notification tests, or paid calls.
