# Phase 19 Continuous Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver validated API commits to the existing sandbox with one CI
identity, one tested image, compatible migrations, candidate smoke tests, and
rehearsed traffic rollback.

**Architecture:** GitHub Actions calls the existing quality/security/web gates,
then runs one approved, serialized deploy job. Two small Python standard-library
scripts handle HTTP smoke checks and the migration/traffic sequence. Terraform
stays in the existing reviewed local process; recovery uses a manual runbook.

**Tech Stack:** GitHub Actions, Google OIDC/WIF, Artifact Registry, Cloud Run,
Docker, existing Trivy action, Python 3.14.7 standard library, Bats, Terraform
1.14.7 and hashicorp/google 8.2.0.

**Spec:** [Phase 19 design](../specs/2026-09-14-continuous-delivery-design.md).

## Global Constraints

- Work in `.worktrees/phase-19-continuous-delivery` on
  `codex/phase-19-continuous-delivery`; preserve the revised spec already there.
- Planning creates this document only. Tasks 1–5 implement repository changes;
  Task 6 is separate learner-operated live acceptance.
- Terraform plans/applies remain local. Application CI gets no state-bucket,
  infrastructure administration, Owner, Editor, key-management, or project-wide
  secret-access grants.
- One CI deploy service account; existing runtime and migration identities remain
  distinct. Use short-lived WIF credentials and full-SHA action pins.
- `DELIVERY_ENABLED` defaults to absent or `false`; only exactly `true` allows
  deployment. Releases run from `refs/heads/main` and environment `sandbox`.
- The mutation job uses `sandbox-release` and `cancel-in-progress: false`.
  Pending runs may be superseded; do not implement an every-commit queue.
- Approval precedes the single `linux/amd64` image build/test/scan/push job.
  Both migration and API use the same `repository@sha256:...` digest.
- Preserve stable Cloud Run configuration, public invocation, and secret version
  references. Do not add Cloud Run labels that require additional ignore rules.
- Candidate gets zero production traffic until smoke passes. Stable smoke failure
  restores the previous revision. Never downgrade the database.
- No image archive transport, saved-plan artifacts, release database, metadata
  parser, workflow rollback mode, or new application dependencies.
- Phase 18 label-drift verification was confirmed closed by the learner on
  2026-09-15. Do not reopen deferred Phase 18 recovery/destruction drills.

## Execution and file map

All paths and commands below are relative to the Phase 19 worktree root. Use the
existing worktree; do not create another one or change another task's files.

| Task | Files | Result |
| --- | --- | --- |
| 1 | Create `scripts/release_smoke.py`, `tests/test_release.py` | Exact HTTP checks, bounded retries, offline tests |
| 2 | Create `infra/terraform/sandbox/delivery.tf`; modify `variables.tf`, `outputs.tf`, `run.tf`, `terraform.tfvars.example`, `tests/safety.tftest.hcl` in that root | WIF/deploy grants and narrow ownership boundary |
| 3 | Create `scripts/release_deploy.py`; extend `tests/test_release.py` | Testable migration, candidate, promotion, and restoration sequence |
| 4 | Create `.github/workflows/release.yml`; modify the three existing workflows, `tests/repository_contract.bats`, `package.json`, `.gitignore` | One gated release path with checks wired into CI |
| 5 | Create `docs/guides/19-continuous-delivery.md`; modify `README.md`, `docs/curriculum-roadmap.md`, `infra/terraform/README.md` | Bootstrap, pause/recovery, acceptance guide and honest status |
| 6 | Update only acceptance records after learner execution | Live sign-off or explicit remaining failures |

Execute 1 → 2 → 3 → 4 → 5. Task 2 can run alongside Task 1 if useful; both
must finish before integration. Keep Tasks 3 and 4 sequential because they share
the release interface. Do not parallelize writes to the same test file.

Routing: planning/architecture uses `gpt-6-astra` medium; well-defined mechanical
work uses `gpt-5.6-luna`; integration and difficult debugging use
`gpt-5.6-terra`; significant and final branch reviews use `gpt-5.6-sol` medium.
Luna must return scope/architecture gaps to the Sol controller, not redesign them.
Use focused commits at each completed task; do not merge or activate delivery as
part of repository implementation.

