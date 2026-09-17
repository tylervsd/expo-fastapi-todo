# Phase 20: Cloud Tasks and Cloud Scheduler

**Status:** Draft for learner review; implementation is not authorized by this document.

**Date:** 2026-09-15

**Base:** `main` at `2d20848`, following recorded Phase 19 acceptance.

**Branch:** `codex/phase-20-cloud-tasks-scheduler`

**Worktree:** `.worktrees/phase-20-cloud-tasks-scheduler`

**Plan:** [Implementation plan](../plans/2026-09-15-cloud-tasks-scheduler.md)

## Outcome

A signed-in user requests suggestions and immediately gets a saved pending
request. Cloud Tasks delivers that request to a private Cloud Run worker. The
user can leave, return, review the saved suggestions, and explicitly confirm
creation through the existing workflow. Cloud Scheduler expires abandoned work
in a small, repeatable database operation.

This is an architectural phase: asynchronous execution adds a service boundary,
changes the POST response timing, and extends deployment to a second service.
Both this spec and its plan are proposed together for review.

## Existing behavior and constraints

- `main.py` currently reserves a suggestion, calls OpenRouter within the HTTP
  request, then finishes it in a separate transaction.
- `suggestion_service.py` already enforces owner, request fingerprint, workflow
  revision, step identity, current-request selection, and saved-result replay.
- `WorkflowSuggestionRequestRow` has no timestamps or persisted provider input.
  Its public states are `pending`, `ready`, `failed`, and `superseded`.
- The agent's suggestion tool uses the same frontend suggestion POST. Its
  promise waits for a matching saved result; the AG-UI transport itself need
  not become a background job.
- The client has status fetching, restart recovery, safe draft reconciliation,
  and agent waiter settlement. It has no periodic timer despite comments using
  the word “poller.” Phase 20 must implement bounded automatic status refresh.
- Phase 19 builds one image, migrates, tests a candidate, and changes API
  traffic. Terraform owns stable settings; releases own image/revision/traffic.
  The image vulnerability scan is currently advisory; preserve that policy.

## Design choices

### Recommended: one private worker using the existing image and table

Run a separate FastAPI entry point from the same image, backed by the existing
Cloud SQL database. Persist execution metadata on suggestion rows. Use one
Cloud Tasks queue and one Scheduler cleanup job. Google Cloud IAM protects the
worker; the public API never mounts its routes.

### Alternatives considered

1. Put task routes on the public API and verify OIDC in application code. This
   avoids a service but adds a second authentication system to an internet-facing
   application. A separate IAM-protected entry point is easier to demonstrate.
2. Add a generic outbox dispatcher and reclaimable execution leases. This can
   improve automatic recovery but adds orchestration and can repeat a paid
   provider call after a crash. The curriculum does not require that guarantee.

The reservation row is durable intent, but **not an automatically dispatched
outbox**. The POST attempts enqueue after commit; same-ID retry repairs an
uncertain enqueue. An abandoned reservation eventually expires. This deliberately
trades automatic eventual dispatch for less machinery and a clear user recovery.

## Global constraints

- Reuse the existing suggestion table, public status/error enums, and workflow confirmation path.
- No provider call or cloud API call runs inside a database transaction.
- At most one application-initiated provider attempt per asynchronous reservation; never reset its claim.
- Task bodies contain only `{"version":1,"suggestion_id":123}` and are at most 1024 bytes.
- Normal CI uses PostgreSQL and injected fakes; no Google credentials or paid provider calls.
- Terraform is applied locally; release CI has no Terraform or state-bucket access.
- Worker routes are absent from the public API and require Cloud Run IAM in deployment.
- No todo is created until the existing user-confirmed workflow action succeeds.

## Public contract and user experience

Keep `POST /todo-workflows/{workflow_id}/suggestions`, its existing request body,
owner authentication, and response schema. In cloud mode:

| Situation | Response |
| --- | --- |
| New reservation and task created, or deterministic task already exists | `202` with current suggestion snapshot |
| Same ID/fingerprint still pending | Retry enqueue if unclaimed; return `202` pending |
| Same ID already ready | `200` with saved result, no enqueue/provider call |
| Same ID already failed | Existing mapped provider error; GET exposes saved failure |
| Same ID with different fingerprint | Existing `409 request_id_reused` |
| Invalid/stale workflow or superseded request | Existing conflict behavior |
| Enqueue unavailable or response uncertain | `503` with `detail.code=enqueue_unavailable`; reservation remains saved |

A task can finish before POST returns: return `200` if reconciliation sees a
ready snapshot. A `202` acknowledges durable pending work and accepted enqueue,
not successful generation. `AlreadyExists` acknowledges name deduplication, not
proof that a task is still queued. The database decides the result.

