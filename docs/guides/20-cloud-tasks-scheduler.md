# Phase 20: Cloud Tasks delivery and scheduled expiry

**Status:** Repository-ready; live rehearsal pending. Implementation (Tasks 1–6)
is merged on this branch; no live cloud activation, paid provider rehearsal, or
disruptive drill has been observed. Every acceptance row below stays pending
until a learner-authorized rehearsal records real evidence.

**Spec:** [Phase 20 design](../superpowers/specs/2026-09-15-cloud-tasks-scheduler-design.md)
**Plan:** [Phase 20 plan](../superpowers/plans/2026-09-15-cloud-tasks-scheduler.md)

## Prerequisites

- Phase 19 delivery is active and its walkthrough is understood
  ([Guide 19](19-continuous-delivery.md)), especially
  [Pause delivery](19-continuous-delivery.md#pause-delivery) and
  [Manual rollback](19-continuous-delivery.md#manual-rollback).
- A Phase 20-compatible image (contains `app.worker` and migration
  `2026091501`) built, scanned, and verified by digest.
- Reviewed Terraform values for `async_suggestions` (worker image digest,
  queue/Scheduler names, invocation and worker account IDs, numeric database
  and provider secret versions/keys, provider model). Secret payloads and
  versions stay outside the repository; Terraform records numeric versions only.
- Learner authorization before any cloud apply, paid provider call, or
  disruptive drill. Normal CI uses PostgreSQL plus injected fakes — never
  Google credentials or paid calls.

## Transaction gap

The reservation row is durable intent, but **not an automatically dispatched
outbox**. The public route commits the reservation first, then enqueues:

1. `POST /todo-workflows/{id}/suggestions` reserves with `queued=True`
   (goal/clarification snapshots, database-clock `queued_at`, `expires_at =
   queued_at + 15 minutes`) inside the existing reservation transaction.
2. The transaction commits; only then does the route create the Cloud Tasks
   task in a threadpool worker.
3. Same-ID replay re-reads the row: still-pending and unclaimed rows retry
   enqueue under the stable task name; `AlreadyExists` is accepted as
   duplicate success, never as proof that a task is still queued.

If the process dies between commit and create, or the create response is lost,
the saved reservation remains and the same request ID repairs enqueue on
retry — never a new ID. No provider or cloud call runs inside a database
transaction. New IDs keep the existing explicit-supersession semantics, and a
new “Try suggestions again” action warns that an earlier provider call may
have been billed.

## Provider attempt policy

At most one application-initiated provider attempt per asynchronous
reservation; the claim (`provider_started_at`) is permanent and never reset.

- The worker locks workflow first, then the suggestion row (the same order as
  reservation/claim/cleanup), re-reads after locking, and commits the claim
  before calling the provider with its existing 30-second deadline.
- Duplicate delivery inside the 2-minute claim window returns `503` without
  calling the provider; after the window the handler records
  `failed/timeout` and acknowledges. Known terminal duplicates return `204`.
- A crash after claiming but before the provider call loses useful work; a
  crash after provider success but before commit may lose a billed result.
  Neither case triggers an automatic repeat provider call — an explicit new
  user request may incur a new charge.
- Expected provider failures persist as `failed/<code>` and are acknowledged,
  not retried. Database outages and unexpected errors return sanitized `503`
  so Tasks can retry. Malformed/version-unknown bodies return `400`/`422`
  (oversized bodies `413`) and consume the bounded queue attempts.
- Queue rate limits bound dispatch throughput, not total demand or dollar
  spend. They are not a monetary cap; neither are cloud budget alerts.
  Provider token/deadline bounds apply, plus a learner-chosen provider credit
  cap where supported.

Every bound in one place:

| Control | Value |
| --- | --- |
| Task body | `{"version":1,"suggestion_id":N}`, at most 1024 bytes |
| Task ID | `suggest-v1-` + SHA-256 of `<row ID>:<request fingerprint>` |
| Queue dispatch / concurrency | 1 per second / 2 |
| Queue attempts / retry duration | 5 / `0s` (attempt-limited) |
| Queue backoff min / max / doublings | 10 s / 60 s / 3 |
| Queue operation-log sampling | 1.0 (low-volume sandbox) |
| Task dispatch deadline / worker request timeout | 60 s / 60 s |
| Enqueue RPC timeout / SDK retries | 5 s / disabled (`retry=None`) |
| Provider deadline | 30 s (existing) |
| Abandoned-claim expiry | 2 minutes (never reclaimed) |
| Pending reservation lifetime | 15 minutes |
| Worker instances / concurrency / resources | min 0, max 1 / 2 / 1 CPU, 512 MiB |
| Scheduler schedule / timezone | `*/5 * * * *` / `Etc/UTC` |
| Scheduler attempt deadline / retries | 30 s / 0 (starts paused) |
| Cleanup batch / statement timeout | 100 rows / 5 s |
| Client pending refresh | one GET in flight, every 3 s, up to 2 minutes per session |

## Bootstrap

First activation ships the compatible image **without** activating cloud mode.
`CLOUD_WORKER_SERVICE` absent preserves the exact Phase 19 path.

1. Build and verify one Phase 20-compatible image. Confirm the worker entry
   point inside the built container:
   `docker exec <container> python -c 'import app.worker'`.
2. Deploy it with inline mode still active (`SUGGESTION_EXECUTION` unset or
   `inline`) and no worker release target. Drain legacy inline requests.
3. Pause delivery with the Guide 19 process (`DELIVERY_ENABLED=false`,
   disable `release.yml`, inspect runs; never cancel an active mutation to
   free the lock).
4. Apply the reviewed Terraform locally with the verified image digest
   (`async_suggestions.worker_image` must be an immutable digest).
5. Verify IAM: no `allUsers`/`allAuthenticatedUsers` on the worker; the
   invocation account holds `roles/run.invoker` on the worker only; the API
   runtime holds queue-scoped `roles/cloudtasks.enqueuer` plus
   `roles/iam.serviceAccountUser` on the invocation identity; the worker
   runtime holds only Cloud SQL access plus the two numeric secret versions.
6. Smoke private invocation with a short-lived ID token from the invocation
   account against the canonical `run.app` root audience (never reuse an
   OAuth access token; mask the token; include the email claim).
7. Verify `GET /ready` (bounded `SELECT 1`) and an empty-object
   `POST /internal/suggestions/expire` returning `{"expired": N}`.
8. Set cloud-mode API configuration (`SUGGESTION_EXECUTION=cloud_tasks`,
   `GOOGLE_CLOUD_PROJECT`, `CLOUD_TASKS_LOCATION`, `CLOUD_TASKS_QUEUE`,
   `SUGGESTION_WORKER_URL` as a bare `https://<host>.run.app` origin,
   `TASK_INVOKER_SERVICE_ACCOUNT`) and the worker release variables
   (`CLOUD_WORKER_SERVICE`, `CLOUD_TASK_INVOKER_SERVICE_ACCOUNT`).
9. Resume Scheduler and delivery only after private smoke and enqueue checks
   pass. Startup fails on unknown mode or incomplete cloud config; cloud mode
   never falls back to inline on enqueue error.

A return to pre-Phase-20 code is not ordinary traffic-only rollback: stop
enqueue, pause queue and Scheduler, drain or expire outstanding work, then
restore inline stable configuration while delivery is paused. Pausing does not
cancel a running handler — inspect claims before recovery.

## Local verification

Repository checks use PostgreSQL plus fakes; no Google credentials needed:

```sh
pnpm db:test:up
uv run --directory apps/api python -m pytest tests/test_suggestion_worker.py tests/test_suggestion_tasks.py -q
uv run --directory apps/api ruff check .
pnpm test:release
bats tests/repository_contract.bats
git diff --check
```

Web E2E stays inline/deterministic; component and PostgreSQL tests exercise
async mode. Terraform checks require a local `terraform` binary (pinned
1.14.7; see `infra/terraform/README.md`):

```sh
terraform -chdir=infra/terraform/sandbox validate
terraform -chdir=infra/terraform/sandbox test
```

Inspect queue configuration, attempts, logs, and metrics in native Google
tools after activation:

```sh
gcloud tasks queues describe "$CLOUD_TASKS_QUEUE" \
  --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
gcloud tasks list --queue="$CLOUD_TASKS_QUEUE" \
  --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
gcloud logging read 'resource.type="cloud_tasks_queue"' --freshness=1h --limit=20
```

A poison task is a task whose body repeatedly fails validation (`400`/`422`
in worker logs) and burns queue attempts without progress. Identify it by the
task name in the worker logs, inspect its attempts with `gcloud tasks
describe`, then delete that one task explicitly — never purge the queue to
fix one bad task. Queue exhaustion has no application callback or
dead-letter queue; Scheduler expiry (`failed/timeout`) is the eventual
database transition.

## Failure drills

Run only with learner authorization, on a disposable sandbox workflow, with
no unbounded paid generation. Never label a local simulation as deployed proof.

- **Duplicate delivery:** submit one disposable request, record its DB row ID
  and task name, deliver the same body twice, and count provider attempts
  (expect exactly one).
- **Lost enqueue response:** simulate through a local test proxy/wrapper that
  drops the first create response, then replay the same ID and confirm
  `AlreadyExists` reconciles to one row — never with production fault flags.
- **Retry exhaustion:** use a disposable authenticated task target that fails
  before claim, exhaust the 5 attempts, then verify cleanup expiry marks the
  row `failed/timeout`.
- **Post-provider crash:** inject the failure in the local worker test harness
  (fail between provider success and commit); separately record which cloud
  failure, if any, was actually observed live.
- **Queue pause/backlog:** pause the queue, confirm dispatches stop and the
  reservation stays pending, resume, and confirm delivery without new user
  action. Rehearse cleanup replay the same way.
- **Poison task:** deliver a version-unknown body to a disposable target,
  watch attempts exhaust, identify it in logs, and delete that task.

## Pause and recovery

Pausing stops future dispatch; it does not cancel a running handler and does
not roll back completed provider work. Before any recovery mutation, inspect
claims (`provider_started_at`) to see what already ran.

```sh
gh variable set DELIVERY_ENABLED --body false
gh workflow disable release.yml
gh run list --workflow release.yml
# Wait for the active deployment to finish; cancel only identified pending runs.
gcloud tasks queues pause "$CLOUD_TASKS_QUEUE" \
  --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
gcloud scheduler jobs pause "$SCHEDULER_JOB" \
  --project="$CLOUD_PROJECT" --location="$CLOUD_REGION"
```

Recovery order for compatible (Phase 20) revisions: restore attempted
promotions API-then-worker to the captured revisions from the release
summary, attempting both restores even if the first fails; verify each with
its smoke (`scripts/release_smoke.py` for the API, authenticated
`/health` + `/ready` for the worker); remove only this release's tags; keep
delivery paused until the failure is fixed. Migration downgrades are never
part of rollback — the expanded database stays.

Returning to pre-Phase-20 code additionally requires: confirming no
unclaimed pending cloud rows remain (run the expire sweep or wait out the
15-minute lifetime), expiring or draining claimed work, disabling cloud
enqueue, and restoring inline stable configuration — all while delivery is
paused.

## Acceptance record

**Status: pending.** No live rehearsal has been conducted on this branch.
Local PostgreSQL/fake suites (Tasks 1–4, 6) prove behavior without cloud
credentials; they are not deployed proof.

| Spec acceptance case | Result | Evidence / run URL | Date | Limitation |
| --- | --- | --- | --- | --- |
| Authenticated invocation succeeds; denied identity is rejected | Pending | — | — | Requires live IAM drill |
| Real queued request completes and is reviewed on web | Pending | — | — | Requires live rehearsal |
| Real queued request completes and is reviewed on iOS | Pending | — | — | Requires live rehearsal |
| Restart recovery after queueing | Pending | — | — | Requires live rehearsal |
| Duplicate delivery, unchanged provider count | Pending | — | — | Local harness proves once-only claim; live count unobserved |
| Lost enqueue response reconciles same ID | Pending | — | — | Local proxy test proves reconcile; live unobserved |
| Deliberate timeout records `failed/timeout` | Pending | — | — | Requires live rehearsal |
| Deliberate crash after claim never auto-retries provider | Pending | — | — | Harness injection proves no auto-retry; live crash unobserved |
| Retry exhaustion then cleanup expiry | Pending | — | — | Requires live disposable-target drill |
| Queue pause/throttling then backlog delivery | Pending | — | — | Requires live rehearsal |
| Repeated cleanup sweep is safe | Pending | — | — | PostgreSQL replay tests pass; live schedule unobserved |
| Poison-task identification and removal | Pending | — | — | Requires live rehearsal |
| One successful two-service release | Pending | — | — | Release script tested with fakes only |
| Rollback restores both services | Pending | — | — | Restore logic tested with fakes only |
| Final no-drift Terraform plan | Pending | — | — | Requires local plan after rehearsal |

## Cleanup

- Delete disposable sandbox workflows and their suggestion rows through the
  existing app flows; cleanup never deletes rows itself — it only marks
  expired pending rows `failed/timeout`.
- Delete identified poison tasks individually (`gcloud tasks delete`); never
  purge the queue.
- After the rehearsal, run a local Terraform plan confirming no
  release-field drift, then update phase completion status using repository
  conventions. Keep unobserved cases pending.
