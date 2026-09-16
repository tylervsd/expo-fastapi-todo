# Phase 20: Cloud Tasks and Cloud Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move deployed suggestion generation to authenticated Cloud Tasks delivery and expire abandoned requests with Cloud Scheduler.

**Architecture:** Extend the existing suggestion reservation with immutable provider input and a permanent execution claim. Deploy a separate private FastAPI entry point from the same image; preserve the public workflow contract, existing confirmation path, and local inline mode.

**Tech Stack:** Existing FastAPI, SQLAlchemy/PostgreSQL, Alembic, Expo/React Native, pytest/Jest, Terraform and GitHub Actions; add the official `google-cloud-tasks` Python client.

**Spec:** [Phase 20 design](../specs/2026-09-15-cloud-tasks-scheduler-design.md).

**Status:** Draft for learner review. These tasks describe future implementation; none have been executed. Base: `main` at `2d20848`.

## Global Constraints

- Reuse the existing suggestion table, public status/error enums, and workflow confirmation path.
- No provider call or cloud API call runs inside a database transaction.
- At most one application-initiated provider attempt per asynchronous reservation; never reset its claim.
- Task bodies contain only `{"version":1,"suggestion_id":123}` and are at most 1024 bytes.
- Normal CI uses PostgreSQL and injected fakes; no Google credentials or paid provider calls.
- Terraform is applied locally; release CI has no Terraform or state-bucket access.
- Worker routes are absent from the public API and require Cloud Run IAM in deployment.
- No todo is created until the existing user-confirmed workflow action succeeds.

## Execution and ownership

Read the spec and the project-root `AGENTS.md` before editing. Phase 20 uses:

- **Branch:** `codex/phase-20-cloud-tasks-scheduler`
- **Worktree:** `.worktrees/phase-20-cloud-tasks-scheduler`
- **Base:** `main` at `2d20848` (Phase 19 acceptance complete).

The worktree already exists and contains this spec and plan. Reuse it for all
Phase 20 edits, tests, commits, and reviews; do not create another worktree or
implement on `main`. All file paths and commands below are relative to this
worktree root. Before execution, verify `git branch --show-current` and
`git rev-parse --show-toplevel` match the branch and directory above. Install
project dependencies and run the baseline checks there before implementation.

The project-root `AGENTS.md` is currently untracked and is not copied by Git
worktree creation; read it from `/Users/tylerv/projects/codex/fullstack/AGENTS.md`.
Preserve root `.pi/` and `AGENTS.md`; neither belongs in phase commits. Submit
completed work through a phase-branch PR targeting `main`, following prior
phases. Merge and checkpoint completion remain separate from implementation
and require the corresponding review and acceptance evidence.

Use Astra medium for architecture decisions, Luna for the mechanical tasks below,
Terra for integration/debugging, and Sol medium for significant/whole-branch
review. A Luna implementer returns scope or architecture problems to the Sol
controller. Tasks 2–4 depend on Task 1; Task 5 can proceed after the contracts
below are fixed; Task 6 integrates Tasks 3–5; Task 7 follows all of them.
Do not parallelize edits to the same file.

Use existing pytest/Jest fixtures and test infrastructure. Each behavior change
starts with a failing behavior test, then the minimal implementation. Do not add
a test framework, generic queue interface, or duplicate workflow domain logic.

## File map

| Area | Files |
| --- | --- |
| Durable reservation/claim | `apps/api/app/{suggestion_service,workflow_repository}.py`; new `apps/api/alembic/versions/2026091501_add_suggestion_execution.py` |
| Queue adapter | new `apps/api/app/suggestion_tasks.py`; `apps/api/{pyproject.toml,uv.lock}` |
| Private application | new `apps/api/app/worker.py` |
| Public route | `apps/api/app/main.py` |
| API tests | new `apps/api/tests/test_suggestion_tasks.py`, `test_suggestion_worker.py`; existing suggestion/reliability/persistence tests |
| Client | `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx` and its tests; `apps/mobile/src/todos/todoApi.ts` and tests only if required |
| Infrastructure | new `infra/terraform/sandbox/tasks.tf`; existing `variables.tf`, `outputs.tf`, `delivery.tf`, example values and `tests/safety.tftest.hcl` |
| Delivery | `scripts/release_deploy.py`, `scripts/release_smoke.py`, `.github/workflows/release.yml`, `tests/test_release.py`, `tests/repository_contract.bats` |
| Teaching | new `docs/guides/20-cloud-tasks-scheduler.md`; `README.md`, roadmap, Terraform README, Guide 19 recovery notes |

