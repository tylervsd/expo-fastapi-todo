# Phase 19: Continuous Delivery, Revisions, and Rollback

**Status:** Proposed for learner review

**Date:** 2026-09-14

**Base:** `main` at `d05ebc0` (Phase 18)

**Branch:** `codex/phase-19-continuous-delivery`

**Worktree:** `.worktrees/phase-19-continuous-delivery`

## Outcome

Every commit merged to `main` is either rejected by the existing quality and
security gates or becomes one auditable sandbox release. The release builds the
API image once, records its provenance, reviews an exact Terraform plan, waits
for one protected-environment approval, runs forward-compatible migrations,
tests a zero-traffic Cloud Run revision, and only then moves production traffic.

A failed candidate receives no production traffic. A failure detected after
promotion returns traffic to the previously serving revision. Rollback never
rebuilds an image, reruns migrations, or attempts a database downgrade.

Phase 19 automates the existing Google Cloud sandbox only. The Phase 17
Cloudflare Pages Git integration remains unchanged.

## Success criteria

Phase 19 is complete when:

1. Pull requests retain the existing quality, security, and web end-to-end
   checks.
2. A `main` release validates the exact release commit without duplicating the
   same checks through separate `main` workflow triggers.
3. GitHub authenticates to Google Cloud through short-lived Workload Identity
   Federation credentials; no service-account JSON key exists.
4. A read-only identity creates one saved Terraform plan before approval, and
   the approved deploy job applies that exact plan.
5. The tested API image is pushed once, resolved to an immutable Artifact
   Registry digest, and that digest is used by both the migration job and API
   revision.
6. Migrations finish before candidate deployment.
7. The candidate revision receives zero production traffic until its tagged URL
   passes health, CORS, and database-connectivity smoke tests.
8. A successful candidate receives 100% traffic and passes the same smoke tests
   through the stable service URL.
9. A failed candidate leaves traffic unchanged; a failed post-promotion smoke
   restores 100% traffic to the captured previous revision.
10. A protected, manual rollback can select a previously successful revision and
    return traffic to it without changing the database or Terraform-managed
    infrastructure.
11. The workflow publishes a concise release record connecting commit, build
    checksum, registry digest, migration execution, candidate revision,
    Terraform plan, smoke results, and final traffic state.
12. A final Terraform plan reports no drift from release-owned image, revision,
    or traffic changes.

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

The Phase 18 live label-drift follow-up must be closed before delivery is
activated. It does not block writing or testing the Phase 19 repository changes.

## Chosen architecture

Use GitHub Actions plus native Google Cloud capabilities:

- GitHub reusable workflows provide the existing gates.
- GitHub OIDC and Google Workload Identity Federation provide short-lived
  credentials.
- Terraform owns stable infrastructure and identity configuration.
- `gcloud` owns release-specific Cloud Run mutations.
- GitHub Environments provide the single human approval boundary.
- Cloud Run revisions, tags, and traffic provide candidate testing and rollback.

This is the smallest architecture that preserves one infrastructure owner while
allowing release-specific revision and traffic operations.

### Rejected alternatives

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
| GitHub plan and deploy service accounts | Terraform | Separate identities with separate least-privilege grants |
| Artifact Registry repository | Terraform | Stable repository configuration only |
| Image build, tag, push, and digest | Release workflow | One tested build per release attempt; deploy by digest |
| Cloud Run service configuration | Terraform | Runtime identity, scaling, networking, secrets, environment, and other stable settings |
| API image, revision name, candidate tag, and traffic | Release workflow | Exact, narrowly ignored Terraform attributes |
| Migration job configuration | Terraform | Stable job configuration, runtime identity, networking, secrets, and resources |
| Migration job image and execution | Release workflow | Same release digest as the API; execute once before candidate deployment |
| Cloud Run runtime and migration identities | Terraform | Remain distinct from GitHub identities |
| Secret payloads | External bootstrap | Never read into Terraform state, plans, logs, or artifacts |
| Cloudflare Pages deployment | Existing Git integration | Unchanged and outside the Google release transaction |

No resource or attribute has two active writers.

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

A new `release.yml` runs on:

- every push to `main`; and
- `workflow_dispatch` for activation rehearsal, retry, or rollback.

The normal release path is:

```text
quality + security + web E2E
             |
             v
 build once + scan + preserve image artifact
             |
             v
 read-only Terraform plan + release evidence
             |
             v
     sandbox environment approval
             |
             v
 push digest -> apply saved plan -> migrate -> candidate smoke
             |
             v
       100% traffic -> stable smoke
             |
             v
          release record
```

The workflow uses concurrency group `sandbox-release` with cancellation disabled.
One release must finish or fail before another mutates the sandbox.

### Activation guard

