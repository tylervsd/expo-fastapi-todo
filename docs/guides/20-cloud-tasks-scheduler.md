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

> Authorization gate: every `gcloud`/`terraform`/`gh` command below is an
> operator instruction for a learner-authorized session. None of them has
> been run on this branch; live activation stays pending until the learner
> authorizes it. Set the required variables first — angle brackets are
> learner input, never committed values:
>
> ```sh
> export CLOUD_PROJECT="<sandbox-project-id>"
> export CLOUD_REGION="<sandbox-region>"          # Cloud Run + Scheduler location
> export CLOUD_TASKS_LOCATION="<tasks-location>"  # same region as var.region
> export CLOUD_TASKS_QUEUE="<suggestions-queue>"   # var.async_suggestions.queue_name
> export SCHEDULER_JOB="<suggestion-expiry-job>"   # var.async_suggestions.scheduler_name
> export CLOUD_SERVICE="<api-service-name>"        # var.api.name
> export WORKER_SERVICE="<phase20-worker-name>"    # var.async_suggestions.worker_name
> export INVOKER_SA="<invoker-sa-email>"           # output suggestion_invoker_email
> export WORKER_URL="https://<worker-host>.run.app" # output suggestion_worker_uri (bare origin)
> export IMAGE_DIGEST="<registry-path>@sha256:<64-hex>"  # verified compatible image
> ```

1. Verify Terraform and workflows before merging. The local checks passed on
   2026-09-16 with Terraform 1.14.7 (21 mock tests) and actionlint 1.7.12.
   If `actionlint` is missing, install it with `brew install actionlint`.
   Terraform installation is documented in `infra/terraform/README.md`.

   ```sh
   terraform -chdir=infra/terraform/sandbox init -backend=false -lockfile=readonly
   terraform -chdir=infra/terraform/sandbox validate
   terraform -chdir=infra/terraform/sandbox test
   actionlint .github/workflows/*.yml
   ```

   Review and merge the Phase 20 PR to `main` after the required checks pass.
   Before merging, verify API `SUGGESTION_EXECUTION` is unset or `inline` and
   both worker release variables are absent at repository and `sandbox`
   environment scope. Preserve the existing Phase 19 delivery configuration.

   ```sh
   gh variable list
   gh variable list --env sandbox
   ```

2. Use the Phase 19 release workflow to build and deploy the first compatible
   image in inline mode. The merge-triggered release can satisfy this step;
   dispatch manually only if another run is needed. Approve its sandbox
   environment deployment and wait for success. This runs the migration job
   with the same digest before deploying the API; a direct `gcloud run deploy`
   alone does not perform that migration.

   ```sh
   gh run list --workflow release.yml
   # Only if a release is needed and DELIVERY_ENABLED is true:
   gh workflow run release.yml --ref main
   ```

   Record `IMAGE_DIGEST` from the successful release summary. Verify migration
   `2026091501` completed, the API serves that digest, and inline suggestions
   still work. Drain active inline requests before cloud-mode activation.
   Run remaining local commands from the Phase 20 worktree containing the
   reviewed implementation.

3. Pause delivery with the Guide 19 process (`DELIVERY_ENABLED=false`,
   disable `release.yml`, inspect runs; never cancel an active mutation to
   free the lock). Expected: variable reads `false`, workflow disabled, no
   active mutation cancelled:

   ```sh
   gh variable set DELIVERY_ENABLED --body false
   gh workflow disable release.yml
   gh run list --workflow release.yml
   # Wait for the active deployment to finish; cancel only identified pending runs.
   ```

4. Apply the reviewed Terraform locally with `async_suggestions.worker_image`
   set to the step 2 release digest in uncommitted tfvars. This seeds the new
   worker with compatible code. Both API and worker images are release-owned
   after creation (`ignore_changes`); Terraform owns their stable configuration.
   Keep API execution inline and `async_suggestions.scheduler_paused = true`.
   Include Cloud Tasks and Scheduler APIs in the existing `enabled_services`.
   Expected: plan shows only the reviewed async additions with `$IMAGE_DIGEST`
   as the worker image; apply succeeds:

   ```sh
   terraform -chdir=infra/terraform/sandbox init -backend-config=backend.hcl
   # Local reviewed tfvars must set async_suggestions.worker_image to $IMAGE_DIGEST. Then:
   terraform -chdir=infra/terraform/sandbox plan -out=/tmp/sandbox-phase20.tfplan | tee /tmp/sandbox-phase20-plan.txt
   grep -F "$IMAGE_DIGEST" /tmp/sandbox-phase20-plan.txt  # worker image must be the verified digest
   # Inspect the plan; reject unexpected replacements, deletes, or unrelated changes.
   terraform -chdir=infra/terraform/sandbox apply /tmp/sandbox-phase20.tfplan
   terraform -chdir=infra/terraform/sandbox output suggestion_queue_name
   terraform -chdir=infra/terraform/sandbox output suggestion_worker_uri
   terraform -chdir=infra/terraform/sandbox output suggestion_invoker_email
   # The new queue starts running. Pause it before enabling cloud enqueue.
   gcloud tasks queues pause "$CLOUD_TASKS_QUEUE" \
     --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
   gcloud tasks queues describe "$CLOUD_TASKS_QUEUE" \
     --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION" \
     --format='value(state)'  # expect PAUSED
   ```