GET remains read-only and owner-scoped. Replaying an enqueue failure uses the
same request ID and original payload. Do not automatically generate a new ID.
A new explicit “Try suggestions again” action gets a new ID and warns that an
earlier provider call may have been billed. Preserve manual entry and cancellation.

Refresh pending status every 3 seconds with at most one GET in flight for up to
2 minutes per active foreground session. Stop on terminal status, logout, workflow
change, unmount, or app background. Foregrounding triggers one immediate GET
and starts a new 2-minute budget, as specified in the implementation plan.
After the time budget or a network failure, show “Check status” and existing
recovery controls. Do not automatically repeat POST. Check status remains usable
while the agent card is waiting; terminal failure/supersession must reject its
waiter and release locks. An unchanged pending GET must not restart the budget.

Preserve edited drafts, accessibility announcements for pending/ready/error,
keyboard controls, and existing epoch/identity checks that reject late responses.
No new screen, global state store, or generic polling abstraction is required.

## Durable data and execution policy

Add nullable fields to `todo_workflow_suggestion_requests`:

| Field | Meaning |
| --- | --- |
| `queued_at` (`timestamptz`) | Cloud-mode reservation creation time, from the database clock |
| `expires_at` (`timestamptz`) | Latest useful completion time: queued time + 15 minutes |
| `provider_started_at` (`timestamptz`) | Permanent claim marker; null means no attempt has been claimed |
| `goal_snapshot` (`text`) | Validated goal used by this reservation |
| `clarification_snapshot` (`jsonb`) | Null or canonical `{field,value}` from existing validation |

All null execution fields identify legacy/inline records. Cloud rows require a
bounded canonical goal, queued time, and expiry; validate clarification through
the existing service contract. Add checks for coherent nullability and timestamp
ordering, plus a partial expiry index for pending cloud rows. No new public enum
or public timestamp is needed. Do not backfill historical pending rows into work;
they lack reconstructable clarification. Existing recovery can supersede them.

`reserve_suggestion` gains a keyword-only `queued: bool = False`. Cloud mode
writes snapshots/timestamps inside the existing reservation transaction. Same-ID
pending cloud replay returns its snapshot so the caller can retry enqueue;
legacy inline pending retains its current conflict behavior. A new ID retains
existing explicit supersession semantics.

### Claim, execute, finalize

1. Load the row by internal ID to discover owner/workflow. Acquire locks in the
   existing order: workflow first, suggestion second. Re-read the row after locks.
2. Reject unsupported payload versions before lookup. A missing, terminal,
   legacy, expired, superseded, cancelled, or stale row never calls the provider.
   Mark expired pending cloud rows failed with existing `timeout`; mark invalid
   workflow/current-request matches superseded. Return success to discard work.
3. If `provider_started_at` is null, set it to the database clock and commit.
   Return the immutable input and marker as a `ClaimedSuggestion` value.
4. Call the existing provider once, using its existing 30-second deadline,
   output validation and token limit. Do not add automatic provider retries.
5. Finalize in a fresh transaction only if the row is still pending, its claim
   matches, the workflow revision/step/current-request checks still pass, and
   neither expiry threshold has passed. Persist a ready result or existing
   provider error; workflow changes produce supersession. Late writes are no-ops.

The claim expiry threshold is `provider_started_at + 2 minutes`. It never grants
a replacement claim. Duplicate delivery during that window returns `503` without
calling the provider; after it, the handler atomically records `failed/timeout`
and acknowledges. A known terminal duplicate returns `204` immediately.

The permanent claim can lose useful work if the worker crashes after claiming
but before calling. If it crashes after provider success but before database
commit, the result may be lost and the call may be billed. Neither case causes
automatic repeat provider work. An explicit new user request may incur a new
charge. This is an application attempt policy, not an exactly-once billing claim.

## Queue adapter and transaction gap

Add one concrete Cloud Tasks adapter using the official Python client and ADC.
Select and lock a release compatible with the repository's Python 3.14 runtime
when implementing; validate imports inside the production image.

Configuration: `SUGGESTION_EXECUTION=inline|cloud_tasks` (default `inline`),
`GOOGLE_CLOUD_PROJECT`, `CLOUD_TASKS_LOCATION`, `CLOUD_TASKS_QUEUE`,
`SUGGESTION_WORKER_URL`, and `TASK_INVOKER_SERVICE_ACCOUNT`. Cloud mode fails
startup on missing configuration; it never falls back to inline on enqueue error.
Keep deterministic inline execution for current local development/E2E; both modes
reuse result validation and finalization rules where applicable.

