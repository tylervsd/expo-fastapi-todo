# Phase 19: Continuous Delivery, Revisions, and Rollback

**Status:** Proposed for learner review

**Date:** 2026-09-14

**Base:** `main` at `d05ebc0` (Phase 18)

**Branch:** `codex/phase-19-continuous-delivery`

**Worktree:** `.worktrees/phase-19-continuous-delivery`

## Outcome

Deliver validated `main` commits to the existing Google Cloud sandbox through
one application release workflow. After the existing gates and one environment
approval, the workflow builds, tests, scans, and pushes the API image once, runs
compatible migrations, tests a zero-traffic revision, and promotes it.

A failed candidate receives no production traffic. A failed post-promotion smoke
test restores the previously serving revision. Rollback changes traffic only;
it never rebuilds an image or downgrades the database.

This phase targets a learning project and a small startup: one CI deploy
identity, native Cloud Run rollout controls, and a short release summary.
Infrastructure changes retain the existing reviewed local Terraform process.
The Phase 17 Cloudflare Pages Git integration remains unchanged.

Newer pending releases may supersede older ones. Each release that starts
deployment uses its exact validated commit; deploying every intermediate commit
is not a requirement.

## Success criteria

Phase 19 is complete when:

1. Pull requests retain existing quality, security, and web end-to-end checks;
   releases validate their exact commit without duplicate `main` triggers.
2. One narrowly scoped CI deploy identity authenticates through short-lived
   Workload Identity Federation credentials, without service-account JSON keys
   or Terraform state access.
3. After environment approval, one job builds, tests, scans, and pushes once.
   The migration job and API revision use the same immutable registry digest.
4. Migrations finish before candidate deployment and remain compatible with the
   previous application revision.
5. The candidate receives zero production traffic until its tagged URL passes
   health, CORS, and database-connectivity smoke tests.
6. Promotion sends 100% traffic to the candidate and repeats the stable-URL
   smoke tests. Failure restores the captured previous revision and verifies it.
7. A documented manual rollback to the recorded previous revision is rehearsed
   without rebuilding, running migrations, or applying Terraform.
8. A GitHub job summary records commit, digest, migration execution, previous
   and candidate revisions, smoke results, and final traffic state.
9. Deployment mutations are serialized, and reruns rediscover current traffic.
10. A local Terraform plan after release and rollback rehearsal confirms that
    release-owned fields cause no drift.

## Existing system boundary

Phase 19 extends the repository as it exists after Phase 18:

- Terraform manages the imported sandbox foundation, Artifact Registry,
  Secret Manager metadata, Cloud SQL, Cloud Run service, Cloud Run migration
  job, and stable runtime configuration.
- The Google Cloud project, Terraform state bucket, secret payloads, and external
  integrations remain outside Terraform.
- The API already has a Linux `amd64`, non-root container and a `/health`
  endpoint.
- `POST /auth/login` touches the database before returning `401` for invalid
  credentials, so it provides a data-free database connectivity probe.
- Cloudflare Pages already deploys the web export from Git integration at
  `https://expo-fastapi-todo.pages.dev`.
- Quality, security, and web end-to-end checks already exist as independent
  GitHub Actions workflows.
- Database changes use Alembic through the existing Cloud Run migration job.

The Phase 18 live label-drift follow-up was confirmed closed by the learner on
2026-09-15. This activation prerequisite is satisfied.

## Chosen architecture

Use GitHub Actions plus native Google Cloud capabilities:

- GitHub reusable workflows provide the existing gates.
- GitHub OIDC and Google Workload Identity Federation provide short-lived
  credentials.
- Terraform owns stable infrastructure and identity configuration, applied
  locally when infrastructure changes.
- `gcloud` owns release-specific Cloud Run mutations.
- GitHub Environments provide the single human approval boundary.
- Cloud Run revisions, tags, and traffic provide candidate testing and rollback.