5. Verify IAM: no `allUsers`/`allAuthenticatedUsers` on the worker; the
   invocation account holds `roles/run.invoker` on the worker only; the API
   runtime holds queue-scoped `roles/cloudtasks.enqueuer` plus
   `roles/iam.serviceAccountUser` on the invocation identity; the worker
   runtime holds only Cloud SQL access plus the two numeric secret versions.
   Expected: no public members; exactly the scoped bindings:

   ```sh
   gcloud run services get-iam-policy "$WORKER_SERVICE" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --format=json | grep -E 'allUsers|allAuthenticatedUsers|run.invoker' || echo "no public bindings"
   gcloud run services get-iam-policy "$WORKER_SERVICE" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --flatten='bindings[].members' --format='value(bindings.members)' | grep "$INVOKER_SA"
   gcloud tasks queues get-iam-policy "$CLOUD_TASKS_QUEUE" \
     --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
   gcloud iam service-accounts get-iam-policy "$INVOKER_SA" --project="$CLOUD_PROJECT"
   ```

6. Smoke private invocation with a short-lived ID token from the invocation
   account against the canonical `run.app` root audience (never reuse an
   OAuth access token; mask the token; include the email claim).
   Expected: `/health` returns `{"status": "ok"}`; unauthenticated call fails:

   ```sh
   TOKEN=$(gcloud auth print-identity-token --impersonate-service-account="$INVOKER_SA" --audiences="$WORKER_URL" --include-email)
   curl -sS -H "Authorization: Bearer $TOKEN" "$WORKER_URL/health"
   unset TOKEN
   curl -sS -o /dev/null -w '%{http_code}\n' "$WORKER_URL/health"  # expect 401/403
   ```

7. Verify `GET /ready` (bounded `SELECT 1`) and an empty-object
   `POST /internal/suggestions/expire` returning `{"expired": N}`.
   Expected: `{"status": "ready"}` (or `ok`) and a JSON expired count:

   ```sh
   TOKEN=$(gcloud auth print-identity-token --impersonate-service-account="$INVOKER_SA" --audiences="$WORKER_URL" --include-email)
   curl -sS -H "Authorization: Bearer $TOKEN" "$WORKER_URL/ready"
   curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{}' "$WORKER_URL/internal/suggestions/expire"
   unset TOKEN
   ```

8. With delivery, queue, and Scheduler paused, add the cloud-mode values to
   the existing `api.plain_env` map in local uncommitted Terraform values.
   Preserve existing entries such as `OPENROUTER_MODEL`. Replace the example
   values below with the observed project and Terraform outputs:

   ```hcl
   # Entries to add to the existing api.plain_env map:
   SUGGESTION_EXECUTION          = "cloud_tasks"
   GOOGLE_CLOUD_PROJECT          = "<sandbox-project-id>"
   CLOUD_TASKS_LOCATION          = "<sandbox-region>"
   CLOUD_TASKS_QUEUE             = "<suggestions-queue>"
   SUGGESTION_WORKER_URL          = "https://<worker-host>.run.app"
   TASK_INVOKER_SERVICE_ACCOUNT  = "<invoker-sa-email>"
   ```

   Set `api.runtime.revision = null` in local tfvars so Cloud Run generates a
   fresh revision name; an existing release revision is immutable. Temporarily
   remove `template[0].revision` from the API resource's `ignore_changes` in
   `infra/terraform/sandbox/run.tf` for this configuration apply. Restore that
   entry immediately afterward, before subsequent plans or releases, so
   Terraform continues to ignore release-owned revision names. Do not commit
   the temporary lifecycle edit. After restoring it, run a follow-up plan and
   verify there is no API revision drift. Plan and
   apply the reviewed configuration. This creates the API configuration
   revision. Terraform preserves existing traffic, so explicitly route traffic
   to the verified new revision below to enable enqueue; the queue stays paused.
   GitHub variables alone do not configure the API container: `release.yml`
   consumes only the two worker release variables below.

   ```sh
   terraform -chdir=infra/terraform/sandbox plan -out=/tmp/sandbox-phase20-activate.tfplan
   # Inspect stable configuration, image preservation, and traffic before apply.
   terraform -chdir=infra/terraform/sandbox apply /tmp/sandbox-phase20-activate.tfplan
   gcloud run services describe "$CLOUD_SERVICE" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --format='yaml(spec.template.spec.containers[0].env)'
   API_REVISION=$(gcloud run services describe "$CLOUD_SERVICE" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --format='value(status.latestCreatedRevisionName)')
   gcloud run revisions describe "$API_REVISION" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --format='yaml(status.conditions,spec.containers)'
   # Verify readiness, the six settings, and the unchanged image before routing.
   gcloud run services update-traffic "$CLOUD_SERVICE" \
     --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
     --to-revisions="$API_REVISION=100"
   gh variable set CLOUD_WORKER_SERVICE --env sandbox --body "$WORKER_SERVICE"
   gh variable set CLOUD_TASK_INVOKER_SERVICE_ACCOUNT --env sandbox --body "$INVOKER_SA"
   gh variable list --env sandbox
   ```

   Verify the intended API revision is serving and the six non-secret settings
   above are correct. Do not copy secret values into output or acceptance records.

