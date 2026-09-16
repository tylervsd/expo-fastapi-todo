"""Concrete Cloud Tasks adapter for durable suggestion delivery.

Ponytail only: this is the single Cloud Tasks enqueue path, not a generic
queue framework. Configuration is validated once at application startup via
`read_cloud_config`; the public route commits its reservation before calling
`enqueue_suggestion`, never inside a database transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from google.api_core.exceptions import AlreadyExists
from google.cloud import tasks_v2
from google.protobuf import duration_pb2

TASK_VERSION = 1
MAX_TASK_BODY_BYTES = 1024

# Synchronous Cloud Tasks RPC bound: the public route runs this off the
# request event loop in the framework threadpool helper.
CREATE_TASK_TIMEOUT_SECONDS = 5.0

# Upper bound Tasks waits for one delivery attempt before retrying; the
# worker's own provider deadline is smaller (30s) so attempts stay useful.
TASK_DISPATCH_DEADLINE_SECONDS = 60

TASK_NAME_PREFIX = "suggest-v1-"


class EnqueueUnavailable(RuntimeError):
    """Sanitized transport failure: the reservation stays saved for retry."""


@dataclass(frozen=True)
class CloudTasksConfig:
    project: str
    location: str
    queue: str
    worker_url: str
    invoker_email: str


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def _canonical_worker_url(value: object) -> str:
    raw = _require_nonempty(value, name="SUGGESTION_WORKER_URL").rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme != "https":
        raise ValueError("SUGGESTION_WORKER_URL must use https")
    hostname = parsed.hostname or ""
    if not hostname.endswith(".run.app"):
        raise ValueError("SUGGESTION_WORKER_URL must be a canonical run.app origin")
    if (
        parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.port is not None
    ):
        raise ValueError("SUGGESTION_WORKER_URL must be a bare https origin")
    return f"https://{hostname}"


def read_cloud_config(env: Mapping[str, str] | None = None) -> CloudTasksConfig:
    """Parse and validate cloud enqueue configuration once at startup.

    Raises ValueError on any missing or malformed value so cloud mode fails
    startup instead of falling back to inline or failing per request. No
    request-supplied routing is accepted here.
    """
    source = env if env is not None else os.environ
    return CloudTasksConfig(
        project=_require_nonempty(
            source.get("GOOGLE_CLOUD_PROJECT"), name="GOOGLE_CLOUD_PROJECT"
        ),
        location=_require_nonempty(
            source.get("CLOUD_TASKS_LOCATION"), name="CLOUD_TASKS_LOCATION"
        ),
        queue=_require_nonempty(source.get("CLOUD_TASKS_QUEUE"), name="CLOUD_TASKS_QUEUE"),
        worker_url=_canonical_worker_url(source.get("SUGGESTION_WORKER_URL")),
        invoker_email=_require_nonempty(
            source.get("TASK_INVOKER_SERVICE_ACCOUNT"),
            name="TASK_INVOKER_SERVICE_ACCOUNT",
        ),
    )


def task_name_for(suggestion_id: int, fingerprint: str) -> str:
    """Deterministic task ID: stable across retries for one reservation row."""
    digest = hashlib.sha256(f"{suggestion_id}:{fingerprint}".encode()).hexdigest()
    return f"{TASK_NAME_PREFIX}{digest}"


def _require_task_identity(suggestion_id: object, fingerprint: object) -> None:
    if (
        isinstance(suggestion_id, bool)
        or not isinstance(suggestion_id, int)
        or suggestion_id <= 0
    ):
        raise EnqueueUnavailable("suggestion enqueue is unavailable")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(
            character not in "0123456789abcdef" for character in fingerprint
        )
    ):
        raise EnqueueUnavailable("suggestion enqueue is unavailable")


def enqueue_suggestion(suggestion_id: int, fingerprint: str) -> None:
    """Create (or deduplicate) the delivery task for a committed reservation.

    Only `AlreadyExists` is accepted as duplicate success; every other
    failure raises sanitized `EnqueueUnavailable`. Never logs the credential
    or the task body.
    """
    _require_task_identity(suggestion_id, fingerprint)
    try:
        config = read_cloud_config()
    except ValueError as exc:
        raise EnqueueUnavailable("suggestion enqueue is unavailable") from exc
    body = json.dumps({"version": TASK_VERSION, "suggestion_id": suggestion_id}).encode()
    if len(body) > MAX_TASK_BODY_BYTES:
        raise EnqueueUnavailable("suggestion enqueue is unavailable")
    parent = (
        f"projects/{config.project}"
        f"/locations/{config.location}"
        f"/queues/{config.queue}"
    )
    task = tasks_v2.Task(
        name=f"{parent}/tasks/{task_name_for(suggestion_id, fingerprint)}",
        http_request=tasks_v2.HttpRequest(
            http_method=tasks_v2.HttpMethod.POST,
            url=f"{config.worker_url}/internal/suggestions",
            headers={"Content-Type": "application/json"},
            body=body,
            oidc_token=tasks_v2.OidcToken(
                service_account_email=config.invoker_email,
                audience=config.worker_url,
            ),
        ),
        dispatch_deadline=duration_pb2.Duration(
            seconds=TASK_DISPATCH_DEADLINE_SECONDS
        ),
    )
    try:
        # ADC only, never key files. retry=None disables implicit SDK
        # retries so at-most-once creation keeps the lost-response path
        # repairable through deterministic-name deduplication.
        client = tasks_v2.CloudTasksClient()
        client.create_task(
            request={"parent": parent, "task": task},
            retry=None,
            timeout=CREATE_TASK_TIMEOUT_SECONDS,
        )
    except AlreadyExists:
        return
    except EnqueueUnavailable:
        raise
    except Exception as exc:
        raise EnqueueUnavailable("suggestion enqueue is unavailable") from exc