Application CI has no Terraform plan or apply stage. Infrastructure prerequisites
are reviewed and applied before deploying application code that requires them.

### Deferred complexity

**Terraform in every application release.** Keep the existing reviewed local
plan/apply process. Add a separate infrastructure workflow when infrastructure
changes become frequent enough to justify it.

**Image artifact handoffs and checksum bookkeeping.** Approval precedes the
build, so one job can test, scan, and push the same local image. No Docker archive
needs to cross jobs.

**Custom rollback history validation.** Start with a rehearsed runbook using the
recorded previous revision. A GitHub API lookup of historical workflow success
is not required for recovery.

**Terraform owns every release field.** Rejected because every application
release would require Terraform to model transient revision names, candidate
tags, and traffic transitions. That makes rollback and zero-traffic smoke tests
needlessly indirect.

**Google Cloud Deploy.** Rejected because one sandbox target does not justify a
second release orchestrator. Reconsider it only when the project gains multiple
promotion environments or requires Cloud Deploy-specific governance.

## Ownership model

| Concern | Owner | Phase 19 rule |
| --- | --- | --- |
| Google Cloud project and Terraform state bucket | External bootstrap | Referenced, never created or destroyed by this phase |
| Workload Identity pool/provider | Terraform | Trusts only the numeric repository/owner identity and approved workflow context |
| GitHub deploy service account | Terraform | One CI identity with release permissions only; no state-bucket or infrastructure apply grants |
| Artifact Registry repository | Terraform | Stable repository configuration only |
| Image build, tag, push, and digest | Release workflow | One tested build per release attempt; deploy by digest |
| Cloud Run service configuration | Terraform | Runtime identity, scaling, networking, secrets, environment, and other stable settings |
| API image, revision name, candidate tag, and traffic | Release workflow | Exact, narrowly ignored Terraform attributes |
| Migration job configuration | Terraform | Stable job configuration, runtime identity, networking, secrets, and resources |
| Migration job image and execution | Release workflow | Same release digest as the API; execute once before candidate deployment |
| Cloud Run runtime and migration identities | Terraform | Remain distinct from each other and from the CI deploy identity |
| Secret payloads | External bootstrap | Never read into Terraform state, plans, logs, or artifacts |
| Cloudflare Pages deployment | Existing Git integration | Unchanged and outside the Google release transaction |

Each attribute has one ownership policy. The rollback runbook follows the same
traffic ownership rules as the release workflow and runs only while delivery
is paused and no release is active.

## Workflow topology

### Existing checks become callable gates

The quality, security, and web end-to-end workflows keep their pull-request
behavior and become callable with `workflow_call`. Their direct `push: main`
triggers are removed so a release commit is not validated twice. Existing
scheduled and manual triggers remain where they already provide value.

The iOS end-to-end workflow remains manual and outside the sandbox deployment
gate because it depends on a local simulator and is not currently a reliable
hosted CI signal.

### Release workflow

A new `release.yml` runs on pushes to `main` and `workflow_dispatch` from `main`
for activation rehearsal or retry. Manual rollback uses the learner runbook.

```text
quality + security + web E2E
             |
             v
     sandbox environment approval
             |
             v
 one deploy job: build -> test -> scan -> push digest
             |
             v
 migrate -> zero-traffic candidate -> candidate smoke
             |
             v
       100% traffic -> stable smoke
             |
             v
        GitHub job summary
```

The mutation job uses concurrency group `sandbox-release` with
`cancel-in-progress: false`. An active deployment finishes or fails before
another starts. GitHub's default pending-run replacement is acceptable: newer
pending releases may supersede older ones. This is not an every-commit queue.
Validation jobs remain independent of the deployment lock.

The deploy job checks out the exact commit validated by its gates, including on
manual runs and reruns; it does not resolve a newer branch head after approval.

### Activation guard

Repository variable `DELIVERY_ENABLED` defaults to absent or `false`. While it
is not exactly `true`, `main` still runs all validation jobs and reports that
delivery is not activated, but no job requests Google credentials or mutates
Google Cloud.