Repository variable `DELIVERY_ENABLED` defaults to absent or `false`. While it
is not exactly `true`, `main` still runs all validation jobs and reports that
delivery is not activated, but no job requests Google credentials or mutates
Google Cloud.

The guard is a migration control, not an emergency bypass. Once the first live
release and rollback rehearsal pass, normal branch protection remains the
primary safety mechanism.

## Identity and authorization

Terraform adds one GitHub Workload Identity provider and two Google service
accounts:

- **Plan identity:** may inspect the managed sandbox resources and use the
  minimum required Terraform state-bucket permissions for planning and locking.
  It cannot push images, apply infrastructure, run migrations, create revisions,
  or move traffic.
- **Deploy identity:** may access the state bucket to apply the reviewed sandbox
  Terraform plan, push to the existing API repository, update and execute the
  migration job, create a Cloud Run revision, manage revision tags, and move
  service traffic. It receives no Owner, Editor, service-account-key, or
  project-wide secret access.

Exact permissions are derived from failed-permission evidence during the
bootstrap rehearsal and documented beside the grants. Prefer existing narrow
Google roles; add a custom role only if predefined roles would materially exceed
the required resource scope.

The provider maps the immutable claims needed for authorization, including
numeric repository ID, numeric owner ID, ref, workflow reference, and subject.
Its provider condition requires:

- the expected numeric repository and owner IDs;
- the exact `refs/heads/main` ref for releases; and
- the expected release workflow.

The plan service-account binding accepts the exact main-ref subject. The deploy
service-account binding accepts only the environment subject
`repo:<owner>/<repository>:environment:sandbox`. This lets the plan job obtain
read-only credentials before approval while making the protected environment a
credential boundary for mutation.

Repository and owner names are not trust anchors because names can be deleted,
renamed, and reused.

Workflow permissions default to read-only. `id-token: write` appears only on the
plan and approved deploy jobs that exchange OIDC tokens. Actions are pinned to
full commit SHAs.

The initial identity resources and grants are applied once with the learner's
local Application Default Credentials. No downloaded service-account key is
created as a bootstrap shortcut.

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

The plan job produces a saved binary plan. It also generates a human-readable
summary that identifies creates, updates, replacements, and deletes. Any delete
or replacement fails before approval; Phase 19 has no legitimate case for one.
The approved deploy job downloads and applies the exact saved plan; it never
regenerates a substitute plan.

Because saved plans can contain cleartext state data, the binary plan is treated
as sensitive release evidence: one-day retention, no log dump, no uploaded JSON
export, and no secret payloads in Terraform-managed attributes. An ephemeral JSON
render may be parsed inside the plan job for action validation, but it is neither
logged nor uploaded. A stale or missing plan requires a new release attempt and
a new approval.

## Image build and provenance

The API image is built once for `linux/amd64` before any Google mutation. The
workflow:

1. builds from the release commit;
2. runs the existing container and health checks;
3. scans the built image using the existing security toolchain;
4. labels it with the source commit;
5. saves it as a short-lived workflow artifact; and
6. records the artifact checksum.

After approval, the workflow loads that artifact instead of rebuilding it,
pushes it to Artifact Registry under a unique, never-reused release tag, and
records the registry digest reported by the push. It resolves the tag from
Artifact Registry and fails if the resolved digest differs from the pushed
digest.

Every later command uses the immutable `repository@sha256:...` reference. The
release record connects source commit, saved-artifact checksum, pushed tag,
registry digest, migration execution, and Cloud Run revision. Formal external
attestation infrastructure is deferred until a policy requires it; the single
build and checked digest chain provide the required Phase 19 provenance.

## Normal release sequence

After all gates pass, the release performs these steps in order:

1. Read and record the currently serving 100% revision as the rollback target.
2. Complete the one-build, local validation, scan, artifact checksum, and saved
   Terraform plan work described above.
3. Wait for the `sandbox` GitHub Environment approval.
4. Authenticate as the deploy identity, push the preserved image, and resolve
   its immutable digest.
5. Apply the exact saved Terraform plan.
6. Update the existing migration job to the release digest and execute it once.
   Wait for successful completion and record the execution name.
7. Deploy a uniquely named, tagged API candidate using the same digest and zero
   production traffic.
8. Smoke-test the candidate's tagged URL.
9. Move 100% production traffic to the candidate revision.
10. Repeat the smoke tests through the stable service URL.
11. Remove the temporary candidate tag and publish the release record.

Release names are deterministic from the GitHub run and short commit SHA so a
rerun is distinguishable without inventing a release database.

Before any mutation, the release must observe exactly one named revision serving
100% of traffic. Any manual split or ambiguous traffic state fails closed rather
than guessing a rollback target.

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

1. `GET /health` returns `200` with `{\"status\":\"ok\"}`.
2. A CORS preflight from `https://expo-fastapi-todo.pages.dev` returns the
   expected allow-origin behavior.