## Task 1: Implement the reusable smoke contract

**Files:** Create `scripts/release_smoke.py` and `tests/test_release.py`.

**Interfaces:** `check(base_url: str) -> None` runs one check set;
`smoke(base_url: str, *, attempts: int = 12, delay: float = 5) -> None` retries
failed sets within that bound. CLI: `python3 scripts/release_smoke.py BASE_URL`.
Success exits 0; exhausted attempts or invalid arguments exit nonzero.

- [x] **1. Read the current HTTP behavior.** Read `UserLogin`, `/auth/login`,
  CORS middleware, and `/health` in `apps/api/app/main.py`, plus username/password
  validators. Login accepts JSON with `username` and `password`, not email or
  form data. Confirm a nonexistent valid username returns 401 after querying DB.

- [x] **2. Add a failing standard-library test.** Load the script by adding
  `scripts` to `sys.path`; use `unittest`, `unittest.mock`, and `BytesIO`.
  A response helper in this one test file may return status, headers, and bytes.
  No new test package or framework. Include this retry test:

```python
from unittest.mock import patch
import release_smoke

# Inside a unittest.TestCase method:
with patch.object(release_smoke, "check", side_effect=RuntimeError("DB 503")) as check:
    with self.assertRaises(RuntimeError):
        release_smoke.smoke("https://example.run.app", attempts=2, delay=0)
self.assertEqual(check.call_count, 2)
```

  Add HTTP cases for exact health JSON, wrong health body, wrong CORS origin,
  login 401 success, login 200/422/503 failure, and timeout. Inspect outgoing
  requests to prove no signup or authenticated write is made.

- [x] **3. Run the new tests before implementation.**

```sh
python3 -m unittest discover -s tests -p test_release.py -v
```

  Expect failure because `release_smoke` is absent, then assertion failures while
  filling in its behavior.

- [x] **4. Implement using `urllib.request`, `urllib.error`, `json`, and `time`.**
  Use a ten-second timeout per request, no unbounded loops, and no response-body
  logging. Treat `HTTPError` as an HTTP response so expected 401 can pass. Reject
  redirects instead of following login payloads to a different origin. Accept
  HTTPS cloud URLs and HTTP loopback URLs for local checks, with no URL userinfo.
  Execute these requests in order:

```python
# Request data; the origin is fixed by this project's deployed web app.
origin = "https://expo-fastapi-todo.pages.dev"
preflight_headers = {
    "Origin": origin,
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}
# Generate a fresh valid username per check to avoid depending on a real account.
# Keep it within the application's username length limit.
```

  Require health status 200 and parsed body `{"status": "ok"}`; preflight status
  200, exact allow-origin, POST in allowed methods, and content-type in allowed
  headers; invalid login status exactly 401. Use `secrets.token_hex` for valid
  random credentials and never print them. `check()` raises a concise
  `RuntimeError` naming the failed endpoint/status. `smoke()` returns on the first
  complete passing set, otherwise raises the final error after bounded retries.
  Guard the CLI with `if __name__ == "__main__"` so tests can import it.

- [x] **5. Run the tests and existing Ruff on these files; commit on success.**

```sh
python3 -m unittest discover -s tests -p test_release.py -v
uv run --directory apps/api ruff check ../../scripts/release_smoke.py ../../tests/test_release.py
git add scripts/release_smoke.py tests/test_release.py
git commit -m "feat: add deployment smoke checks"
```

## Task 2: Add the CI identity and Terraform ownership boundary

**Files:** The Terraform files listed in the file map. Reuse existing API/job,
registry, project-number data source, IAM member patterns, and mock inventory.

**Interfaces:** Add nullable `github_delivery` input (default `null`) with string
fields `repository`, `repository_id`, `owner_id`. IDs must contain only digits;
repository must be an owner/repository pair. Fixed pool/provider/account IDs:
`github-delivery`, `github`, `github-deploy`. Output
`github_workload_identity_provider` and `github_deploy_service_account`, null
when disabled. The existing Phase 18 input files must still validate unchanged.

- [x] **1. Extend the existing mock tests before adding resources.** Add one run
  with `github_delivery = null` and one with fictional repository IDs. Check the
  provider condition, exact environment principal, grants and output names.