## Task 1: Persist cloud reservations and enforce one provider claim

**Interfaces:** Extend `reserve_suggestion(..., clarification=None, *, queued=False)`
without changing existing positional arguments. Add these interfaces in
`suggestion_service.py`; `session` always belongs to the caller:

```python
@dataclass(frozen=True)
class ClaimedSuggestion:
    suggestion_id: int
    owner_id: int
    reservation: SuggestionReservation
    provider_started_at: datetime

# Returns None for work that must not execute; raises SuggestionInProgress for
# a still-live claim. Every returned claim has already committed.
def claim_suggestion(session: Session, suggestion_id: int) -> ClaimedSuggestion | None: ...

def finish_claimed_suggestion(
    session: Session, claim: ClaimedSuggestion, *,
    titles: tuple[str, ...] | None, error_code: SuggestionErrorCode | None,
) -> SuggestionSnapshot | None: ...

def expire_suggestions(session: Session) -> int: ...
```

The declarations above are interface signatures, not instructions to leave stub
bodies. Implement their exact transaction semantics from the spec.

- [x] **1. Add failing PostgreSQL cases** to new `test_suggestion_worker.py`,
  reusing `setup_owner` and `make_collecting` patterns from
  `test_workflow_suggestions.py`. Create a cloud reservation, resolve its row ID
  with the existing unique owner/workflow/request key, and check:

```python
with session_factory() as session:
    claim = claim_suggestion(session, suggestion_id)
assert claim is not None
with session_factory() as session:
    with pytest.raises(SuggestionInProgress):
        claim_suggestion(session, suggestion_id)
with session_factory() as session:
    saved = finish_claimed_suggestion(
        session, claim, titles=("Book venue", "Invite guests"), error_code=None,
    )
assert saved.status is SuggestionStatus.READY
with session_factory() as session:
    assert claim_suggestion(session, suggestion_id) is None
```

  Add a real two-session race using a barrier and separate connections; exactly
  one returns a claim. Other cases: changed fingerprint, cancelled workflow,
  new request superseding old, database expiry boundary, and stale finish after
  expiry. Assert no `TodoRow` is inserted by any execution operation.

- [x] **2. Run the new tests and record the expected missing-interface failure.**

```sh
uv run --directory apps/api pytest tests/test_suggestion_worker.py -q
```

- [x] **3. Add the migration and mapped columns.** Use revision `2026091501`
  after `2026091001`; nullable PostgreSQL timezone-aware timestamps, text goal,
  JSONB clarification. Enforce all-legacy-null versus coherent queued fields;
  require `expires_at > queued_at`, claim time at/after queued time, and a
  nonempty bounded goal for cloud rows. Clarification must be null or an object;
  perform exact field/value validation with `normalize_clarification` on writes
  and worker reads. Add the pending-cloud partial expiry index. Preserve existing
  status/error checks. Test upgrade with preexisting ready and pending rows;
  they remain readable and cannot be claimed as cloud work.

- [x] **4. Implement reservation and claim under existing lock ordering.**
  Persist goal/clarification snapshots and database-clock deadlines when
  `queued=True`; same-ID pending cloud replay returns a snapshot. Do not extend
  deadlines or change a snapshot on replay. The worker performs a read to discover
  ownership, closes that read transaction, then locks workflow and row. Recheck
  current request, revision, state and timestamps before committing the claim.
  Use the spec's `15 minutes` reservation and `2 minutes` claim expiry constants.

