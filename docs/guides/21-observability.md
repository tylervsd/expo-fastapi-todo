# Phase 21: Observability, alerts, and cost control

**Status:** Revised for the learner-approved tracing focus; proposed learner walkthrough. Phase 21 implementation (Tasks 1–4) is complete locally on `codex/phase-21-observability` through commit `57dd321`, each task review-clean. Local verification observed on 2026-09-17: `pnpm test:api` 688 passed, `pnpm lint:api` clean, Terraform `fmt`/`validate` clean with `test` 43 passed, web E2E 4 passed. Live deployment and learner walkthrough acceptance are pending and require explicit authorization. Phase 20's pending iOS and fault-drill gaps remain open.

**Design:** [Proposed design](../superpowers/specs/2026-09-17-observability-design.md).

**Plan:** [Implementation proposal](../superpowers/plans/2026-09-17-observability.md).

## What you will learn

You will open one Cloud Trace waterfall spanning a suggestion’s API request, database operations, task enqueue, worker execution, provider call, and saved result. You will distinguish an acknowledged task from saved success, diagnose queue delay, and receive an actionable email. AI token/cost analytics moves to Phase 26/28; per-user quota enforcement is separately deferred.

The learner chose a low-traffic sandbox with email alerts. Begin by reviewing the proposed policy values in the design. No new cloud project or observability vendor is needed.

## 1. Record the starting point

Use the same sandbox and authentication setup as [Guide 20](20-cloud-tasks-scheduler.md). Record the project, region, API/worker names and serving revisions, queue, expiry Scheduler job, database instance, current budget, and existing notification-channel resource name. Keep account identifiers in your local evidence; keep tokens and secret payloads out of documents and command output.

Read-only inventory should answer:

- Is the queue running and is the five-minute expiry schedule active?
- Which API and worker revisions receive traffic?
- Do the Terraform budget and uptime resources actually exist, or are their optional inputs null?
- Which email recipient/channel should receive alerts? Confirm ownership and verification requirements.
- What are the log bucket's current location, retention, and sinks? Do platform request logs have separate routing?
- What does PostgreSQL report for `max_connections`, and what connections are reserved? What is the peak across API/worker revisions, migration jobs, and operator tools?
- What provider key/model and spending controls are already configured?
- Which runtime identities can write Cloud Trace, what trace storage/retention applies, and is request-based CPU allocation enabled?

Preserve an ordinary Terraform plan as the baseline. A plan with unrelated drift needs explanation before adding monitoring changes. Repository inspection alone cannot answer these live-state questions.

**Checkpoint:** You can identify each resource and the alert recipient without copying credentials into your notes.

## 2. Prove behavior locally

After implementation, use the existing test database and test seams:

```sh
pnpm db:test:up
pnpm test:api
pnpm lint:api
terraform -chdir=infra/terraform/sandbox fmt -check
terraform -chdir=infra/terraform/sandbox validate
terraform -chdir=infra/terraform/sandbox test
```

Initialize the Terraform root with the existing guide's setup if needed. The Terraform tests use mocks; they must not apply resources. Provider tests use fakes and tracing tests use an in-memory exporter; neither requires credentials or a paid call.

**Observed 2026-09-17 (local worktree, Task 5 integration run):** `pnpm test:api` — 688 passed; `pnpm lint:api` — clean; `terraform fmt -check` / `validate` — clean; `terraform test` — 43 passed, 0 failed (21 pre-existing + 22 observability); web E2E (`pnpm test:e2e:web`) — 4 passed. The worktree's default test ports (5433/5434) were held by other worktrees' containers, so isolated throwaway PostgreSQL 18.6 containers on `127.0.0.1:5435` (`TEST_DATABASE_URL`) and `127.0.0.1:5436` (`E2E_DATABASE_URL`) were used instead; no other worktree's containers were touched. The pinned Terraform binary would not execute in place (macOS launcher verification); a byte-identical copy reported v1.14.7 and ran the checks.

Read one captured JSON line and identify its event, request ID, operation ID, duration, and outcome. Follow a fake provider failure into a saved `failed` result. Confirm that its task response can still be 204. Then inspect a late completion: it must say `discarded`, not falsely report a saved result.

Inspect the in-memory trace test: separate API and worker tracer providers must still produce one trace ID, distinct span IDs, and correct parent relationships using only durable context and task headers. Repeat delivery and enqueue repair; no additional provider execution is allowed. Test legacy/malformed context fallback without changing business outcomes.

