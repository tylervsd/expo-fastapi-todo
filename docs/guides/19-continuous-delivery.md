# Phase 19: Continuous delivery walkthrough

Repository changes are **ready for review**; live cloud acceptance is
**pending** (see [Acceptance record](#acceptance-record)). Nothing here runs
until the learner deliberately activates delivery. Application CI never
applies Terraform.

Spec: [Phase 19 design](../superpowers/specs/2026-09-14-continuous-delivery-design.md).
Plan: [Phase 19 implementation plan](../superpowers/plans/2026-09-14-continuous-delivery.md).

## Prerequisites

- Phase 18 label-drift verification was confirmed closed by the learner on
  2026-09-15. This activation prerequisite is satisfied.
- Local operator credentials via Application Default Credentials
  (`gcloud auth application-default login`); no downloaded service-account
  keys anywhere.
- Numeric GitHub identity for the trust condition (names alone are not
  trust anchors):

```sh
gh api repos/OWNER/REPO --jq '{id, owner: .owner.id}'
```

- Required Google APIs: IAM Credentials and Security Token Service, plus
  the existing Phase 18 set (`google_project_service.required` covers
  them; see `infra/terraform/sandbox/terraform.tfvars.example`).
- Before activation, confirm against observed cloud state: actual
  resource names, existing IAM ownership, the migration job's
  `max_retries` setting (example uses `1`; the release promises one
  execution attempt, so any required change is a reviewed local
  prerequisite, not a CI mutation), expand-first compatible migrations,
  and the retained previous revision's ability to keep running.

## Bootstrap

All Terraform work is local and reviewed. Real values stay local; never
commit them. `github_delivery` defaults to `null` (creates nothing).

1. Copy `infra/terraform/sandbox/terraform.tfvars.example` to the
   ignored local tfvars, set real values, and add a local
   `github_delivery` block (angle brackets are learner input, never
   the mock IDs from tests):

```hcl
github_delivery = {
  repository    = "<owner>/<repo>"
  repository_id = "<numeric repository id>"
  owner_id      = "<numeric owner id>"
}
```

1. Review and apply locally:

```sh
terraform -chdir=infra/terraform/sandbox init -backend-config=backend.hcl
terraform -chdir=infra/terraform/sandbox plan
terraform -chdir=infra/terraform/sandbox apply
```

Inspect the plan before applying; reject unexpected replacements,
deletes, or unrelated changes.

1. Map Terraform outputs to GitHub environment variables:

| Terraform output | GitHub `sandbox` environment variable |
| --- | --- |
| `github_workload_identity_provider` | `GCP_WIF_PROVIDER` |
| `github_deploy_service_account` | `GCP_DEPLOY_SERVICE_ACCOUNT` |

Non-secret variable table (all `sandbox` environment variables except
the repository variable):

| Variable | Meaning |
| --- | --- |
| `CLOUD_PROJECT` | Sandbox project ID |
| `CLOUD_REGION` | Sandbox region |
| `CLOUD_SERVICE` | Cloud Run API service name |
| `CLOUD_MIGRATION_JOB` | Cloud Run migration job name |
| `CLOUD_IMAGE` | Full registry image path, no tag |
| `GCP_WIF_PROVIDER` | Full WIF provider name from Terraform |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Deploy service-account email from Terraform |

`DELIVERY_ENABLED` is a repository variable, not an environment
variable. Verify federation restrictions (numeric repository and owner
IDs, `refs/heads/main`, exact release workflow ref, `sandbox`
environment subject) and effective permissions during rehearsal,
including a denied-auth probe from a wrong branch or repository
context that cannot run a deployment.

## Activate delivery

1. Protect `main` and inspect the reusable check names (quality,
   security, web) before updating required checks.
1. Configure the `sandbox` environment: required reviewers and
   main-only deployments. Verify the account and repository support
   those environment controls.
1. Keep `DELIVERY_ENABLED=false` until ready. Validation gates still
   run while delivery is disabled and report that nothing was
   deployed; pending releases may be superseded (newer pending runs
   replace older ones — this is not an every-commit queue).
1. First activation uses a manual run from `main`:

```sh
gh workflow run release.yml --ref main
```

1. Approve the `sandbox` environment prompt, then confirm one
   tested/scanned image, matching migration and API digests, and
   migration completion before candidate deployment.

## Pause delivery

Setting the variable alone does not stop already queued or approved
work. Inspect run IDs first; never cancel an active mutation just to
free the `sandbox-release` lock — let it finish or fail, and cancel
only identified pending runs.

```sh
gh variable set DELIVERY_ENABLED --body false
gh workflow disable release.yml
gh run list --workflow release.yml
# Wait for active deployment to finish; cancel only identified pending runs.
```

Use this same pause process before local Cloud Run infrastructure
changes, and resume delivery only after verifying the infrastructure
change. Re-enable deliberately afterward:

```sh
gh workflow enable release.yml
gh variable set DELIVERY_ENABLED --body true
```

## Manual rollback

Operator uses existing authorized access (never impersonates GitHub,
never weakens the `sandbox` approval boundary). Delivery must be
paused (above) with pending work cleared before any operator
mutation. `PREVIOUS_REVISION` comes from the release summary.

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

Extract the returned tag URL from observed service status (never
guess hostnames). Precheck that revision before cutover:

```sh
python3 scripts/release_smoke.py "$ROLLBACK_URL"
```

A failed precheck stops the procedure for investigation. On success:

```sh
gcloud run services update-traffic "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --to-revisions="$PREVIOUS_REVISION=100"
python3 scripts/release_smoke.py "$STABLE_URL"
gcloud run services update-traffic "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --remove-tags=manual-rollback
```

Rules: confirm the revision belongs to the expected sandbox service
and currently serves 100% only after cutover; check migration
compatibility (the expanded database stays — never downgrade it).
Rollback never builds or pushes images, applies Terraform, runs
migrations, or selects an arbitrary historical revision — only the
recorded previous revision. A failed rollback smoke requires
operator investigation and must be recorded as a failure, never as
recovered. Keep delivery paused until the failed release is fixed,
then re-enable deliberately.

## Acceptance record

Live acceptance is **pending**. The learner records evidence here;
local tests alone do not establish it.

| Check | Result |
| --- | --- |
| Local identity bootstrap, environment protection, denied federation probe | pending |
| Approved release: one image, matching migration/API digests, migration first | pending |
| Zero-traffic candidate smoke, promotion, stable smoke, clean summary | pending |
| Candidate failure leaves traffic unchanged | pending |
| Post-promotion failure restores and verifies previous revision | pending |
| Manual rollback with paused delivery and cleared pending work | pending |
| Serialized mutations, safe reruns, superseded pending run | pending |
| Final local Terraform plan: no drift from release-owned fields | pending |

Rehearsal instructions (delivery paused throughout; `$CLOUD_*`
from the [Bootstrap](#bootstrap) table, same verified digest from
the release summary, and a new rehearsal release ID built as
`RELEASE_ID="r$(date +%s)-a1-$(git rev-parse --short=8 HEAD)"`):

1. Candidate failure. Deploy the digest with zero traffic under a
   temporary tag, prove the bad path fails, prove traffic never
   moved, then clean the tag:

```sh
REHEARSAL_TAG="rehearse-candidate-<short-sha>"
gcloud run deploy "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --image="<verified-digest>" \
  --revision-suffix="$REHEARSAL_TAG" --tag="$REHEARSAL_TAG" --no-traffic
gcloud run services describe "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --format=json > /tmp/rehearsal-service.json
CANDIDATE_URL=$(python3 -c "import json;svc=json.load(open('/tmp/rehearsal-service.json'));print([t['url'] for t in svc['status']['traffic'] if t.get('tag')=='$REHEARSAL_TAG'][0])")
# The smoke script strips any URL path before probing, so a bad path
# cannot induce failure. Use an unroutable loopback URL instead:
# connection-refused is deterministic and fully offline.
if python3 scripts/release_smoke.py "http://127.0.0.1:9"; then
  echo "rehearsal invalid: smoke unexpectedly passed"; exit 1
fi
echo "candidate smoke failed as rehearsed"
gcloud run services describe "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --format='value(status.traffic)'
# Confirm the previous revision still holds 100% before cleanup.
gcloud run services update-traffic "$CLOUD_SERVICE" \
  --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
  --remove-tags="$REHEARSAL_TAG"
```

   The loopback failure proves the smoke contract can fail. The
candidate tag URL (extracted above) confirms the candidate
exists with zero traffic, and the traffic output
must still show the previous revision at 100%. Record the result.

1. Post-promotion restore. Run the real rollout function locally
   with only its second smoke call forced to fail; the candidate
   and restored-revision calls delegate to the real
   `release_smoke.smoke`. The learner must approve this deliberate
   live promotion/restore cycle — there is no production
   failure-injection flag:

```python
import os
from unittest.mock import patch
import release_deploy
import release_smoke

# Build the rehearsal ID in the shell first (matches ^r\d+-a\d+-[0-9a-f]{8}$).
# Invoke as: RELEASE_ID="r$(date +%s)-a1-$(git rev-parse --short=8 HEAD)" PYTHONPATH=scripts python3 <wrapper>.py
os.environ["RELEASE_ID"]  # KeyError if unset — invoke as above
os.environ["GITHUB_STEP_SUMMARY"] = os.environ.get(
    "GITHUB_STEP_SUMMARY", "/tmp/rehearsal-summary.md")
real_smoke = release_smoke.smoke
calls = []

def fail_second(url):
    calls.append(url)
    if len(calls) == 2:
        raise RuntimeError("rehearsed stable-smoke failure")
    return real_smoke(url)

with patch.object(release_deploy, "smoke", side_effect=fail_second):
    try:
        release_deploy.deploy("<verified-digest>", "<previous-revision>")
    except RuntimeError as exc:
        print("release failed as rehearsed:", exc)
```

   Run from the worktree root with the `CLOUD_*`/`GITHUB_SHA`
   environment set:

```sh
RELEASE_ID="r$(date +%s)-a1-$(git rev-parse --short=8 HEAD)" PYTHONPATH=scripts python3 <wrapper>.py
```

Expect the release to raise, traffic restored to the previous
revision, and the stable URL re-verified; the wrapper prints the
rehearsed failure. Record run output and final traffic.

1. A separate normal successful release and a separate manual
   rollback must also pass before sign-off.

## Recovery

Decide from observed cloud state before each operation:

- Migration failure: candidate is never deployed; fix the migration
  (expand-first, compatible with the old revision), rerun as a new
  serialized release.
- Missing candidate tag URL: stop, inspect service status, clean the
  temporary tag; traffic was never moved.
- Failed automatic restore: hard failure needing learner action —
  the workflow reports desired and observed traffic; recover via
  [Manual rollback](#manual-rollback).
- Expired credentials: re-authenticate locally (ADC) or re-approve a
  new release; never relax production trust for the test.
- Runner loss or forced cancellation mid-mutation: read observed
  service, job, and traffic state first, then follow
  [Manual rollback](#manual-rollback); a rerun rediscovers current
  traffic and Alembic applies only pending migrations.