- [x] **5. Implement guarded finalization and bounded expiry.** Share the existing
  title validation/current-workflow logic instead of weakening `finish_suggestion`.
  Keep legacy `finish_suggestion` behavior for inline records. For cloud rows,
  finalization requires the exact claim marker and a still-valid pending row.
  Expiry selects at most 100 candidates, locks workflows with `SKIP LOCKED`, then
  locks/rechecks rows, using a 5-second local statement timeout. Count actual
  transitions only. Repeat cleanup tests with 101 expired rows, live claims,
  terminal/legacy rows, locked rows, and concurrent finalization; no sleeping.
  Add a `ponytail:` comment explaining that claims are never reclaimed and users
  explicitly retry uncertain work.

- [x] **6. Run focused tests and commit.**

```sh
uv run --directory apps/api pytest tests/test_suggestion_worker.py tests/test_workflow_suggestions.py tests/test_workflow_reliability.py -q
uv run --directory apps/api ruff check .
git diff --check
git add apps/api/app/suggestion_service.py apps/api/app/workflow_repository.py apps/api/alembic/versions/2026091501_add_suggestion_execution.py apps/api/tests/test_suggestion_worker.py apps/api/tests/test_workflow_suggestions.py
git commit -m "feat: persist and fence asynchronous suggestion attempts"
```

## Task 2: Enqueue from the existing authenticated suggestion route

**Interfaces:** `suggestion_tasks.enqueue_suggestion(suggestion_id: int,
fingerprint: str) -> None`; sanitized `EnqueueUnavailable` exception. Add a
callable injection to `create_app` for this concrete function, matching the
existing provider test-seam style. Cloud configuration is parsed once at startup.
Use an internal owner-scoped lookup to obtain row ID/fingerprint; never expose
those fields in the public suggestion schema.

- [x] **1. Add failing adapter and route tests.** Fake `create_task` and assert
  exact project/queue, stable task name, 1024-byte body limit, fixed URL, canonical
  audience, caller service account, 60-second dispatch deadline, `retry=None`,
  and 5-second timeout. Two calls for one row produce identical task names.
  Simulate create success with lost response: first POST is `503`, same-ID replay
  meets `AlreadyExists`, and remains one row with no public-route provider call.
  Verify other exceptions are sanitized `503`, cross-owner POST is denied, and
  conflicting fingerprints never enqueue.

```sh
uv run --directory apps/api pytest tests/test_suggestion_tasks.py tests/test_workflow_suggestions.py -q
```

- [x] **2. Add the client dependency and minimal adapter.** Resolve an official
  `google-cloud-tasks` release compatible with Python 3.14, pin it in
  `pyproject.toml`, and update `uv.lock` through uv. Use its generated request
  types; the essential target content is:

```python
body = json.dumps({"version": 1, "suggestion_id": suggestion_id}).encode()
name = "suggest-v1-" + hashlib.sha256(
    f"{suggestion_id}:{fingerprint}".encode()
).hexdigest()
http_request = {
    "http_method": tasks_v2.HttpMethod.POST,
    "url": f"{worker_url}/internal/suggestions",
    "headers": {"Content-Type": "application/json"},
    "body": body,
    "oidc_token": {
        "service_account_email": invoker_email,
        "audience": worker_url,
    },
}
```

  Validate configured HTTPS canonical `run.app` origin and nonempty queue/project
  values; no request-supplied routing. Use ADC, not key files. Create the task with
  its full resource name and protobuf duration of 60 seconds. Only catch
  `AlreadyExists` as successful deduplication. Never log the credential or body.

- [x] **3. Branch the public route at dispatch, preserving inline mode.**
  Cloud mode calls `reserve_suggestion(..., queued=True)`, handles replay, ends
  database work, then runs enqueue in the existing framework threadpool helper.
  Reconcile current saved state and return the spec's `202`/`200`/error results.
  Unknown execution modes or incomplete cloud config fail startup. Inline mode
  preserves existing `201`, provider errors, and injected provider fixtures.
  Reuse enums and the current response mapper. `enqueue_unavailable` is a
  transport error code, not a new persisted provider error enum.

- [x] **4. Verify async mode through the actual route.** Include new and replayed
  pending, ready replay, failed replay, lost response, unknown mode, and a fake
  provider that fails the test if called by the cloud-mode public route. Prove
  fake enqueue observes the already committed row from a second DB connection.

