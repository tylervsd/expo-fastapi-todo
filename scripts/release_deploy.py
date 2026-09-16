"""Phase 19 migration and traffic sequence (stdlib only).

Runs the ordered rollout: verify previous traffic, update and execute the
migration job, deploy a zero-traffic tagged candidate, smoke-test it,
promote it, and smoke-test the stable URL. A post-promotion failure
restores the previous revision once. No mutation is retried.

Phase 20 extends this sequence to an optional private suggestion worker
(`CLOUD_WORKER_SERVICE`). When set, the same digest rolls the worker first
(candidate/readiness, promotion/readiness) and only then the API; any later
failure restores attempted promotions API-first, then worker, collecting
both errors. Absence preserves the Phase 19 single-service behavior.

ponytail: extend the existing release directly, no generic deployment
engine. The queue keeps running during normal compatible releases, and
completed provider work cannot be rolled back by restoring traffic.

Runner loss or forced cancellation between mutations needs the manual
rollback runbook; only the release workflow's own steps are handled here.
"""

import json
import os
import re
import subprocess
import sys

from release_smoke import smoke, smoke_worker

TIMEOUT = 300
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_RELEASE_RE = re.compile(r"^r\d+-a\d+-[0-9a-f]{8}$")


def _req(name):
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"missing required environment: {name}")
    return value


