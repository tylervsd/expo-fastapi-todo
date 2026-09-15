"""Phase 19 migration and traffic sequence (stdlib only).

Runs the ordered rollout: verify previous traffic, update and execute the
migration job, deploy a zero-traffic tagged candidate, smoke-test it,
promote it, and smoke-test the stable URL. A post-promotion failure
restores the previous revision once. No mutation is retried.

Runner loss or forced cancellation between mutations needs the manual
rollback runbook; only the release workflow's own steps are handled here.
"""

import json
import os
import re
import subprocess
import sys

from release_smoke import smoke

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


def _contains_image(obj, image):
    if isinstance(obj, str):
        return obj == image
    if isinstance(obj, dict):
        return any(_contains_image(v, image) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_image(v, image) for v in obj)
    return False


def _spec_image(service):
    try:
        containers = service["spec"]["template"]["spec"]["containers"]
        return containers[0].get("image")
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
    service = _req("CLOUD_SERVICE")
    job = _req("CLOUD_MIGRATION_JOB")
    registry = _req("CLOUD_IMAGE")
    release = _req("RELEASE_ID")
    commit = _req("GITHUB_SHA")
    summary_path = _req("GITHUB_STEP_SUMMARY")
    parts = image.split("@", 1)
    if len(parts) != 2 or parts[0] != registry or not _DIGEST_RE.match(parts[1]):
        raise RuntimeError("image digest does not match CLOUD_IMAGE@sha256:<64 hex>")
    for name in (service, job, previous):
        if not _NAME_RE.match(name):
            raise RuntimeError(f"invalid resource name: {name}")
    if not _RELEASE_RE.match(release):
        raise RuntimeError(f"invalid release ID: {release}")
    candidate = f"{service}-{release}"
    if len(candidate) > 63:
        raise RuntimeError(f"candidate revision name too long: {candidate}")

    execution = "not reached"
    candidate_smoke = "not reached"
    stable_smoke = "not reached"
    observed = "unknown"
    error = None
    restore_note = "not attempted"
    cleanup_note = "ok"
    promotion_attempted = False
    candidate_created = False
    stable_url = ""
    try:
        described = cloud("run", "services", "describe", service)
        if serving_revision(described) != previous:
            raise RuntimeError("previous revision is no longer serving 100%")
        stable_url = described.get("status", {}).get("url", "")
        if not stable_url:
            raise RuntimeError("service has no stable URL")
        cloud("run", "jobs", "update", job, "--image=" + image)
        executed = cloud("run", "jobs", "execute", job, "--wait")
        execution = executed.get("metadata", {}).get("name", "unknown")
        if not _completed(executed):
            raise RuntimeError(f"migration execution failed: {execution}")
        if not _contains_image(executed, image):
            raise RuntimeError("migration did not run the release digest")
        cloud(
            "run",
            "deploy",
            service,
            "--image=" + image,
            "--revision-suffix=" + release,
            "--tag=" + release,
            "--no-traffic",
        )
        candidate_created = True
        described = cloud("run", "services", "describe", service)
        if _spec_image(described) != image:
            raise RuntimeError("candidate revision image mismatch")
        if serving_revision(described) != previous:
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
                smoke(stable_url)
                restore_note = f"restored {previous}, stable smoke passed"
            except Exception as restore_exc:  # noqa: BLE001 - restore is best-effort
                restore_note = f"restore failed: {restore_exc}"
                try:
                    observed = serving_revision(
                        cloud("run", "services", "describe", service)
                    )
                except Exception:  # noqa: BLE001 - traffic may be unobservable
                    observed = "unknown"
        if restore_note.startswith("restore failed"):
            raise RuntimeError(
                f"deploy failed: {error}; {restore_note}; traffic: {observed}"
            ) from error
        raise RuntimeError(f"deploy failed: {error}") from error
    finally:
        if candidate_created:
            try:
                cloud(
                    "run",
                    "services",
                    "update-traffic",
                    service,
                    "--remove-tags=" + release,
                )
            except Exception as exc:  # noqa: BLE001 - cleanup must not raise
                cleanup_note = f"cleanup failed: {exc}"
        else:
            cleanup_note = "not needed"
        outcome = "failed" if error is not None else "success"
        _write_summary(
            summary_path,
            [
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
            ],
        )


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