- [x] **5. Run the commands above plus Ruff and commit the adapter, dependency,
  route and tests** with message `feat: enqueue durable suggestion requests`.

## Task 3: Add the private worker and expiry endpoint

**Interfaces:** `worker.create_worker_app(*, session_factory=None,
suggestion_callable=None) -> FastAPI`, exported as `worker.app`. Shared provider
call signature remains `(goal, config, clarification=...)`. Do not import the
public application instance or mount its router.

- [x] **1. Extend failing worker endpoint tests.** Assert strict version 1 integer
  IDs (reject booleans), extra-field rejection, 1025-byte rejection, empty-object
  cleanup payload, and absence of `/todos`, `/agent`, and public suggestion routes.
  Fake provider counts must remain one for duplicate and concurrent deliveries.
  Test no provider call on terminal/stale/legacy/expired/missing rows.

- [x] **2. Implement the worker factory and bounded handler.** Use existing engine
  and session lifecycle patterns; `/health` returns the existing health shape and
  `/ready` runs only a bounded `SELECT 1`. Enforce body limits while reading chunks,
  not merely a potentially absent Content-Length. Set deadlines for DB readiness.
  The handler claims, awaits the existing provider, and finalizes outside provider
  time. Use existing exception-to-error-code mappings; share a small provider
  execution helper only if extraction eliminates the public route's duplicate
  mapping. No unrelated `main.py` refactor.

```text
No usable claim -> 204
Live existing claim -> 503
Provider returns validated result -> persist ready -> 204
Known provider failure -> persist failed -> 204
Database unavailable/unexpected exception -> sanitized 503
Malformed payload -> 400/422; oversized -> 413
```

- [x] **3. Add expiry route and failure tests.** `POST .../expire` calls Task 1's
  bounded sweep and returns `{"expired": count}`. Lost success acknowledgement
  followed by repeat delivery must return `204` with the same saved titles.
  Inject failure after provider success but before commit; retry must not call
  the provider, and expiry eventually records timeout. Reject late result writes.
  Assert logs omit goal, clarification, raw exception text, tokens and proposals.

- [x] **4. Verify the production entry point without cloud credentials.**

```sh
uv run --directory apps/api pytest tests/test_suggestion_worker.py tests/test_suggestion_tasks.py tests/test_workflow_suggestions.py -q
uv run --directory apps/api ruff check .
docker build --tag phase20-worker-check apps/api
docker run --rm --entrypoint python phase20-worker-check -c 'import app.worker; from google.cloud import tasks_v2'
```

  A missing Docker daemon is an unperformed image check, not a pass. Do not use a
  Cloud SQL database for local verification.

- [x] **5. Commit** worker and focused tests as
  `feat: execute and expire suggestions in a private worker`.

## Task 4: Reconcile asynchronous suggestions on web and iOS

**Files:** Client files from the file map. Read `apps/mobile/AGENTS.md` and its
versioned Expo documentation before coding. No new dependency.

**Interfaces:** Existing `WorkflowSuggestion` schema and `getWorkflowSuggestion`
remain unchanged; successful `202` carries that schema. Reuse
`fetchSuggestionRecord`, `settleAgentSuggestionWaiter`, session epoch and fetch
sequence guards. Keep request identity in existing pending-write storage.

- [x] **1. Add failing component tests with fake timers.** A `202 pending` response
  causes one GET after 3 seconds and then a ready result resolves the manual/agent
  flow. Assert one GET in flight, unchanged pending does not reset the 2-minute
  budget, and stop conditions work (ready, failed, logout, background, unmount,
  new workflow). Foreground triggers one GET and a new bounded foreground session.
  Simulate pending-to-failed/superseded agent result and verify its submission
  controls unlock. Preserve typed drafts under late ready results.

- [x] **2. Implement one local effect using a cancellable timeout loop.** Each tick
  awaits the existing guarded fetch before scheduling another; store elapsed
  budget independently of the changing suggestion object. Subscribe to React
  Native `AppState` for background/foreground; retain web support through the
  existing cross-platform runtime. Cleanup clears timer and invalidates in-flight
  responses via the existing guards. Do not duplicate suggestion fetching logic.