The guard controls activation; it does not cancel jobs already running or
waiting for approval. For manual recovery or infrastructure changes, follow the
manual rollback section's pause procedure: disable the workflow, let active
deployment finish, and clear pending work. Branch and environment protections
remain in force when delivery resumes.

## Identity and authorization

Terraform creates one GitHub Workload Identity provider and one CI deploy
service account. The deploy identity may push to the existing API repository,
inspect the sandbox service, update and execute its migration job, deploy API
revisions, manage candidate tags, and move traffic. It may act as the existing
runtime and migration identities only where required.

It receives no Terraform state-bucket, infrastructure administration, Owner,
Editor, service-account-key, or project-wide secret-access grants. Runtime and
migration identities retain their separate existing permissions.

Prefer narrow predefined Google roles scoped to the required resources. Verify
permissions during bootstrap rehearsal; use a custom role only if predefined
roles materially exceed the required scope.

The provider condition requires the expected numeric repository and owner IDs,
`refs/heads/main`, and the exact release workflow reference. The service-account
binding accepts only the environment subject
`repo:<owner>@<owner_id>/<repository>@<repository_id>:environment:sandbox`. Together these restrictions
limit credentials to the expected repository, branch, workflow, and protected
environment. Repository and owner names alone are not trust anchors.

Workflow permissions default to read-only. Only the approved deploy job requests
`id-token: write`. Actions remain pinned to full commit SHAs.

The learner applies identity resources and grants locally with Application
Default Credentials. No downloaded service-account key is created.

## Terraform and release ownership boundary

Terraform continues to express the desired Cloud Run service and job, but ignores
only the attributes the release workflow owns:

- API service container image;
- API service revision name;
- API service traffic block; and
- migration job container image.

The expected provider paths are:

```hcl
# google_cloud_run_v2_service.api
template[0].containers[0].image
template[0].revision
traffic

# google_cloud_run_v2_job.migrate
template[0].template[0].containers[0].image
```

Implementation tests must prove those paths against the pinned provider schema.
No whole-resource ignore rule and no speculative metadata ignore rule is allowed.

Infrastructure plans and applies remain local and reviewed, following Phase 18.
Apply prerequisites before the application release; use the documented pause
procedure before changing Cloud Run infrastructure. Resume delivery
after verifying the infrastructure change. Application rollback does not undo
infrastructure changes, so configuration changes must preserve the previous
revision's ability to run.

Verify the ownership boundary with a local Terraform plan after the release and
rollback rehearsal. This is an acceptance check, not a per-release CI stage.
No saved Terraform plans are uploaded by the release workflow.

## Image build and release summary

After environment approval, the deploy job:

1. builds one API image for `linux/amd64` from the validated commit;
2. labels the image with the source commit;
3. runs the existing container and health checks and scans that local image;
4. pushes that same image under a unique, never-reused release tag; and
5. resolves and records its immutable Artifact Registry digest, checking it
   against the digest reported by the push.

The migration job and API deployment both use `repository@sha256:...`. There is
no rebuild between testing and pushing, no Docker archive handoff, and no
separate archive checksum. Tags and revision suffixes include the run ID, run
attempt, and short commit SHA so reruns are distinguishable.

Use the GitHub job summary for commit, registry digest, migration execution,
previous and candidate revisions, smoke results, and observed final traffic.
Write available results on failure too, marking unavailable values explicitly.
No custom release-record format, parser, or external attestation is required.
Logs and summaries must not contain credentials or secret payloads.

## Normal release sequence

1. Validate the exact release commit through the reusable gates.
2. Confirm delivery is enabled and wait for `sandbox` environment approval.
3. In the serialized deploy job, authenticate and read the currently serving
   revision. Require exactly one named revision serving 100% traffic and record
   it for rollback.
4. Build, test, scan, push, and resolve the image digest in that same job.
5. Update the existing migration job to that digest, execute it once, wait for
   success, and record the execution name.