3. An invalid `POST /auth/login` returns exactly `401`, proving that the request
   reached the database without creating or depending on test data. A database
   outage already maps this path to `503`, so it cannot falsely pass.

The script accepts an explicit base URL and contains no environment discovery or
deployment mutation. The same checks run against the tagged candidate URL and
the stable service URL.

## Failure handling

- Validation, build, scan, plan, approval, push, apply, or migration failure
  stops the release before a candidate receives production traffic.
- Candidate smoke failure leaves existing traffic unchanged, removes the
  temporary tag where possible, and retains the zero-traffic revision for
  investigation.
- Stable smoke failure immediately assigns 100% traffic to the captured previous
  revision and verifies the stable URL again.
- An unsuccessful automatic traffic restore is a hard failure requiring learner
  action; the workflow reports both desired and observed traffic state.
- Mutation steps are not automatically retried. A workflow rerun is a new,
  serialized release attempt that rediscovers current traffic and obtains a new
  plan and approval.

## Manual rollback

`workflow_dispatch` supports a rollback mode with an exact previously successful
revision name. The workflow:

1. validates that the revision belongs to the expected sandbox service;
2. reads its release-run label and verifies through the GitHub Actions API that
   the referenced release workflow run completed successfully;
3. waits for the same `sandbox` environment approval;
4. moves 100% traffic to that revision; and
5. runs the stable smoke contract.

Rollback does not rebuild or push an image, apply Terraform, execute migrations,
delete revisions, or bypass branch and environment protections.

Candidate revisions carry the source commit and GitHub run ID as Cloud Run
labels. Those labels connect the revision to the release record and provide the
manual rollback validation input; they do not create a second release database.

## Activation and required learner interaction

Repository changes can merge with delivery disabled. Live activation requires
four deliberate learner actions:

1. Close the Phase 18 live drift follow-up.
2. Run the documented local Terraform bootstrap with Application Default
   Credentials to create Workload Identity Federation and its IAM bindings.
3. Configure and protect the GitHub `sandbox` Environment, set the documented
   non-secret repository/environment variables, and add required reviewers.
4. Set `DELIVERY_ENABLED=true`, manually run the first release, and perform the
   documented failed-candidate and rollback rehearsal.

Missing variables, missing credentials, denied permissions, missing approval, or
stale evidence fail closed. The guide must distinguish repository-complete from
live-accepted status so documentation never claims an unperformed cloud test.

## Verification strategy

### Repository verification

Automated checks cover:

- Terraform configuration and mocked tests for Workload Identity claim
  restrictions, least-privilege bindings, and exact lifecycle ignore paths;
- repository contract tests for workflow triggers, reusable gates, concurrency,
  environment protection, job permissions, SHA-pinned actions, activation guard,
  and the absence of JSON-key authentication;
- focused tests for Terraform plan-action parsing and release metadata parsing;
- the existing full quality, security, Terraform, and web end-to-end suites;
- local container architecture, non-root execution, health, and vulnerability
  checks; and
- workflow syntax and static validation without Google Cloud access.

The smoke script uses the smallest runnable tests needed to lock its exact health,
CORS, database, and failure behavior.

### Live acceptance

The learner records evidence for:

1. successful local identity bootstrap;
2. denied federation from a wrong repository or branch context;
3. a reviewed saved plan and protected-environment approval;
4. one build with a continuous commit-to-artifact-to-registry digest chain;
5. the same digest on the migration execution and API revision;
6. successful migration before candidate creation;
7. candidate deployment at zero traffic and successful tagged-URL smoke;
8. an injected candidate smoke failure that leaves traffic unchanged;
9. successful 100% promotion and stable-URL smoke;
10. successful manual rollback to the recorded previous revision;
11. serialization and safe rerun behavior; and
12. a final Terraform plan with no release-field drift.

Logs and artifacts are inspected to confirm they contain no downloaded keys,
secret payloads, or unredacted credentials.

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
- Automatic Terraform apply without the protected environment approval.
- Two tools owning the same Cloud Run attribute.
- External paging or chat notifications; GitHub status, summaries, and artifacts
  are sufficient until Phase 21 observability work.
- A release database, custom deployment controller, or Cloud Deploy adoption.

## References

- [GitHub deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub deployment controls and concurrency](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments)
- [GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc)
- [Google Cloud Workload Identity Federation for deployment pipelines](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Cloud Run rollouts, rollbacks, and traffic migration](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration)
- [Artifact Registry image push and digest behavior](https://docs.cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling)
- [Terraform `ignore_changes`](https://developer.hashicorp.com/terraform/language/meta-arguments/lifecycle)
- [Terraform saved plans](https://developer.hashicorp.com/terraform/cli/commands/plan)
- [Terraform automation guidance](https://developer.hashicorp.com/terraform/tutorials/automation/automate-terraform)