```hcl
run "delivery_identity" {
  command = plan
  variables {
    github_delivery = {
      repository    = "example-owner/example-repo"
      repository_id = "123456789"
      owner_id      = "987654321"
    }
  }
  assert {
    condition = strcontains(
      google_iam_workload_identity_pool_provider.github[0].attribute_condition,
      "assertion.repository_id == '123456789'"
    )
    error_message = "Federation must restrict the numeric repository ID."
  }
}
```

  Add equivalent assertions for numeric owner, main ref, exact workflow ref,
  environment subject binding, and only the intended resource-scoped grants.
  Reuse global fixtures already in `safety.tftest.hcl` rather than copying them.

- [x] **2. Run the focused Terraform tests and observe missing-input/resource
  failures.** Use the existing pinned local Terraform binary if not on PATH.

```sh
terraform -chdir=infra/terraform/sandbox init -backend=false -lockfile=readonly
terraform -chdir=infra/terraform/sandbox test -filter=tests/safety.tftest.hcl
```

- [x] **3. Implement `delivery.tf` with conditional resources.** Use `count` for
  the nullable delivery input. Create the pool, provider, and one service account;
  use additive IAM member resources. Map `google.subject = assertion.sub` and
  the repository/owner/ref/workflow attributes. Build this condition from the
  typed input, preserving all four restrictions:

```text
assertion.repository_id == '123456789' &&
assertion.repository_owner_id == '987654321' &&
assertion.ref == 'refs/heads/main' &&
assertion.workflow_ref == 'example-owner/example-repo/.github/workflows/release.yml@refs/heads/main'
```

  Bind `roles/iam.workloadIdentityUser` on the deploy account to the exact
  `principal://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-delivery/subject/repo:OWNER@OWNER_ID/REPO@REPOSITORY_ID:environment:sandbox`
  value assembled from `data.google_project.current.number` and the input.
  The capitalized components here describe Terraform expressions, not literal
  values to put in source or documentation examples.

  Starting grants: Artifact Registry Writer on the existing repository; Cloud Run
  Developer on the existing API service and migration job; Service Account User
  on the two existing runtime identities. Confirm job execution/read permissions
  in the pinned provider and Google role reference. Add only evidenced missing
  narrow grants during rehearsal; no project-wide Run Admin or token-key grants.
  Check the requirements for generating a short-lived impersonated access token
  with WIF; do not add Token Creator reflexively.

  Reuse `google_project_service.required` for IAM Credentials and STS API
  enablement by updating the documented example/input prerequisites. No duplicate
  Terraform addresses for already managed APIs or IAM grants. Keep fake examples
  opt-in (`github_delivery = null` by default); the guide supplies real values
  locally. Do not create live resources during this task.

- [x] **4. Add the exact lifecycle exclusions to the two existing resources.**

```hcl
# google_cloud_run_v2_service.api, retaining prevent_destroy:
ignore_changes = [
  template[0].containers[0].image,
  template[0].revision,
  traffic,
]

# google_cloud_run_v2_job.migrate, retaining prevent_destroy:
ignore_changes = [template[0].template[0].containers[0].image]
```

  Validate these paths with Terraform's pinned schema/validation; use Phase 18's
  backend-free schema workspace when schema inspection needs it. Do not claim a
  mocked test proves live drift behavior. Preserve all other configuration and
  protections. Check that the imported migration job has no platform retries if
  the release promises one execution attempt; any required change to
  `max_retries` is a reviewed local prerequisite, not an application CI mutation.

- [x] **5. Run all sandbox tests, validation and formatting; commit.**

```sh
terraform -chdir=infra/terraform/sandbox fmt
terraform -chdir=infra/terraform/sandbox validate
terraform -chdir=infra/terraform/sandbox test
git add infra/terraform/sandbox
git commit -m "feat: define delivery identity and release ownership"
```

## Task 3: Implement the migration and traffic sequence

**Files:** Create `scripts/release_deploy.py`; extend `tests/test_release.py`.