```text
pending + active + current workflow -> begin bounded refresh
await guarded GET -> terminal/error/stale? stop : schedule next tick
elapsed >= 120 seconds -> stop; show Check status
```

- [x] **3. Preserve explicit retry semantics.** An uncertain enqueue retains the
  stored request and retries its ID only on user action. “Check status” must not
  enqueue. Keep it available while the agent waits, even after polling stops.
  Terminal failed results allow an explicit fresh request with the billing warning.
  Update live-region copy for queued work; preserve focus and edited-draft guards.

- [x] **4. Verify and commit.**

```sh
pnpm --dir apps/mobile exec jest src/todoWorkflows/TodoWorkflowScreen.test.tsx src/todos/todoApi.test.ts --runInBand
pnpm lint:mobile
pnpm typecheck
git diff --check
```

  Commit the client change as `feat: recover queued suggestions across app sessions`.

## Task 5: Provision queue, private worker, identities and schedule

**Interfaces:** Add nullable `async_suggestions` with fields `worker_name`,
`worker_image`, `queue_name`, `scheduler_name`, `invoker_account_id`,
`worker_account_id`, `scheduler_paused` (default true), and explicit worker
`database_secret_key/version`, `provider_secret_key/version`, `provider_model`.
Reuse existing region and SQL connection name. Validate immutable image digest,
positive numeric secret versions, and references to existing secret metadata.
Output `suggestion_worker_uri`, `suggestion_queue_name`,
`suggestion_invoker_email`, each null when disabled. API cloud-mode configuration
uses those outputs through the existing local values process.

- [x] **1. Add failing Terraform mock tests** for zero resources when disabled,
  mandatory invocation IAM, resource-specific grants, numeric secret versions,
  expiry schedule and the following exact queue settings:

```hcl
rate_limits {
  max_dispatches_per_second = 1
  max_concurrent_dispatches = 2
}
retry_config {
  max_attempts       = 5
  max_retry_duration = "0s"
  min_backoff       = "10s"
  max_backoff       = "60s"
  max_doublings     = 3
}
stackdriver_logging_config {
  sampling_ratio = 1.0
}
```

- [x] **2. Create `tasks.tf` using existing provider/resource patterns.** Worker:
  min 0/max 1 instances, concurrency 2, timeout `60s`, 1 CPU/512 MiB, database
  connection and two numeric secret references, explicit command
  `sh -c 'exec uvicorn app.worker:app --host 0.0.0.0 --port "${PORT:-8080}"'`.
  Escape Terraform's `${` interpolation as `$${` in HCL. Require invocation IAM;
  no unauthenticated principal. Use the existing image and lifecycle ownership
  pattern without copying public invoker configuration or the public route command.

- [x] **3. Add least-privilege grants and Scheduler.** Enqueuer on this queue for
  API identity; serviceAccountUser on the invoker identity; worker Cloud SQL
  and per-secret access; invoker `run.invoker` on worker only. Retain required
  Google service-agent roles. Scheduler calls `/internal/suggestions/expire` with
  `{}`, OIDC invoker identity, root URI audience, UTC five-minute schedule,
  `30s` deadline, zero retries, initially paused. Teach that both Tasks and
  Scheduler intentionally share invocation authority; they are not route-isolated.

- [x] **4. Extend CI deployment grants** with worker-scoped `run.developer`, act-as
  on worker runtime identity, and Token Creator on the invocation account only
  for ID-token smoke. CI gets no queue administration, worker secret payload,
  infrastructure apply, or state-bucket access. Keep GitHub's immutable subject
  trust condition unchanged. Preserve existing API runtime provider credentials
  for inline rollback until activation acceptance; do not remove unrelated grants.

- [x] **5. Document real bootstrap inputs in example values and verify offline.**

```sh
terraform -chdir=infra/terraform/sandbox fmt -check
terraform -chdir=infra/terraform/sandbox init -backend=false -lockfile=readonly
terraform -chdir=infra/terraform/sandbox validate
terraform -chdir=infra/terraform/sandbox test
```

  Inspect provider schema/docs for the repository's locked provider before using
  a new field. Never fabricate a successful plan/apply or a live resource name.
  Commit as `infra: define authenticated suggestion delivery and cleanup`.

