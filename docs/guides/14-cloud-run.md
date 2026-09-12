# Phase 14: Containers, Artifact Registry, and Cloud Run

## Outcome

The learner reports that the manual Phase 14 walkthrough worked, including
local container checks, Artifact Registry publishing, Cloud Run deployment,
and the revision promotion/rollback exercise. This record is based on that
confirmation and the repository files; the assistant did not independently
rerun the deployment or inspect the cloud environment.

The deployed acceptance target is `GET /health`, returning
`{"status":"ok"}`. Database-backed todo features are outside this phase;
Cloud SQL integration belongs to Phase 16. Phase 13 cloud foundations were
completed manually before this exercise.

## Container configuration

The implementation is in [Dockerfile](../../apps/api/Dockerfile) and
[.dockerignore](../../apps/api/.dockerignore), on branch
`codex/phase-14-cloud-run`.

| Setting | Value in the implementation |
| --- | --- |
| Python base | `python:3.14.7-slim-bookworm` |
| Dependency tool | `ghcr.io/astral-sh/uv:0.12.1` |
| Dependency installation | `uv sync --locked --no-dev --no-install-project` using `apps/api/uv.lock` |
| Runtime identity | UID/GID `10001:10001` |
| Application | `app.main:app` |
| Bind address | `0.0.0.0` |
| Port | Runtime `PORT`, default `8080` |
| Shutdown handling | Shell uses `exec` to make Uvicorn the main process |
| Build platform | `linux/amd64`, as specified in the walkthrough |

The build context allowlist includes dependency metadata and application source,
excluding local environment files, virtual environments, and the E2E harness.
The application creates its SQLAlchemy engine at startup without immediately
opening a database connection, allowing the health endpoint to run without
PostgreSQL. Health success does not establish database readiness.

## Manual execution

Run commands from the Phase 14 worktree. Cloud commands require the learner's
Phase 13 project/account configuration. Keep project IDs, region, repository,
and service names explicit through the terminal variables used below.
Do not store access tokens, credential files, or private keys in this guide.

### Build and local checks

```sh
docker buildx build --platform linux/amd64 --load \
  --tag fullstack-api:phase14 apps/api

docker image inspect fullstack-api:phase14 \
  --format='architecture={{.Architecture}} user={{.Config.User}}'

docker run --detach --name fullstack-api-phase14 \
  --platform linux/amd64 --publish 127.0.0.1:8080:8080 \
  --env PORT=8080 fullstack-api:phase14

docker logs fullstack-api-phase14
curl --fail --show-error http://127.0.0.1:8080/health
docker exec fullstack-api-phase14 id

docker stop fullstack-api-phase14
docker rm fullstack-api-phase14
```

Repeat with `PORT=9090`, port mapping `127.0.0.1:9090:9090`, and the matching
health URL to prove that the startup command honors the runtime port.
Stop and remove the local test container afterward.

### Registry and deployment

The walkthrough creates a Docker Artifact Registry repository, configures
Docker authentication for its regional hostname, tags the local image as
`phase14-v1`, and pushes it. The deployment uses the resolved immutable digest.

```sh
export CLOUD_IMAGE="${CLOUD_REGION}-docker.pkg.dev/${CLOUD_PROJECT}/${CLOUD_REPOSITORY}/api"

docker tag fullstack-api:phase14 "$CLOUD_IMAGE:phase14-v1"
docker push "$CLOUD_IMAGE:phase14-v1"

export CLOUD_DIGEST="$(
  gcloud artifacts docker images describe "$CLOUD_IMAGE:phase14-v1" \
    --project="$CLOUD_PROJECT" --format='value(image_summary.digest)'
)"
export CLOUD_IMAGE_REF="${CLOUD_IMAGE}@${CLOUD_DIGEST}"
```

Inspect the image's vulnerability scan before deployment. Pending scans and
unreported findings must not be treated as a clean scan.

The walkthrough uses a dedicated runtime service account without additional
project roles or a downloaded key. Its deployment settings are:

| Setting | Walkthrough value |
| --- | --- |
| Service name | `fullstack-api` |
| Repository | `fullstack-images` |
| Region | `us-west1` example; actual selection not recorded |
| CPU / memory | 1 CPU / 512 MiB |
| Concurrency / timeout | 20 requests / 30 seconds |
| Service minimum / maximum instances | 0 / 1 |
| CPU allocation | Request-based (`--cpu-throttling`) |
| Ingress / invocation | Public ingress, invoker IAM check disabled |
| Initial revision suffix | `phase14-v1` |