Task ID is `suggest-v1-` plus SHA-256 of the row's decimal internal ID, a colon,
and its existing request fingerprint. This is stable across retries and spreads
IDs without exposing user content. Use an explicit HTTPS POST target ending in
`/internal/suggestions`, JSON content type, version 1 body, and OIDC audience equal
to the worker's canonical root `run.app` URL. Request body/user headers cannot
choose URL, queue, identity, or audience.

Disable implicit SDK create retries and set a 5-second RPC timeout. Run the
synchronous client off the async request event loop. Commit reservation first,
then create; only `AlreadyExists` is accepted as duplicate success. Credential,
permission, network, and timeout errors produce the sanitized `503` above.
Re-read before enqueue to avoid submitting known terminal/claimed work; races
remain harmless because workers validate database state. Do not create a new
name to escape a tombstone or extend the original deadline on retries.

Cloud Tasks can deliver duplicates and provides no ordering guarantee; neither
property is a workflow correctness mechanism. [Cloud Tasks limitations](https://docs.cloud.google.com/tasks/docs/common-pitfalls)

## Private worker and authenticated cleanup

`app.worker:app` exposes only:

- `GET /health`: existing small health response; platform IAM still applies.
- `GET /ready`: bounded database `SELECT 1` for authenticated release readiness.
- `POST /internal/suggestions`: strict version/positive integer schema and
  1024-byte body limit, invokes the claim/execution sequence, returns `204`.
- `POST /internal/suggestions/expire`: empty JSON object, runs one bounded sweep,
  returns `200 {"expired":N}`.

No public auth, todo, agent, or workflow routes are mounted here. IAM invocation
is mandatory, ingress may remain `INGRESS_TRAFFIC_ALL` for Google HTTP delivery,
and there is no `allUsers` or `allAuthenticatedUsers` binding. “Private” means
IAM protected, not a newly introduced VPC/network topology. Do not trust task
name or Scheduler headers as authentication. Local tests instantiate the worker
factory with fake provider/session seams; no production auth-bypass flag exists.

Use one narrowly privileged invocation service account for Tasks and Scheduler;
both are trusted to invoke either internal operation. It has no database, secret,
enqueue, or deployment rights. A separate worker runtime identity accesses only
the existing database/provider secret versions and Cloud SQL. The API runtime
gets queue-scoped `roles/cloudtasks.enqueuer` and `roles/iam.serviceAccountUser`
on the invocation identity. Preserve the managed Tasks/Scheduler service-agent
roles needed to mint tokens; never grant project-wide Token Creator as a shortcut.
OIDC and Cloud Run invocation follow the official
[Tasks integration](https://docs.cloud.google.com/run/docs/triggering/using-tasks)
and [Scheduler authentication](https://docs.cloud.google.com/scheduler/docs/http-target-auth).

## Bounds, cleanup, and failure handling

| Control | Initial value |
| --- | --- |
| Queue dispatch rate / concurrent dispatches | 1 per second / 2 |
| Queue attempts / retry duration | 5 / `0s` (attempt-limited, no additional duration condition) |
| Queue minimum / maximum backoff / doublings | 10 seconds / 60 seconds / 3 |
| Queue operation-log sampling ratio | 1.0 for this low-volume sandbox |
| Task dispatch deadline / worker request timeout | 60 seconds / 60 seconds |
| Provider deadline / abandoned-claim expiry | Existing 30 seconds / 2 minutes |
| Pending reservation useful lifetime | 15 minutes |
| Worker instances / concurrency / resources | min 0, max 1 / 2 / 1 CPU, 512 MiB |
| Scheduler schedule / timezone | `*/5 * * * *` / `Etc/UTC` |
| Scheduler attempt deadline / retries | 30 seconds / 0 |
| Cleanup batch / database statement timeout | 100 rows / 5 seconds |

Retry-count semantics are explicit: a nonzero retry duration can interact with
attempt exhaustion; use the attempt-only setting and verify the effective queue
configuration. [Queue RetryConfig](https://docs.cloud.google.com/tasks/docs/reference/rest/v2/projects.locations.queues#RetryConfig)

Cleanup selects pending cloud rows past either expiry threshold, in stable ID
order, using database time. Lock workflow then suggestion consistently, skip
locked workflows, recheck predicates, and change at most 100 rows to
`failed/timeout`. Do not delete rows, journal entries, workflows, todos, or queue
resources. Replays and overlaps are safe because only pending expired rows match;
no schedule ledger is needed. No provider calls or enqueue repair happen here.
There is no exact wall-clock completion SLA: backlog, skipped locks, or Scheduler
failure can delay expiry. A late task also applies the expiry rule itself.

Database unavailability and unexpected worker errors return sanitized `503` so
Tasks can retry. Expected provider failures are persisted and acknowledged, not
retried. Malformed/version-unknown task bodies return `400/422` and consume the
bounded queue attempts; document inspecting/deleting an identified poison task.
Cloud Tasks exhaustion has no application callback or dead-letter queue in this
design. Scheduler provides the eventual database timeout transition.

Queue rate limits bound dispatch throughput, not total user demand or dollar
spend. Retain provider token/deadline bounds, configure a learner-chosen provider
credit cap where supported, and teach queue pause plus the existing cloud budget
alerts. New user-wide quotas, monitoring dashboards, alert policies, and cost
accounting belong to Phase 21. Log only IDs, outcome, duration, and safe error
codes; never goals, clarification, proposals, raw provider responses, or tokens.

## Infrastructure and delivery

Add opt-in `async_suggestions` Terraform configuration, default null. It owns
queue, worker service, invocation/runtime identities and grants, Scheduler job,
and stable environment/resources. Enable Cloud Tasks and Scheduler APIs through
existing service ownership. Reuse existing Cloud SQL attachment and numeric
secret versions. Scheduler starts paused. Expose worker URI, queue name, and
invoker email; no secret outputs.

Bootstrap cannot launch `app.worker` from a Phase 19 image. First ship the Phase
20-compatible image with inline mode still active and no worker release target.
Then pause delivery, apply reviewed Terraform with that verified digest, test
private invocation, configure API cloud-mode environment, and configure the
worker release target. Drain legacy inline requests before activation. Resume
Scheduler and delivery only after private smoke and enqueue checks pass.

Extend the existing serialized release, preserving one build and one migration:

1. Capture API and worker serving revisions independently; reject split traffic.
2. Run compatible migration; deploy worker candidate with no traffic and the
   same digest; verify authenticated health and database connectivity.
3. Promote and verify worker before deploying/promoting the API candidate.
4. On later failure restore any attempted API and worker promotions to their
   captured revisions, attempting both restores even if the first fails.
5. Record both services, smoke results, digests, observed traffic, and failures;
   remove only this release's tags. Never hide failures after successful restore.

Use the bounded database `SELECT 1` readiness route `GET /ready` for release
smoke; no mutations or provider calls. Use a short-lived
ID token from the invocation account for smoke with canonical service audience,
including when calling a tagged URL, and include the service-account email claim.
Grant CI token creation on this account
only; keep deployment/act-as grants scoped to the worker. Never reuse the OAuth
access token as an ID token. Mask tokens and avoid command-line/log exposure.

Worker/app mixed versions must preserve version 1 task payloads and additive
schema compatibility. Rollback cannot undo already completed tasks. Rollback to
pre-Phase-20 code requires disabling cloud enqueue, pausing queue/Scheduler,
draining or expiring outstanding work, and restoring compatible inline API
configuration while delivery is paused. Normal release rollback targets only
Phase-20-compatible revisions; first activation has its own operator runbook.
Terraform narrowly ignores worker release fields, matching the API pattern.

## Acceptance and testing

Automated coverage concentrates on PostgreSQL/API tests and client components:

- Same-ID enqueue retry, lost create response, fingerprint conflict, owner isolation.
- Concurrent/duplicate delivery, permanent claim, crash before/after provider,
  failed finalization, lost success acknowledgement, stale/cancelled/superseded work.
- Cleanup expiry boundaries, replay, competing finalization, bounded batches,
  and exclusion of legacy, ready, and failed rows.
- Validated task target/body/OIDC configuration, SDK timeouts and sanitized errors.
- Pending-to-ready/failure UI, bounded polling, restart/background/logout races,
  agent lock release, edited draft preservation, and explicit new-request warning.
- Migration compatibility, Terraform least privilege/bounds, and two-service
  release failure/restore behavior. No cloud token verification is “proved” by mocks.

Live learner acceptance separately records authenticated and denied invocation,
real queued request and review on web/iOS, restart recovery, duplicate delivery
with unchanged provider count, lost enqueue response, deliberate timeout/crash,
retry exhaustion, queue pause/throttling, repeated cleanup, poison-task removal,
one successful two-service release, rollback, and a final no-drift Terraform plan.
Use a disposable sandbox workflow for fault drills. Any paid provider call or
intentional live disruption is part of the later explicitly authorized rehearsal.
Do not mark Phase 20 complete from mock tests or deployment alone.

## Non-goals

No generic task framework, Celery/Redis, Pub/Sub, automatic provider retry,
exactly-once billing promise, reclaimable leases, general outbox, new AG-UI
protocol, arbitrary worker payload, automatic todo creation, database retention
policy, monitoring platform, or infrastructure deployment pipeline.