## Task 6: Extend the existing release to the worker

**Interfaces:** Optional environment variable `CLOUD_WORKER_SERVICE`; absence
preserves Phase 19/first bootstrap behavior. When present,
`CLOUD_TASK_INVOKER_SERVICE_ACCOUNT` is required. Extend existing smoke with
`smoke_worker(url: str, audience: str, invoker: str) -> None` and bounded ID-token
acquisition through gcloud impersonation. Private smoke checks `/health` and
`/ready`; preserve the public smoke function and its CORS/auth checks.

- [x] **1. Add failing release tests** to the existing unittest file: same digest
  on migration/API/worker; worker promotion precedes API deployment; no API
  promotion after worker smoke failure; rollback independently restores both
  captured revisions, even if one restore fails. Test failure after a command
  succeeds remotely but raises locally, tag cleanup, early summaries and no-worker
  compatibility. Never infer no mutation from a nonzero CLI response.

```sh
pnpm test:release
```

- [x] **2. Add authenticated private smoke.** Obtain an ID token for the canonical
  worker audience using the permitted invocation account, hold it in memory,
  include its email claim (`gcloud auth print-identity-token --include-email`),
  and supply Authorization only to verified worker URLs. Bound token/subprocess
  and HTTP timeouts; mask token in Actions before any possible output. Never
  include it in logs, summary, exception messages or command arguments. Do not
  change the private service to public for testing. Verify root audience when
  calling candidate tag URLs.

- [x] **3. Extend rollout directly.** Reuse existing gcloud/traffic/digest helpers.
  Capture both previous revisions before migration; preserve mutation-attempt
  flags separately. Sequence: migration, worker candidate/readiness, worker
  promotion/readiness, API candidate/smoke, API promotion/smoke. Restore attempted
  promotions on any subsequent failure, API then worker, collecting both errors.
  Record observed traffic independently; clean both release tags in `finally`.
  Do not add a generic deployment engine. Leave the queue running during normal
  compatible releases; explain that completed provider work cannot be rolled back.

- [x] **4. Wire workflow environment and contracts.** Keep the one tested build,
  registry digest, approval boundary, deployment lock, advisory image scan, and
  validation gates. Test the worker entrypoint import in the built container.
  Omit worker mode until bootstrap resources exist; configured-but-missing worker
  fails before mutations. Update `repository_contract.bats` only for new invariants.

- [x] **5. Verify and commit.**

```sh
pnpm test:release
bats tests/repository_contract.bats
uv run --directory apps/api ruff check ../../scripts/release_deploy.py ../../scripts/release_smoke.py ../../tests/test_release.py
actionlint .github/workflows/*.yml
git diff --check
```

  Commit as `feat: release and restore the private suggestion worker`.

## Task 7: Teach, review and record live acceptance separately

**Files:** Documentation in the file map; acceptance records remain pending until
observed. No cloud provisioning or paid calls are implied by finishing code tasks.

- [x] **1. Write Guide 20** with headings `Prerequisites`, `Transaction gap`,
  `Provider attempt policy`, `Bootstrap`, `Local verification`, `Failure drills`,
  `Pause and recovery`, `Acceptance record`, and `Cleanup`. (Done: `docs/guides/20-cloud-tasks-scheduler.md`.) Show DB reservation,
  task delivery, claim and result timeline; explain every limit from the spec.
  Include how to inspect queue configuration, attempts, logs and metrics in native
  Google tools, how to identify a poison task, and how to pause queue/Scheduler.
  Never describe rate limits or budget alerts as a hard monetary cap.

- [x] **2. Write a concrete staged bootstrap and recovery runbook.** (Done: Guide 20
  `Bootstrap` and `Pause and recovery` sections.) First deploy
  the compatible image with inline mode and worker variable absent. Pause releases
  using Guide 19, provision reviewed Terraform with that digest, verify IAM,
  then set cloud-mode API configuration and worker release variables. Resume
  Scheduler only after testing expiry. A return to pre-phase code requires
  stopping enqueue, pausing queue/Scheduler, draining/expiring work and restoring
  inline stable configuration; it is not ordinary traffic-only rollback.
  Pause doesn't cancel a running handler; inspect claims before recovery.