These are the supplied settings, not an independently retrieved cloud inventory.
Public invocation applies to all application routes; existing application
authentication still applies. No production credentials or database connection
were supplied. Instance limits are not a monetary spending cap.

### Health, scaling, and revisions

Retrieve the service URL and verify the deployed response:

```sh
export CLOUD_URL="$(
  gcloud run services describe "$CLOUD_SERVICE" \
    --project="$CLOUD_PROJECT" --region="$CLOUD_REGION" \
    --format='value(status.url)'
)"
curl --fail --show-error "$CLOUD_URL/health"
```

For the cold-request exercise, stop requests, observe instance count dropping
to zero in Cloud Run metrics, and compare the next request with a subsequent
request. Minimum instances of zero permits autoscaling to zero; it does not
force immediate termination. Request timing alone does not establish a cold
start. No measured latency values were supplied for this record.

The second revision reuses the same image with
`PHASE14_REVISION=two`, suffix `phase14-v2`, `--no-traffic`, and tag `candidate`.
Inspect `status.traffic`, test the candidate tag's health URL, promote the
second revision to 100%, then roll back to the first revision and retest the
normal service URL. Tagged requests still execute the candidate and can incur
usage even while its normal traffic allocation is zero.

## Acceptance record

| Check | Recorded result | Evidence boundary |
| --- | --- | --- |
| Build `linux/amd64` image | Passed, learner-reported | Dockerfile inspected; build output not retained here |
| Non-root runtime user | Passed, learner-reported | Dockerfile specifies UID/GID `10001:10001` |
| Local health on ports 8080 and 9090 | Passed, learner-reported | No response transcript supplied |
| Push to Artifact Registry | Passed | Learner screenshot shows `phase14-v1` and registry digests |
| Initial vulnerability scan review | Walkthrough completed, learner-reported | Screenshot shows 109 findings; severity, fixes, and disposition not supplied |
| Public Cloud Run health | Passed, learner-reported | Exact URL and response transcript not supplied |
| Scale-to-zero / cold-request exercise | Passed, learner-reported | Metrics and timing values not supplied |
| Candidate with no normal traffic | Passed, learner-reported | Exact revision inventory not supplied |
| Promotion and rollback | Passed, learner-reported | Final traffic allocation not independently inspected |
| Resource retention or deletion | Not recorded | Cleanup is a separate step after this documentation task |

The provided Artifact Registry screenshot shows a tagged digest prefix
`2a416823f093` and an untagged digest prefix `65d3bf6555ec` with virtual size
82.3 MB. Both rows display 109 findings. The likely relationship is an image
index referencing a platform image; this was explained to the learner but
manifest inspection output was not supplied. Do not sum the two displayed
counts or infer that either row is an unused duplicate.

To inspect that relationship:

```sh
docker buildx imagetools inspect "$CLOUD_IMAGE:phase14-v1"
```

## Details still needed for a reproducible deployment record

The following were not supplied and are deliberately not inferred:

- Execution date and actual Docker, Buildx, and gcloud versions.
- Actual project ID, region, service name, runtime service-account email, and URL.
- Full deployed image digest and the final revision/traffic allocation.
- Scan severity breakdown, available fixes, and disposition of unresolved findings.
- Whether resources remain deployed or were deleted after the exercise.

The walkthrough is reported successful; this does not mean the image had zero
vulnerabilities or that a production-ready application was deployed.

## Cleanup

Retain the project and budget from Phase 13 for later phases. If removing this
exercise's resources, verify the names before deleting the Cloud Run service,
dedicated image repository, and dedicated runtime service account. Repository
deletion removes every image in that repository. Record whether each resource
was retained or deleted; do not infer cleanup from a zero-instance metric.

## References

- [Curriculum roadmap](../curriculum-roadmap.md)
- [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/)
- [Cloud Run container contract](https://docs.cloud.google.com/run/docs/container-contract)
- [Cloud Run deployment](https://docs.cloud.google.com/run/docs/deploying)
- [Cloud Run autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling)
- [Artifact Registry image management](https://cloud.google.com/artifact-registry/docs/docker/manage-images)
- [Docker image index inspection](https://docs.docker.com/reference/cli/docker/buildx/imagetools/inspect/)