6. Deploy a uniquely named, tagged API candidate with that digest and zero
   production traffic.
7. Smoke-test the candidate's tagged URL.
8. Move 100% traffic to the candidate, wait for the traffic update to complete,
   and repeat the smoke tests through the stable service URL.
9. If stable smoke fails, restore the captured previous revision, wait for the
   traffic update, and verify the stable URL again.
10. Remove the temporary candidate tag where possible and write the job summary.

An ambiguous initial traffic split stops deployment. The previous revision is
captured after approval, not before a potentially long approval wait.

## Migration policy

Every Phase 19 migration must be expand-first and compatible with both the old
and new application revisions during the release window. Examples include adding
nullable columns or new tables before code starts depending on them.

The workflow never performs an automatic Alembic downgrade. If migration fails,
the candidate is not deployed. If application promotion is rolled back, the
expanded database remains in place and the previous revision must continue to
work with it.

Destructive contract migrations require a later, explicit phase after old code
is no longer eligible for rollback.

## Smoke-test contract

Candidate and stable smoke tests use repository-owned scripts and exact
assertions:

1. `GET /health` returns `200` with `{"status":"ok"}`.
2. A CORS preflight from `https://expo-fastapi-todo.pages.dev` returns the
   expected allow-origin behavior.
3. An invalid `POST /auth/login` returns exactly `401`, proving that the request
   reached the database without creating or depending on test data. A database
   outage already maps this path to `503`, so it cannot falsely pass.

The script accepts an explicit base URL and contains no environment discovery or
deployment mutation. Use bounded polling for startup and traffic propagation,
with a timeout and clear failure output. The same checks run against the tagged candidate URL and
the stable service URL.

## Failure handling

- Validation, approval, build, scan, push, or migration failure
  stops the release before a candidate receives production traffic.
- Candidate smoke failure leaves existing traffic unchanged, removes the
  temporary tag where possible, and retains the zero-traffic revision for
  investigation.
- Stable smoke failure immediately assigns 100% traffic to the captured previous
  revision and verifies the stable URL again.
- An unsuccessful automatic traffic restore is a hard failure requiring learner
  action; the workflow reports both desired and observed traffic state.
- Mutation steps are not automatically retried. A workflow rerun is a new,
  serialized release attempt that validates the commit, obtains new approval,
  and rediscovers current traffic. Alembic applies only pending migrations.

## Manual rollback

Provide a short learner runbook using native Cloud Run traffic controls and
local operator credentials. A workflow rollback mode and GitHub API validation
of historical runs are deferred.

The operator:

1. Sets `DELIVERY_ENABLED=false`, disables the release workflow to prevent new
   queued work, and waits for active deployment to finish. Clears pending
   deployments so they cannot immediately undo recovery.
2. Selects the exact previous revision from the release summary, verifies it
   belongs to the expected sandbox service, and checks migration compatibility.
3. Uses a temporary tag to run the smoke contract against that revision before
   cutover. A failed precheck stops the procedure for investigation.
4. Assigns 100% traffic to that revision, waits for completion, runs stable-URL
   smoke tests, and removes the temporary tag where possible.
5. Records the result and keeps delivery paused until the failed release has
   been addressed. Re-enables the workflow and delivery deliberately afterward.

Rollback never builds or pushes images, applies Terraform, runs migrations, or
downgrades the database. It restores the recorded previous revision; arbitrary
historical revision selection is outside this phase. A failed rollback smoke
requires operator investigation and must not be reported as recovered.

Manual recovery uses existing authorized operator access; it does not impersonate
GitHub or weaken the CI environment approval boundary.

## Activation and required learner interaction

Repository changes can merge with delivery disabled. Live activation requires
four deliberate learner actions:

1. Phase 18 live drift follow-up: satisfied by learner confirmation on 2026-09-15.
2. Run the documented local Terraform bootstrap with Application Default
   Credentials to create Workload Identity Federation, the CI deploy identity,
   its IAM bindings, and the narrow release ownership exclusions.