**Interfaces:** CLI `python3 scripts/release_deploy.py IMAGE_DIGEST PREVIOUS_REVISION`.
Required environment: `CLOUD_PROJECT`, `CLOUD_REGION`, `CLOUD_SERVICE`,
`CLOUD_MIGRATION_JOB`, `CLOUD_IMAGE`, `RELEASE_ID`, `GITHUB_SHA`,
`GITHUB_STEP_SUMMARY`. `CLOUD_IMAGE` is the full registry image path without a tag.
`RELEASE_ID` is `rRUN_ID-aATTEMPT-SHORT_SHA`; candidate name is
`CLOUD_SERVICE-RELEASE_ID`, and tag is `RELEASE_ID`.

Expose only small functions needed by the script/tests:
`cloud(*args: str) -> dict` runs gcloud with explicit project/region/JSON flags;
`serving_revision(service: dict) -> str` validates observed traffic;
`deploy(image: str, previous: str) -> None` runs the sequence. Import
`smoke` from `release_smoke`. Tests patch `cloud` and `smoke` directly.

- [x] **1. Write a failing restoration test and failure matrix.** Use
  `unittest.mock`; fake only command responses, not the rollout logic. Maintain
  one command list so tests assert ordering and absence of dangerous calls.

```python
# Core assertion inside the stable-smoke-failure test, after fake cloud replies
# provide a named 100% previous revision, migration success and tagged candidate:
with patch.object(release_deploy, "cloud", side_effect=fake_cloud):
    with patch.object(release_deploy, "smoke",
                      side_effect=[None, RuntimeError("stable failed"), None]):
        with self.assertRaises(RuntimeError):
            release_deploy.deploy(image, previous)
self.assertIn(("run", "services", "update-traffic", service,
               "--to-revisions=" + previous + "=100"), commands)
```

  Define `fake_cloud`, `image`, `previous`, `service`, and `commands` in this test
  file from the interface above. Its replies use actual gcloud JSON shapes,
  including `status.traffic`, `revisionName`, `percent`, `tag`, `url`, and
  migration completion conditions. Cover: split/empty traffic, tagged zero-traffic
  entries, migration failure, missing candidate URL, candidate smoke failure,
  promotion failure with uncertain outcome, stable failure, restore failure,
  cleanup failure, and success. A successful restore still leaves the release
  failed. No mutation is retried automatically.

- [x] **2. Run the tests and confirm they fail before the deploy script exists.**

```sh
python3 -m unittest discover -s tests -p test_release.py -v
```

- [x] **3. Implement the sequential commands using argument lists, never a shell.**
  Validate the digest against `CLOUD_IMAGE` and `sha256:` plus 64 hexadecimal
  characters. Validate resource/release names and candidate name length before
  any mutation. Read the service and confirm the captured previous revision is
  still the only named revision receiving 100%. Zero-percent tagged entries
  must not be mistaken for a split. Read the stable URL from service status;
  never construct tagged URLs by guessing hostnames.

  The cloud command sequence is:

```sh
# cloud() supplies --project, --region, --quiet and --format=json.
gcloud run jobs update "$CLOUD_MIGRATION_JOB" --image="$IMAGE_DIGEST"
gcloud run jobs execute "$CLOUD_MIGRATION_JOB" --wait
gcloud run deploy "$CLOUD_SERVICE" --image="$IMAGE_DIGEST" \
  --revision-suffix="$RELEASE_ID" --tag="$RELEASE_ID" --no-traffic
gcloud run services describe "$CLOUD_SERVICE"
gcloud run services update-traffic "$CLOUD_SERVICE" \
  --to-revisions="$CANDIDATE_REVISION=100"
```

  Capture the returned execution name; verify successful completion and the
  migration image digest before creating the candidate. Verify the candidate
  revision image digest, find its tag URL by exact tag/revision match, confirm
  production traffic remains on the previous revision, and call `smoke(url)`.
  After promotion, verify observed traffic and call `smoke(stable_url)`.
  These are updates of existing resources, not replacements of runtime settings;
  pass no environment, secrets, identity, scaling, or public-access flags.

- [x] **4. Implement restoration and always-on summary/cleanup.** Set
  `promotion_attempted = True` immediately before the promotion command. If it
  raises or subsequent verification fails, attempt one traffic restore and
  verify the stable URL. If the restore fails, report both errors and observed
  traffic (or explicitly unknown). Never mark a failed release green merely
  because restoration succeeded. Before promotion, failures leave traffic alone.