9. Re-enable delivery and run the two-service release. The workflow builds one
   image from `main`, runs migrations, then deploys worker and API with that
   same digest. It preserves the API configuration applied in step 8.
   Keep queue and Scheduler paused throughout the release.

   ```sh
   gh workflow enable release.yml
   gh variable set DELIVERY_ENABLED --body true
   gh workflow run release.yml --ref main
   # Approve the sandbox deployment and wait for a successful release.
   gh run list --workflow release.yml
   ```

   Record the new digest and both serving revisions from the release summary.
   Update the local `async_suggestions.worker_image` value to this digest for
   future provisioning. The image is ignored on existing resources; this update
   does not require an apply just to reconcile release-owned image changes.
   Verify observed traffic and revision image digests for both services.

   Submit one disposable suggestion through the app, verify the task is queued,
   then resume promptly (the pending reservation expires after 15 minutes):

   ```sh
   gcloud tasks list --queue="$CLOUD_TASKS_QUEUE" \
     --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
   gcloud tasks queues resume "$CLOUD_TASKS_QUEUE" \
     --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
   ```

   Verify the saved result in the app and the worker execution evidence. Enable
   Scheduler only after worker and cleanup checks pass: pause delivery again
   using step 3, set `async_suggestions.scheduler_paused = false` in local
   tfvars, review/apply a new saved plan, and confirm Scheduler is enabled.
   This keeps the schedule's enabled state consistent with Terraform. Resume
   delivery afterward and record the final no-drift plan.

   Startup fails on unknown mode or incomplete cloud config; cloud mode
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

Queue metrics live in Cloud Monitoring under the `cloudtasks.googleapis.com`
metric namespace. List available queue time series, then read dispatch,
attempt, and backlog signals (expected: one time-series entry per metric;
empty output means no dispatch activity in the window, not a broken query):

```sh
gcloud monitoring time-series list \
  --project="$CLOUD_PROJECT" \
  --filter='metric.type=starts_with("cloudtasks.googleapis.com/queue/")' \
  --format='value(metric.type)' | sort -u
gcloud monitoring time-series list \
  --project="$CLOUD_PROJECT" \
  --filter='metric.type="cloudtasks.googleapis.com/queue/task_attempt_dispatch_count"' \
  --format='table(metric.labels.queue_name, points.value.int64Value)'
gcloud monitoring time-series list \
  --project="$CLOUD_PROJECT" \
  --filter='metric.type="cloudtasks.googleapis.com/queue/task_attempt_count"' \
  --format='table(metric.labels.queue_name, points.value.int64Value)'
gcloud monitoring time-series list \
  --project="$CLOUD_PROJECT" \
  --filter='metric.type="cloudtasks.googleapis.com/queue/depth"' \
  --format='table(metric.labels.queue_name, points.value.int64Value)'
```

Console alternative: Monitoring → Metrics Explorer → resource type
`Cloud Tasks Queue`, then plot `Task attempt dispatch count`
(dispatches), `Task attempt count` (attempt outcomes), and queue depth
(backlog). Filter by `queue_name`; group by response code where offered to
separate `400`/`422` validation failures from `503` retries.