- [x] **3. Add live acceptance rows** for every spec acceptance case with columns
  result, evidence/run URL, date, and limitation. (Done: Guide 20 `Acceptance record`;
  all rows pending — no rehearsal observed.) Supply rehearsal instructions:
  submit one disposable request, record its DB ID/task name, deliver twice with
  the same body, and count provider attempts; simulate a lost response through a
  local test proxy/wrapper rather than production fault flags. For retry exhaustion
  use a disposable authenticated task target that fails before claim, then verify
  cleanup expiry. For post-provider crash inject failure in the local worker test
  harness; separately identify which cloud failure was actually observed. Never
  label local simulation as deployed proof. Rehearse queue pause/backlog and
  cleanup replay with no unbounded paid generation.

- [x] **4. Update README/roadmap and Guide 19 links.** (Done: README Phase 20
  repository-ready paragraph, roadmap opening fixed, Guide 19 recovery note, Terraform
  README Guide 20 pointer.) Link spec, plan and guide;
  distinguish repository-ready, live-pending and learner-confirmed completion.
  Fix the roadmap opening's stale “Phase 17 is next” summary using existing
  Guides 17–19 evidence without upgrading earlier partial acceptance records.

- [x] **5. Run integrated verification once.** (Done 2026-09-16: `pnpm quality` passed
  end-to-end; `pnpm test:release` 57 passed; `pnpm test:pages` passed;
  `pnpm typecheck:e2e` clean; `pnpm test:e2e:web` 4 passed; `git diff --check` clean.
  `terraform validate/test` and `actionlint` not run — binaries unavailable, recorded
  as gaps.) Start the repository's local test
  database with its documented environment, then:

```sh
pnpm quality
pnpm test:release
pnpm test:pages
pnpm typecheck:e2e
pnpm test:e2e:web
terraform -chdir=infra/terraform/sandbox validate
terraform -chdir=infra/terraform/sandbox test
actionlint .github/workflows/*.yml
git diff --check
```

  Existing web E2E remains inline/deterministic; component and PostgreSQL tests
  exercise async mode. Real queued web/iOS acceptance is a separate live row.
  Add any changed Python test/script checks to existing CI rather than a parallel
  workflow. Record unavailable tools/services as gaps.

- [ ] **6. Request whole-branch Sol medium review.** Review exact spec coverage,
  permanent claims, lock ordering, transaction gap, no automatic paid retries,
  worker IAM, two-service failure handling and frontend agent recovery. Fix
  findings and rerun affected checks. Commit guide/status changes with
  `docs: teach Cloud Tasks delivery and scheduled expiry`.

- [ ] **7. Conduct the learner-authorized live rehearsal.** Record actual task,
  IAM, expiry, web/iOS, release and rollback observations; finish with a local
  Terraform plan confirming no release-field drift. Keep unobserved cases pending.
  Only then update phase completion/checkpoint status using repository conventions.

## Coverage map

| Spec requirement | Tasks |
| --- | --- |
| Durable snapshots, permanent claims, no duplicate result/todos | 1, 3 |
| Same-ID enqueue recovery and existing API contracts | 1, 2 |
| Private routes, OIDC, bounded queue and authenticated schedule | 2, 3, 5 |
| Cleanup replay, claim timeout, poison tasks and exhaustion | 1, 3, 5, 7 |
| Web/iOS pending recovery and agent waiter settlement | 4, 7 |
| Same-image deployment, bootstrap, mixed versions and rollback | 5, 6, 7 |
| Privacy, cost limits, manual recovery and honest evidence | 2, 3, 7 |

## Reference material

- [Cloud Tasks HTTP targets and Python examples](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks)
- [Cloud Run private task invocation](https://docs.cloud.google.com/run/docs/triggering/using-tasks)
- [Cloud Run service-to-service authentication](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)
- [Cloud Scheduler authenticated HTTP targets](https://docs.cloud.google.com/scheduler/docs/http-target-auth)
- [Cloud Tasks queue retry configuration](https://docs.cloud.google.com/tasks/docs/reference/rest/v2/projects.locations.queues#RetryConfig)