```python
# Restoration command, followed by observed-traffic verification and stable smoke:
cloud("run", "services", "update-traffic", service,
      "--to-revisions=" + previous + "=100")
# In finally, attempt only this release's tag cleanup:
cloud("run", "services", "update-traffic", service,
      "--remove-tags=" + release_id)
```

  A cleanup error must not suppress the original failure or cause traffic to
  move again. Append a plain Markdown summary in `finally` with commit, digest,
  execution, previous/candidate, smoke results and final observed traffic; use
  `not reached`/`unknown` when a stage failed early. No JSON evidence artifact.
  Keep command output in memory and report selected fields, not full resource
  dumps. Set finite subprocess timeouts and reserve time for restore/cleanup.
  Document that runner loss or forced cancellation needs the manual runbook.

- [x] **5. Run tests and Ruff; commit on success.**

```sh
python3 -m unittest discover -s tests -p test_release.py -v
uv run --directory apps/api ruff check ../../scripts/release_smoke.py ../../scripts/release_deploy.py ../../tests/test_release.py
git add scripts/release_deploy.py tests/test_release.py
git commit -m "feat: deploy candidates with verified traffic rollback"
```

## Task 4: Wire the single release workflow

**Files:** `.github/workflows/{release,quality,security,e2e}.yml`,
`tests/repository_contract.bats`, `package.json`, `.gitignore`.

**Interfaces:** Repository variable `DELIVERY_ENABLED`. Sandbox environment
variables `CLOUD_PROJECT`, `CLOUD_REGION`, `CLOUD_SERVICE`, `CLOUD_MIGRATION_JOB`,
`CLOUD_IMAGE`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`. No target inputs
on dispatch: targets come only from the configured sandbox environment.

- [x] **1. Update the failing trigger/security contracts.** Replace the existing
  security test's requirement for `push:` with `workflow_call:`. Cover main-only
  release dispatch, activation guard, deploy-only OIDC, full-SHA actions, one
  deployment lock, and the same digest passed to Task 3. Keep meaningful existing
  security assertions. Add `test:release` to package scripts:

```json
"test:release": "python3 -m unittest discover -s tests -p test_release.py -v"
```

  Run `bats tests/repository_contract.bats` and confirm failures for the missing
  release workflow and callable gates. Do not add a bespoke YAML parser.

- [x] **2. Make the existing gates reusable without changing their checks.**
  Add `workflow_call` and remove direct `push: main` in all three workflows.
  Preserve PR triggers, security schedule/manual trigger, and direct E2E manual
  dispatch. Explicitly keep native iOS out of reusable calls:

```yaml
# e2e.yml
on:
  pull_request:
  workflow_dispatch:
  workflow_call:
    inputs:
      run_ios:
        type: boolean
        default: false

# ios job condition: a direct E2E dispatch has github.workflow == 'e2e';
# a reusable call inherits the release caller's event and workflow context.
if: >-
  github.event_name == 'workflow_dispatch' &&
  (github.workflow == 'e2e' || inputs.run_ios)