3. Configure and protect the GitHub `sandbox` Environment, set the documented
   non-secret repository/environment variables, and add required reviewers.
4. Set `DELIVERY_ENABLED=true`, manually run the first release, and perform the
   documented failed-candidate and rollback rehearsal.

Missing variables, missing credentials, denied permissions, or missing approval
stop deployment. The guide must distinguish repository-complete from
live-accepted status so documentation never claims an unperformed cloud test.

## Verification strategy

### Repository verification

Retain existing quality, security, Terraform, and web end-to-end suites. Add only
focused checks for the new behavior:

- Terraform validation and mocked tests for federation restrictions, narrow CI
  grants, and the exact lifecycle ignore paths against the pinned provider.
- Workflow syntax/static validation and focused contracts for reusable gates,
  exact commit checkout, deployment concurrency, environment use, job
  permissions, the activation guard, and no JSON-key authentication.
- Small runnable tests for smoke success/failure and release failure handling:
  migration or candidate failure must not promote; post-promotion failure must
  attempt restoration and report a failed restore.
- Existing container architecture, non-root, health, and vulnerability checks
  against the image that will be pushed.

Reuse the repository's test tools. Avoid tests that merely mirror workflow YAML;
exercise failure behavior. Environment reviewer settings and effective cloud
permissions require live verification, not only repository assertions.

### Live acceptance

The learner records a concise checklist covering:

1. Local identity bootstrap, environment protection, and denied federation from
   an unauthorized repository or branch context.
2. An approved release with one tested/scanned image, the same digest on the
   migration execution and API revision, and migration completion before
   candidate deployment.
3. Zero-traffic candidate smoke, successful promotion and stable smoke, and a
   useful GitHub summary without exposed credentials or secret payloads.
4. An injected candidate failure leaving traffic unchanged, and an injected
   post-promotion smoke failure restoring and verifying the previous revision.
5. The manual rollback runbook, including pausing delivery before recovery.
6. Serialized deployment mutations, safe reruns, and acceptable replacement of
   an older pending release.
7. A final local Terraform plan with no drift caused by release-owned fields.

Document observed results and any unresolved failure. Local tests alone do not
establish live cloud acceptance.

## Deliverables

Phase 19 produces only the files needed for the release path:

- this design specification;
- a task-level implementation plan;
- the release workflow and minimal reusable-workflow changes;
- focused release safety and smoke scripts with tests;
- Terraform Workload Identity, IAM, and exact ownership-boundary changes;
- a Phase 19 learner guide covering bootstrap, activation, evidence, failure
  rehearsal, rollback, and recovery; and
- honest README and curriculum-roadmap status updates.

## Non-goals

- Application, API, mobile, or web product features.
- Replacing or orchestrating Cloudflare Pages Git integration.
- Staging, production, multi-region, canary percentages, or general platform
  abstractions.
- Service-account JSON keys or other long-lived CI credentials.
- Automatic database downgrades or destructive contract migrations.
- Terraform plan/apply in application CI or automated infrastructure delivery.
- Docker archive transport, archive checksum bookkeeping, or custom release
  metadata parsers.
- A workflow rollback mode, arbitrary historical rollback selection, or GitHub
  API checks of historical release success.
- Conflicting Terraform and release ownership of Cloud Run attributes.
- External paging or chat notifications; GitHub status, summaries, and artifacts
  are sufficient until Phase 21 observability work.
- A release database, custom deployment controller, or Cloud Deploy adoption.

## References

- [GitHub deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
- [GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc)
- [Google Cloud Workload Identity Federation for deployment pipelines](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Cloud Run rollouts, rollbacks, and traffic migration](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration)
- [Artifact Registry image push and digest behavior](https://docs.cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling)
- [Terraform `ignore_changes`](https://developer.hashicorp.com/terraform/language/meta-arguments/lifecycle)