A poison task is a task whose body repeatedly fails validation (`400`/`422`
in worker logs) and burns queue attempts without progress. Identify it by the
task name in the worker logs, inspect its attempts, then delete that one
task explicitly — never purge the queue to fix one bad task:

```sh
gcloud tasks describe "<task-full-name>" \
  --queue="$CLOUD_TASKS_QUEUE" \
  --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
gcloud tasks delete "<task-full-name>" \
  --queue="$CLOUD_TASKS_QUEUE" \
  --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
```

Queue exhaustion has no application callback or
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
summary, attempting both restores even if the first fails. `API_PREVIOUS`
and `WORKER_PREVIOUS` come from the release summary; inspect each target
before cutover. Expected: each describe shows the recorded revision on the
expected sandbox service; each smoke passes; traffic ends on the previous
revisions with only this release's tags removed:

```sh
# 0. Inspect claims before any recovery mutation: what already ran
#    (provider_started_at set) must not be re-driven by hand.
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"suggestion"' \
  --project="$CLOUD_PROJECT" --freshness=2h --limit=50
TOKEN=$(gcloud auth print-identity-token --impersonate-service-account="$INVOKER_SA" --audiences="$WORKER_URL" --include-email)
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{}' "$WORKER_URL/internal/suggestions/expire"
unset TOKEN
# 1. Restore the API, then the worker — attempt both even if the first fails.
gcloud run revisions describe "$API_PREVIOUS" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION"
gcloud run services update-traffic "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --to-revisions="$API_PREVIOUS=100"
gcloud run revisions describe "$WORKER_PREVIOUS" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION"
gcloud run services update-traffic "$WORKER_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --to-revisions="$WORKER_PREVIOUS=100"
# 2. Verify each with its smoke (API stable URL, worker authenticated probes).
python3 scripts/release_smoke.py "$STABLE_URL"
TOKEN=$(gcloud auth print-identity-token --impersonate-service-account="$INVOKER_SA" --audiences="$WORKER_URL" --include-email)
curl -sS -H "Authorization: Bearer $TOKEN" "$WORKER_URL/health"
curl -sS -H "Authorization: Bearer $TOKEN" "$WORKER_URL/ready"
unset TOKEN
# 3. Remove only this release's tags; keep delivery paused until fixed.
gcloud run services update-traffic "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --remove-tags="$RELEASE_ID"
gcloud run services update-traffic "$WORKER_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --remove-tags="$RELEASE_ID"
```

Migration downgrades are never part of rollback — the expanded database
stays.

Returning to pre-Phase-20 code additionally requires stopping enqueue,
pausing queue and Scheduler, draining or expiring outstanding work, then
restoring inline stable configuration — all while delivery stays paused.
Expected: queue and Scheduler paused, no unclaimed pending rows left,
variables read back `inline`/empty, delivery still disabled:

```sh
gh variable set DELIVERY_ENABLED --body false
gh workflow disable release.yml
gcloud tasks queues pause "$CLOUD_TASKS_QUEUE" \
  --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
gcloud scheduler jobs pause "$SCHEDULER_JOB" \
  --project="$CLOUD_PROJECT" --location="$CLOUD_REGION"
# Drain or expire outstanding work: run the expire sweep with a worker token,
# or wait out the 15-minute pending lifetime, then confirm the queue is empty.
TOKEN=$(gcloud auth print-identity-token --impersonate-service-account="$INVOKER_SA" --audiences="$WORKER_URL" --include-email)
curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{}' "$WORKER_URL/internal/suggestions/expire"
unset TOKEN
gcloud tasks list --queue="$CLOUD_TASKS_QUEUE" \
  --project="$CLOUD_PROJECT" --location="$CLOUD_TASKS_LOCATION"
# Disable cloud enqueue and restore the inline stable configuration.
# In local tfvars, set api.plain_env.SUGGESTION_EXECUTION = "inline".
# Preserve the other existing runtime settings; review/apply the saved plan.
terraform -chdir=infra/terraform/sandbox plan -out=/tmp/sandbox-phase20-inline.tfplan
terraform -chdir=infra/terraform/sandbox apply /tmp/sandbox-phase20-inline.tfplan
# Delete these at their configured scope (sandbox in this bootstrap).
gh variable delete CLOUD_WORKER_SERVICE --env sandbox
gh variable delete CLOUD_TASK_INVOKER_SERVICE_ACCOUNT --env sandbox
gh variable list --env sandbox
```

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
- Delete identified poison tasks individually (full per-task command in
  [Local verification](#local-verification)); never purge the queue.
- After the rehearsal, run a local Terraform plan confirming no
  release-field drift, then update phase completion status using repository
  conventions. Keep unobserved cases pending.