```

  Release always passes `run_ios: false`. Use the existing `name: e2e` in this
  condition. Adjust the workflow comment and add a contract for this distinction.
  Run `pnpm test:release` in quality's existing Python-enabled application job;
  add Ruff checks for the three new Python files there too.

- [x] **3. Create the release topology with exact checkout and permissions.**

```yaml
name: release
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  quality:
    uses: ./.github/workflows/quality.yml
  security:
    permissions:
      actions: read
      contents: read
      packages: read
      security-events: write
    uses: ./.github/workflows/security.yml
  web:
    uses: ./.github/workflows/e2e.yml
    with:
      run_ios: false
  deploy:
    needs: [quality, security, web]
    if: github.ref == 'refs/heads/main' && vars.DELIVERY_ENABLED == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 45
    environment: sandbox
    concurrency:
      group: sandbox-release
      cancel-in-progress: false
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          ref: ${{ github.sha }}
```

  Bind environment variables through `env:`, not interpolation into shell code.
  Add a read-only status job when delivery is disabled to write the reason to
  `$GITHUB_STEP_SUMMARY`. Do not put workflow-level concurrency around validation.
  Caller security permissions are required because reusable jobs cannot elevate
  the caller's token permissions.

- [x] **4. Pin authentication/tool actions and validate inputs before cloud use.**
  Resolve the official `google-github-actions/auth` and `setup-gcloud` v3 refs to
  commits at execution time; record verified 40-character SHAs with version
  comments in the workflow. Use this read-only lookup, then inspect each action's
  `action.yml` at that commit before using it:

```sh
gh api repos/google-github-actions/auth/commits/v3 --jq .sha
gh api repos/google-github-actions/setup-gcloud/commits/v3 --jq .sha
```

  Pin gcloud to the existing recorded `584.0.0` if the rehearsal confirms these
  commands work; route a necessary version change through the controller. Reuse
  existing Python setup and Trivy action SHAs. Fail on empty environment values
  or a checkout SHA different from `GITHUB_SHA`. Add `gha-creds-*.json` to root
  `.gitignore`; keep Docker's build context `apps/api`, excluding root credentials.

  Authenticate as the single deploy account after approval. Request a masked
  short-lived impersonated access token with `token_format: access_token` and
  `access_token_lifetime: 3600s`; use its output through
  `CLOUDSDK_AUTH_ACCESS_TOKEN` for gcloud and `docker login --password-stdin`.
  Never echo the token. The 45-minute job must fit inside token lifetime; verify
  this auth mode during bootstrap, including access after the image build.
  Do not depend on an expired five-minute source OIDC token after a long build.

- [x] **5. Capture previous traffic, then build/test/scan/push exactly once.**
  Use Task 3's `serving_revision()` on a captured gcloud service JSON response;
  save only its returned revision to `GITHUB_OUTPUT`. Read it after approval.
  Build the release ID from run ID, attempt, and the first eight SHA characters.
  Validate Cloud Run's combined name length before building.

```sh
docker buildx build --platform linux/amd64 --load \
  --label "org.opencontainers.image.revision=$GITHUB_SHA" \
  --tag "$CLOUD_IMAGE:$RELEASE_ID" apps/api
docker image inspect "$CLOUD_IMAGE:$RELEASE_ID" \
  --format '{{.Architecture}} {{.Config.User}}'