def cloud(*args: str) -> dict:
    """Run gcloud with project/region/JSON flags; return parsed JSON."""
    project = _req("CLOUD_PROJECT")
    region = _req("CLOUD_REGION")
    cmd = [
        "gcloud",
        *args,
        f"--project={project}",
        f"--region={region}",
        "--quiet",
        "--format=json",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gcloud {' '.join(args[:3])} timed out") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip()[:200]
        raise RuntimeError(f"gcloud {' '.join(args[:3])} failed: {detail}")
    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except ValueError as exc:
        raise RuntimeError("gcloud returned invalid JSON") from exc


def serving_revision(service: dict) -> str:
    """Return the single revision serving 100%; fail on split/empty."""
    try:
        traffic = service["status"]["traffic"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("service has no observed traffic") from exc
    active = [t for t in traffic if (t.get("percent") or 0) > 0]
    if (
        len(active) != 1
        or active[0].get("percent") != 100
        or not active[0].get("revisionName")
    ):
        raise RuntimeError("ambiguous service traffic: expected one revision at 100%")
    return active[0]["revisionName"]


def _completed(execution):
    conditions = execution.get("status", {}).get("conditions", [])
    return any(
        c.get("status") == "True" and c.get("type") in ("Completed", "Succeeded")
        for c in conditions
    )


def _execution_image(execution):
    """Return the executed job container image, or None."""
    try:
        containers = execution["spec"]["template"]["spec"]["containers"]
        return containers[0].get("image")
    except (KeyError, TypeError, IndexError):
        return None


def _revision_image(revision, candidate):
    """Return candidate revision image; fail if identity is wrong."""
    name = revision.get("metadata", {}).get("name")
    if name != candidate:
        raise RuntimeError(f"candidate revision not found: {candidate}")
    try:
        return revision["spec"]["containers"][0].get("image")
    except (KeyError, TypeError, IndexError):
        return None


def _tag_url(service, tag, revision):
    try:
        traffic = service["status"]["traffic"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("service has no observed traffic") from exc
    for entry in traffic:
        if entry.get("tag") == tag and entry.get("revisionName") == revision:
            if entry.get("url"):
                return entry["url"]
            raise RuntimeError(f"candidate tag {tag} has no URL")
    raise RuntimeError(f"candidate tag {tag} not found")


def _write_summary(path, rows):
    with open(path, "a") as handle:
        handle.write("## Release\n")
        handle.writelines(f"- {key}: {value}\n" for key, value in rows)


def deploy(image: str, previous: str) -> None:
    """Run the migration, candidate, promotion, and restoration sequence."""
    summary_path = _req("GITHUB_STEP_SUMMARY")
    execution = "not reached"
    candidate = "not reached"
    candidate_smoke = "not reached"
    stable_smoke = "not reached"
    observed = "unknown"
    error = None
    restore_note = "not attempted"
    cleanup_note = "ok"
    promotion_attempted = False
    candidate_created = False
    stable_url = ""
    worker_previous = "not reached"
    worker_candidate = "not reached"
    worker_candidate_smoke = "not reached"
    worker_stable_smoke = "not reached"
    worker_observed = "unknown"
    worker_restore_note = "not attempted"
    worker_promotion_attempted = False
    worker_candidate_created = False
    worker_stable_url = ""
    restore_failed = False
    commit = os.environ.get("GITHUB_SHA", "unknown")
    worker_service = ""
    invoker = ""
    try:
        service = _req("CLOUD_SERVICE")
        job = _req("CLOUD_MIGRATION_JOB")
        registry = _req("CLOUD_IMAGE")
        release = _req("RELEASE_ID")
        commit = _req("GITHUB_SHA")
        parts = image.split("@", 1)
        if len(parts) != 2 or parts[0] != registry or not _DIGEST_RE.match(parts[1]):
            raise RuntimeError(
                "image digest does not match CLOUD_IMAGE@sha256:<64 hex>"
            )
        for name in (service, job, previous):
            if not _NAME_RE.match(name):
                raise RuntimeError(f"invalid resource name: {name}")
        if not _RELEASE_RE.match(release):
            raise RuntimeError(f"invalid release ID: {release}")
        worker_service = os.environ.get("CLOUD_WORKER_SERVICE", "")
        invoker = os.environ.get("CLOUD_TASK_INVOKER_SERVICE_ACCOUNT", "")
        if worker_service:
            if not _NAME_RE.match(worker_service):
                raise RuntimeError(
                    f"invalid resource name: {worker_service}"
                )
            if not invoker:
                raise RuntimeError(
                    "missing required environment: "
                    "CLOUD_TASK_INVOKER_SERVICE_ACCOUNT"
                )
            worker_candidate = f"{worker_service}-{release}"
            if len(worker_candidate) > 63:
                raise RuntimeError(
                    f"candidate revision name too long: {worker_candidate}"
                )
        candidate = f"{service}-{release}"
        if len(candidate) > 63:
            raise RuntimeError(f"candidate revision name too long: {candidate}")
        described = cloud("run", "services", "describe", service)
        observed = serving_revision(described)
        if observed != previous:
            raise RuntimeError("previous revision is no longer serving 100%")
        stable_url = described.get("status", {}).get("url", "")
        if not stable_url:
            raise RuntimeError("service has no stable URL")
        if worker_service:
            worker_described = cloud(
                "run", "services", "describe", worker_service
            )
            worker_observed = serving_revision(worker_described)
            worker_previous = worker_observed
            worker_stable_url = worker_described.get("status", {}).get("url", "")
            if not worker_stable_url:
                raise RuntimeError("worker service has no stable URL")
        cloud("run", "jobs", "update", job, "--image=" + image)
        executed = cloud("run", "jobs", "execute", job, "--wait")
        execution = executed.get("metadata", {}).get("name", "unknown")
        if not _completed(executed):
            raise RuntimeError(f"migration execution failed: {execution}")
        if _execution_image(executed) != image:
            raise RuntimeError("migration did not run the release digest")
        if worker_service:
            worker_candidate_created = True
            cloud(
                "run",
                "deploy",
                worker_service,
                "--image=" + image,
                "--revision-suffix=" + release,
                "--tag=" + release,
                "--no-traffic",
            )
            worker_revision = cloud(
                "run", "revisions", "describe", worker_candidate
            )
            if _revision_image(worker_revision, worker_candidate) != image:
                raise RuntimeError("worker candidate revision image mismatch")
            worker_described = cloud(
                "run", "services", "describe", worker_service
            )
            worker_observed = serving_revision(worker_described)
            if worker_observed != worker_previous:
                raise RuntimeError("worker traffic moved before candidate smoke")
            worker_tag_url = _tag_url(
                worker_described, release, worker_candidate
            )
            try:
                smoke_worker(worker_tag_url, worker_stable_url, invoker)
                worker_candidate_smoke = "passed"
            except (RuntimeError, ValueError) as exc:
                worker_candidate_smoke = f"failed: {exc}"
                raise RuntimeError(
                    f"worker candidate smoke failed: {exc}"
                ) from exc
            worker_promotion_attempted = True
            cloud(
                "run",
                "services",
                "update-traffic",
                worker_service,
                "--to-revisions=" + worker_candidate + "=100",
            )
            worker_described = cloud(
                "run", "services", "describe", worker_service
            )
            worker_observed = serving_revision(worker_described)
            if worker_observed != worker_candidate:
                raise RuntimeError(
                    "worker promotion unverified: "
                    f"traffic on {worker_observed}"
                )
            try:
                smoke_worker(worker_stable_url, worker_stable_url, invoker)
                worker_stable_smoke = "passed"
            except (RuntimeError, ValueError) as exc:
                worker_stable_smoke = f"failed: {exc}"
                raise RuntimeError(
                    f"worker stable smoke failed: {exc}"
                ) from exc
        candidate_created = True
        cloud(
            "run",
            "deploy",
            service,
            "--image=" + image,
            "--revision-suffix=" + release,
            "--tag=" + release,
            "--no-traffic",
        )
        revision = cloud("run", "revisions", "describe", candidate)
        if _revision_image(revision, candidate) != image:
            raise RuntimeError("candidate revision image mismatch")
        described = cloud("run", "services", "describe", service)
        observed = serving_revision(described)
        if observed != previous:
            raise RuntimeError("traffic moved before candidate smoke")
        tag_url = _tag_url(described, release, candidate)
        try:
            smoke(tag_url)
            candidate_smoke = "passed"
        except (RuntimeError, ValueError) as exc:
            candidate_smoke = f"failed: {exc}"
            raise RuntimeError(f"candidate smoke failed: {exc}") from exc
        promotion_attempted = True
        cloud(
            "run",
            "services",
            "update-traffic",
            service,
            "--to-revisions=" + candidate + "=100",
        )
        described = cloud("run", "services", "describe", service)
        observed = serving_revision(described)
        if observed != candidate:
            raise RuntimeError(f"promotion unverified: traffic on {observed}")
        try:
            smoke(stable_url)
            stable_smoke = "passed"
        except (RuntimeError, ValueError) as exc:
            stable_smoke = f"failed: {exc}"
            raise RuntimeError(f"stable smoke failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - summary must record any failure
        error = exc
        if promotion_attempted:
            try:
                cloud(
                    "run",
                    "services",
                    "update-traffic",
                    service,
                    "--to-revisions=" + previous + "=100",
                )
                described = cloud("run", "services", "describe", service)
                observed = serving_revision(described)
                if observed != previous:
                    raise RuntimeError(f"restore unverified: traffic on {observed}")
                smoke(stable_url)
                restore_note = f"restored {previous}, stable smoke passed"
            except Exception as restore_exc:  # noqa: BLE001 - restore is best-effort
                restore_note = f"restore failed: {restore_exc}"
                restore_failed = True
                try:
                    observed = serving_revision(
                        cloud("run", "services", "describe", service)
                    )
                except Exception:  # noqa: BLE001 - traffic may be unobservable
                    observed = "unknown"
        if worker_promotion_attempted:
            try:
                cloud(
                    "run",
                    "services",
                    "update-traffic",
                    worker_service,
                    "--to-revisions=" + worker_previous + "=100",
                )
                worker_described = cloud(
                    "run", "services", "describe", worker_service
                )
                worker_observed = serving_revision(worker_described)
                if worker_observed != worker_previous:
                    raise RuntimeError(
                        f"restore unverified: traffic on {worker_observed}"
                    )
                smoke_worker(worker_stable_url, worker_stable_url, invoker)
                worker_restore_note = (
                    f"restored {worker_previous}, stable smoke passed"
                )
            except Exception as restore_exc:  # noqa: BLE001 - restore all attempted
                worker_restore_note = f"restore failed: {restore_exc}"
                restore_failed = True
                try:
                    worker_observed = serving_revision(
                        cloud("run", "services", "describe", worker_service)
                    )
                except Exception:  # noqa: BLE001 - traffic may be unobservable
                    worker_observed = "unknown"
        if restore_failed:
            raise RuntimeError(
                f"deploy failed: {error}; api {restore_note}; "
                f"worker {worker_restore_note}; api traffic: {observed}; "
                f"worker traffic: {worker_observed}"
                if worker_service
                else f"deploy failed: {error}; {restore_note}; "
                f"traffic: {observed}"
            ) from error
        raise RuntimeError(f"deploy failed: {error}") from error
    finally:
        tagged = []
        if candidate_created:
            tagged.append(service)
        if worker_candidate_created:
            tagged.append(worker_service)
        for tag_service in tagged:
            try:
                cloud(
                    "run",
                    "services",
                    "update-traffic",
                    tag_service,
                    "--remove-tags=" + release,
                )
            except Exception as exc:  # noqa: BLE001 - cleanup must not raise
                cleanup_note = f"cleanup failed: {exc}"
        if not tagged:
            cleanup_note = "not needed"
        outcome = "failed" if error is not None else "success"
        rows = [
            ("outcome", outcome),
            ("commit", commit),
            ("image", image),
            ("migration execution", execution),
            ("previous revision", previous),
            ("candidate revision", candidate),
            ("candidate smoke", candidate_smoke),
            ("stable smoke", stable_smoke),
            ("restore", restore_note),
            ("traffic", observed),
            ("cleanup", cleanup_note),
        ]
        if worker_service:
            rows.extend([
                ("worker service", worker_service),
                ("worker invoker", invoker),
                ("worker previous revision", worker_previous),
                ("worker candidate revision", worker_candidate),
                ("worker candidate smoke", worker_candidate_smoke),
                ("worker stable smoke", worker_stable_smoke),
                ("worker restore", worker_restore_note),
                ("worker traffic", worker_observed),
            ])
        _write_summary(summary_path, rows)


def main(argv):
    if len(argv) != 2:
        print("usage: release_deploy.py IMAGE_DIGEST PREVIOUS_REVISION", file=sys.stderr)
        return 2
    try:
        deploy(argv[0], argv[1])
    except RuntimeError as exc:
        print(f"deploy failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