The privacy tests insert recognizable sentinel values into goals, headers, SQL parameters, exceptions, and provider responses. Inspect serialized logs and exported spans, including exception events and resource attributes. No sensitive sentinel may appear. Confirm a sampled-out failure still logs and can alert.

Test an unreachable exporter: request flushing stays within the two-second budget, committed success is preserved, and pending export work stays bounded. Test SSE disconnect, threadpool context propagation, and shutdown cleanup.

**Checkpoint:** Explain trace ID versus span ID, parent versus link, transport status versus saved outcome, and why API response completion does not end the logical suggestion trace.

## 3. Deploy the application and monitoring

Review the additive migration and release both API and worker using the established [two-service release procedure](20-cloud-tasks-scheduler.md). Preserve the permanent claim and task schema. The nullable trace-context migration must precede the compatible application release. Old reservations remain valid and can start fresh traces; their historical API spans cannot be reconstructed.

Review the Terraform plan for the dashboard, three log metrics, three additional alert policies, Cloud Trace API enablement/runtime writer grants, and only the necessary configuration changes. Reuse the existing email channel, budget, uptime check, and log bucket where present. Do not replace an adopted database, queue, or service to introduce observability.

Set the SQL alert threshold to 80% of the observed usable connection capacity, rounded down to a positive whole connection count. Review pool capacity against rollout overlap; two connections per process is not two connections for the whole deployment.

Use the learner-approved cloud apply procedure. Verify the resulting resource names and dashboard links. Check a local and cloud log line to confirm INFO output reaches `jsonPayload` and unexpected errors retain a safe location. Verify application logs link to active application trace/span IDs. Platform-generated Cloud Run request traces can differ; acceptance concerns the explicitly instrumented application waterfall.

Keep the current cloud budget amount. If approved, use 50%, 80%, and 100% actual-spend notifications. Keep and record the existing provider-account spending controls; this phase introduces no new per-user allowance or prescribed provider cap. Do not place a management key or secret payload into Terraform.

Enable trace export only after runtime IAM/API setup. Use `TRACE_SAMPLE_RATE=1.0` for the bounded acceptance window, then restore `0.1`. Verify spans arrive after a single request followed by idle time; do not rely on another request waking an exporter thread. Record export overhead and flush behavior.