```

  Require `amd64` and the existing `10001:10001` image user. Start the built
  container with `PORT=8080` on loopback, poll `/health` with a fixed timeout,
  assert parsed JSON, and check `docker exec ... id -u` equals `10001`. Remove
  the container with a trap. Local container health needs no production DB;
  do not call the full cloud smoke contract on this DB-free container.

  Run the existing Trivy action against that local tag with `scan-type: image`,
  `exit-code: 1`, `severity: HIGH,CRITICAL` and scanner `vuln`. Only then log in
  and push. Save the push output to the runner's temporary directory, extract
  its one reported sha256 digest, resolve the tag with
  `gcloud artifacts docker images describe --format='value(image_summary.digest)'`,
  and fail if either digest is missing/malformed or they differ. Use the
  digest output as the only image input to Task 3; never rebuild or deploy a tag.

- [x] **6. Invoke rollout and preserve early failure visibility.**

```sh
python3 scripts/release_deploy.py "$IMAGE_DIGEST" "$PREVIOUS_REVISION"
```

  Add an `if: always()` summary step for failures before the rollout script ran,
  using `not reached` for migration/candidate/smoke and observed or unknown traffic.
  Do not duplicate the full summary after the script wrote it. A failure in
  build/scan/push must never run rollout. No step retries cloud mutations.

- [x] **7. Validate workflow syntax and contracts, then commit.** Use `actionlint`
  as a development CLI (not an app dependency), following its official install
  instructions and recording the version used. Pin its verified version/checksum
  if installing it in CI; do not invent an action SHA or skip missing validation.

```sh
actionlint .github/workflows/*.yml
bats tests/repository_contract.bats
pnpm test:release
pnpm lint
git diff --check
git add .github/workflows tests/repository_contract.bats package.json .gitignore
git commit -m "feat: gate sandbox releases through GitHub Actions"
```

## Task 5: Write the learner guide and reconcile curriculum status

**Files:** `docs/guides/19-continuous-delivery.md`, `README.md`,
`docs/curriculum-roadmap.md`, `infra/terraform/README.md`.

**Interfaces:** Guide headings `Prerequisites`, `Bootstrap`, `Activate delivery`,
`Pause delivery`, `Manual rollback`, `Acceptance record`, `Recovery`.
Use the environment variable names from Task 4 exactly.

- [x] **1. Write prerequisites and bootstrap commands.** Include Phase 18 drift
  closure, local ADC, numeric GitHub IDs from `gh api repos/OWNER/REPO`, required
  APIs, local `github_delivery` values and reviewed local Terraform plan/apply.
  Check actual resource names, existing IAM ownership, migration retry settings,
  compatible migrations and retained previous revision before activation.
  Show a non-secret variable table and how Terraform outputs map to the WIF and
  deploy-account environment variables. Missing real values are learner inputs;
  do not guess cloud identities or copy the mock inventory into a live config.

- [x] **2. Document GitHub setup and first activation.** Protect `main`, inspect
  reusable check names before updating required checks, configure `sandbox`
  required reviewers and main-only deployments, and verify the account/repository
  supports those environment controls. Keep `DELIVERY_ENABLED=false` until ready.
  First activation uses `workflow_dispatch` on `main`. Explain that normal gates
  still run while delivery is disabled and pending releases may be superseded.

- [x] **3. Write pause and rollback commands using existing operator access.**
  Include inspecting active/pending run IDs before cancellation; never cancel an
  active mutation just to free the lock. Setting a variable alone does not stop
  already queued/approved work.

```sh
gh variable set DELIVERY_ENABLED --body false
gh workflow disable release.yml
gh run list --workflow release.yml
# Wait for active deployment to finish; cancel only identified pending runs.
# PREVIOUS_REVISION comes from the release summary; inspect the target first.
gcloud run revisions describe "$PREVIOUS_REVISION" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION"
gcloud run services update-traffic "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --update-tags="manual-rollback=$PREVIOUS_REVISION"
```

  Extract the returned tag URL from observed service status. Run
  `python3 scripts/release_smoke.py "$ROLLBACK_URL"` before cutover, then:

```sh
gcloud run services update-traffic "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --to-revisions="$PREVIOUS_REVISION=100"
python3 scripts/release_smoke.py "$STABLE_URL"
gcloud run services update-traffic "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --remove-tags=manual-rollback
```

  Describe exact service-membership/traffic checks, migration compatibility, no
  rebuild/migration/Terraform, and recording failure instead of declaring recovery.
  Resume only after fixing the failed release, with workflow enablement followed
  by deliberate activation. Use the same pause process before local Cloud Run
  infrastructure changes. Include recovery for migration failure, missing tag,
  failed restoration, expired credentials and runner loss; use observed cloud
  state before deciding the next operation.

- [x] **4. Include runnable rehearsal instructions and a pending evidence table.**
  Candidate-failure rehearsal: with delivery paused, use the same verified digest
  and native no-traffic deploy commands; deliberately run smoke against the
  candidate URL with a nonexistent base path and confirm current traffic is
  unchanged. Clean its temporary tag after recording the result.

  Post-promotion rehearsal: with delivery paused, run the actual rollout function
  locally using `unittest.mock.patch` to fail only its second smoke call; real
  candidate and restored-revision smoke calls delegate to `release_smoke.smoke`.
  This exercises the real restoration path without a production failure-injection
  flag. Show the wrapper code in the guide, use a new rehearsal release ID, and
  require the learner to approve this deliberate live promotion/restore cycle.
  A separate normal successful release and manual rollback must also pass.

- [x] **5. Update roadmap copy that still describes the old architecture.**
  Phase 19 currently promises a reviewed Terraform plan in each release and
  rollback of image/configuration. Replace it with application-only delivery,
  local infrastructure changes, one CI identity, digest deployment, compatible
  migrations and traffic-only rollback. Link the spec, this plan, and the guide.
  Mark repository readiness only after checks pass; mark live acceptance pending
  until Task 6. Preserve unrelated earlier-phase acceptance gaps.

- [x] **6. Check Markdown, links and diff; commit.**

```sh
pnpm lint:markdown
pnpm lint:links
git diff --check
git add docs/guides/19-continuous-delivery.md docs/curriculum-roadmap.md README.md infra/terraform/README.md
git commit -m "docs: explain sandbox delivery and manual recovery"
```

## Task 6: Review and learner-operated live acceptance

**Files:** Only update the guide acceptance record and corresponding status text
when supported by results. Do not mark this task complete from offline tests.

- [x] **1. Run repository verification once on the integrated branch.**

```sh
pnpm quality
pnpm test:release
pnpm test:pages
pnpm typecheck:e2e
pnpm test:e2e:web
terraform -chdir=infra/terraform/sandbox validate
terraform -chdir=infra/terraform/sandbox test
terraform -chdir=infra/terraform/drill init -backend=false -lockfile=readonly
terraform -chdir=infra/terraform/drill validate
terraform -chdir=infra/terraform/drill test
actionlint .github/workflows/*.yml
git diff --check
```

  Use the existing documented local test-database setup for application/E2E
  commands; never point tests at Cloud SQL. Run the existing hosted security
  gates and image scan on the candidate branch/PR. Record unavailable tools or
  external service failures separately from passing checks.

- [x] **2. Request whole-branch review with `gpt-5.6-sol` medium.** Review against
  the revised spec, focusing on OIDC claims/permissions, exact commit/image use,
  migration success before deployment, zero-traffic behavior, exception paths,
  workflow reruns and preservation of stable Terraform attributes. Fix findings
  and rerun only affected checks. Report repository-ready and live-pending.

- [ ] **3. Learner bootstraps WIF locally; Phase 18 drift is already closed.** Inspect
  the actual plan before applying; reject unexpected replacements/deletes or
  unrelated configuration changes. Verify the numeric claims and effective
  permissions, including denied federation from a wrong branch/repository and
  successful authorized authentication. Use an isolated negative-auth probe
  that cannot run deployment; do not relax production trust for the test.

- [ ] **4. Learner enables delivery and runs a successful approved release.**
  Record run URL, commit, digest, migration execution, revision/tag, smoke results
  and final 100% traffic. Verify one built image and matching migration/API
  digests, as well as credentials surviving the build and no leaked credentials.

- [ ] **5. Learner performs the documented failure and rollback rehearsals.**
  Record candidate failure with unchanged traffic, automatic restoration after
  injected stable failure, and separate manual rollback. Verify paused delivery
  and clear pending work before operator mutations. Verify serialization and
  distinguish a superseded pending run from an active deployment cancellation.

- [ ] **6. Learner runs a final local Terraform plan and records evidence.**
  Expect no changes due to release-owned image/revision/traffic fields. If stable
  metadata drifts, investigate the specific command/provider interaction; do not
  add broad ignores to force a green result. Leave live acceptance pending until
  resolved. Update statuses only for actually observed results.

## Coverage and completion

| Spec concern | Tasks |
| --- | --- |
| Exact smoke contract and bounded propagation checks | 1, 3 |
| One WIF identity, protected environment and least privilege | 2, 4, 6 |
| Stable Terraform ownership, local prerequisites, no release drift | 2, 5, 6 |
| Single image build/test/scan/push and digest equality | 4, 6 |
| Migration ordering, candidate isolation, promotion and restoration | 3, 6 |
| Existing gates, manual iOS isolation, main-only activation and concurrency | 4, 6 |
| Short summaries, failed-stage visibility, manual recovery | 3, 4, 5, 6 |
| Honest docs and separate repository/live completion | 5, 6 |

## Implementation references

- [Reusable workflow caller context and permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)
- [Google deployment pipeline federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Google auth action inputs and credential lifetime](https://github.com/google-github-actions/auth)
- [Google setup-gcloud action](https://github.com/google-github-actions/setup-gcloud)
- [Cloud Run IAM roles](https://docs.cloud.google.com/run/docs/reference/iam/roles)
- [Cloud Run deploy flags](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy)
- [Cloud Run job execution](https://docs.cloud.google.com/sdk/gcloud/reference/run/jobs/execute)
- [Cloud Run traffic commands](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/update-traffic)
- [actionlint installation](https://github.com/rhysd/actionlint/blob/main/docs/install.md)