**Rollback (compatible revisions):** restore both services to the recorded previous revisions API-then-worker following [Guide 20's compatible recovery](20-cloud-tasks-scheduler.md#pause-and-recovery); attempt both restores even if the first fails. The trace-context migration (`2026091701`) is additive and nullable — keep the column during rollback; old revisions ignore it and old reservations remain valid. Never downgrade the database. After drills, restore `TRACE_SAMPLE_RATE` to `0.1`, queue/Scheduler to running/enabled, and confirm a final no-drift plan.

**Checkpoint:** You can open Cloud Trace, the dashboard, matching log queries, alert policy, and runbook from supplied links.

## 4. Open one complete suggestion waterfall

With authorization for a real provider call, create a disposable sandbox workflow with synthetic text. Submit a suggestion, find the API reservation log by its request ID, and follow its trace link into Cloud Trace. Record the `suggestion_id`, trace URL, and span IDs.

Verify these application spans share a trace ID:

```text
API request
  db.reserve_suggestion
  cloudtasks.enqueue
  suggestion.process
    db.claim_suggestion
    provider.suggestions
    db.finish_suggestion
```

The worker may start after the API span ends. This is expected: it continues the same logical trace without keeping the HTTP request or database transaction open. Database spans show application-side operation time, including pool/transaction overhead, not the database server's full internal execution plan. Provider spans show the client request, not internal model processing.

Find the committed ready log and follow it back to the corresponding span. A provider HTTP success is not proof of a saved result. Confirm the application shows the same saved result.

Use this fallback Logs Explorer query when a trace is missing or sampled out, substituting the real integer:

```text
resource.type="cloud_run_revision"
jsonPayload.suggestion_id=123
```

Inspect a clarification call separately if authorized: `provider.clarification` is a child of its `/agent` request. Separate frontend calls and polls do not automatically become one workflow-wide trace. Do not look for token counts or attributed costs; those are outside this phase.

**Checkpoint:** One trace shows API → database → enqueue → worker → provider → saved result, without user content in attributes, events, span names, or logs.

## 5. Prove queue delay and repeated delivery

With authorization, pause an idle sandbox queue briefly, submit one suggestion directly without an agent clarification call, then resume well before the existing 15-minute reservation expiry. Have the resume command from Guide 20 ready before pausing. Restore the original state if interrupted.

The resulting trace should show a gap before processing and a matching `queue_wait_ms` on first claim. Compare database-clock timestamps with the waterfall; account for cross-process clock skew when interpreting very small differences. Do not expect a span exposing internal Google queue processing.

Use the local integration harness to repeat the exact task delivery and exercise live-claim retry/terminal no-work. Each delivery gets a new span ID in the stored trace and never repeats a claimed provider call. For an authorized live duplicate drill, use the existing Guide 20 procedure and record the trace evidence separately; local tests are not live acceptance.

Replay the same API suggestion request after completion: it returns the saved result. Its new HTTP trace links to the original suggestion trace; it does not rewrite the persisted context or create a second provider span. Test lost-enqueue-response repair locally with the same lineage rule.

**Checkpoint:** You can distinguish queue wait, separate delivery attempts, and provider time, with stable suggestion identity and unchanged execution semantics.

## 6. Rehearse backlog and a traceable saved failure

This is a disruptive sandbox drill and requires authorization. Run it while no other learner work is in flight. Capture the original queue state and have the Guide 20 resume command ready. Keep Scheduler running throughout.

1. Pause the existing suggestion queue using Guide 20's procedure. Confirm there are no active worker claims before continuing.
2. Submit one new suggestion directly through the ordinary suggestion path for a disposable workflow, without triggering the agent clarification call. Record the request ID and `suggestion_id`.
3. Keep the queue paused beyond the proposed five-minute backlog threshold. Allow additional time for metric ingestion and email delivery. Open the email, follow its runbook link, and locate the exact queue.
4. Continue the pause until the reservation's existing 15-minute deadline passes and the next scheduled expiry sweep runs. Under healthy scheduling this is roughly 15–20 minutes after reservation, plus observation delay.
5. Find the committed `suggestion_finished` event with `failed/timeout` for that ID and the `suggestion.expire` span in its stored trace. Confirm the application reads the saved failure and the application-failure policy delivers an actionable notification, subject to its one-hour rate limit.
6. Confirm there was no provider claim/call for this reservation; a request that was never claimed need not incur a provider charge. Absence of a log alone is not sufficient proof—inspect the stored claim marker or the existing safe test evidence as well.
7. Resume the queue. Any later delivery must acknowledge the terminal row as no work, without a new provider call. Wait for backlog recovery and record the metric-based incident's resolution.
8. If interrupted, restore the original queue state immediately using the prepared recovery step. Verify the queue is running, Scheduler is healthy, and ordinary requests work before ending the drill.

The saved terminal failure is the actual application failure exercise. It does not simulate a provider timeout or a crash after billing; those cases remain covered by local injected-provider tests unless separately rehearsed. This drill does not silently close Phase 20's pending crash/timeout/iOS acceptance cases.

**Checkpoint:** The stored trace connects the API reservation to `suggestion.expire`; a span link identifies the independent Scheduler sweep, and both emails lead to useful recovery instructions.

## 7. Test database alerting and Error Reporting

Do not exhaust database connections to test an email. With authorization, temporarily lower only the SQL alert threshold below the observed connection count and keep the condition true for its configured duration. Record the delivered notification, restore the original threshold through the same ownership path, and confirm recovery/final Terraform state. If no connections are present, use a single bounded read-only connection rather than a load test.

This proves policy evaluation and delivery; it does not prove performance under exhaustion. The final policy must use the observed capacity-based threshold, not the drill value.

For Error Reporting, use a clearly named synthetic sanitized `ReportedErrorEvent` fixture through Cloud Logging after approval. Verify grouping by service/location and safe message. Record it as a pipeline fixture, not a real production exception. The local exception test proves the application emits the matching shape. Never introduce a public crash endpoint or forward raw exception text to make the demo work.

The failure email policy has a one-hour notification throttle. Plan drills around it or use a reviewed temporary test policy, then remove that policy; a suppressed repeat email is not proof of broken delivery. Log-based incident auto-close is not application recovery evidence.

## 8. Review retention and spend

Record these separately:

| Question | Evidence |
| --- | --- |
| What did Google Cloud charge this month? | Billing view filtered to this project, grouped by service and date |
| Which costs persist while idle? | Cloud SQL and any provisioned/retained resources |
| What did the provider charge? | Provider account/key usage and activity for the same period |
| What did our application observe? | Traces and diagnostic logs for latency, errors, and saved outcomes; no consumption accounting |
| What does tracing cost and retain? | Trace ingestion/storage settings and current billing; compare 100% drill sampling with the restored 10% setting |
| How long are logs retained? | Actual log bucket retention/routing; trace, audit, metric, and Error Reporting retention documented separately |
| What user content remains in PostgreSQL? | Existing workflow snapshots/proposals/journals, retained with the workflow |
| What can backups/provider systems retain? | Observed backup settings and provider data policy; no blanket deletion promise |

Keep application logs at the proposed 30 days. Document actual Cloud Trace retention separately; log retention does not control traces. Persisted trace IDs remain with existing suggestion rows. Preserve workflow content and replay journals; no usage-counter table or cleanup is introduced.

Use the existing provider account dashboard for a manual spending check. Sampled traces and diagnostic call logs are not a billing ledger; token/cost collection, attribution, and reconciliation belong to the later analytics design.

The existing cloud budget sends alerts; it does not stop these resources. Queue pause stops new dispatch but not the API's clarification call path, active provider calls, or ongoing database charges. To contain provider spend, use the dedicated key's controls and the existing release/operations procedure; do not assume queue pause shuts down all AI work.

## Runbooks linked from alerts

### Application failure

Open the attached service/event filter and follow its trace link. If the trace is absent or incomplete, use `suggestion_id` or HTTP request ID in logs and inspect saved state. Check whether the failure is enqueue, saved provider output, scheduled expiry, agent choice, or an unexpected fault. A worker 204 can contain a saved failure; a 503 live-claim retry can be expected. Read the saved workflow result before trying again. Repeating an uncertain provider request with a new ID can incur another charge. Use Guide 20 for queue containment and compatible API/worker rollback.

### Queue backlog

Check whether the queue was deliberately paused. Otherwise inspect worker revision, invocation IAM, task response codes, database readiness, and terminal workflow state. Do not reset provider claims, change task IDs, or multiply retries. Restore the valid worker/configuration, resume the queue, and verify it drains. Missing telemetry is not a healthy queue.

### Database connections

Compare current connections with usable capacity. Check overlapping Cloud Run revisions/instances, application pool settings, migration jobs, and operator sessions. Stop unnecessary test clients and finish or roll back a faulty rollout before increasing limits. Never kill unidentified sessions just to clear an alert.

### Cost warning

Open the project billing view and provider-key usage separately. Compare dates, model, calls, and cloud resource changes. Remember SQL idle cost and trace ingestion/storage cost; sampled traces do not account for provider spend. Use the chosen provider controls for AI spend; consult existing operations guidance for infrastructure changes. Per-user quota enforcement is deferred; existing queue/provider bounds are not a complete public-signup abuse control.

## Acceptance record

| Check | Result | Evidence/date |
| --- | --- | --- |
| Structured stdout/stderr privacy and context tests | Local pass | 688-test API suite observed 2026-09-17, including serialized-output redaction, context isolation, SSE/threadpool/shutdown checks; live Cloud Run log-output check pending |
| One API → database → task → worker → provider → saved result waterfall | Pending | Requires deployed Phase 21 and trace URL |
| Queue delay and repeated-delivery context | Local pass (harness); live pending | Local duplicate/retry/queue-wait tests pass; live queue-delay drill and trace evidence pending |
| Replay/legacy context and unchanged business behavior | Local pass | Same-ID replay link, legacy/malformed fallback, and unchanged business outcomes covered by API tests observed 2026-09-17 |
| Span/log privacy and sampling behavior | Local pass | Sentinel redaction and sampled-out-failure logging covered by API tests observed 2026-09-17; Cloud Trace attribute check pending |
| Bounded export and idle/shutdown delivery | Local pass | 2 s flush budget, unreachable-exporter, idle/shutdown delivery covered by API tests observed 2026-09-17; Cloud Run idle check pending |
| Backlog email and recovery | Pending | Requires authorized drill |
| Saved expiry failure and actionable email | Pending | Requires authorized drill |
| SQL threshold email and restoration | Pending | Requires authorized drill |
| Sanitized Error Reporting fixture | Pending | Requires deployed telemetry |
| Retention and cost review | Pending | Requires live inventory |
| Final Terraform state and restored sample rate/queue/configuration | Pending | Requires deployment/drills |

Implementation, automated verification, and live acceptance are separate milestones. Record observed evidence and agreed deferrals; do not mark this phase complete from a dashboard screenshot or a successful mock plan.
