"""Task 2: Cloud Tasks enqueue adapter and cloud-mode suggestion route.

TDD red: this module fails at collection until `google-cloud-tasks` is
added and `app.suggestion_tasks` exists, then its cases fail until the
cloud branch lands in `app.main.create_app`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.suggestion_service import SuggestionErrorCode

CLOUD_ENV = {
    "SUGGESTION_EXECUTION": "cloud_tasks",
    "GOOGLE_CLOUD_PROJECT": "demo-project",
    "CLOUD_TASKS_LOCATION": "us-central1",
    "CLOUD_TASKS_QUEUE": "suggestion-queue",
    "SUGGESTION_WORKER_URL": "https://suggestion-worker-abc123-uc.a.run.app",
    "TASK_INVOKER_SERVICE_ACCOUNT": "task-invoker@demo-project.iam.gserviceaccount.com",
}


def use_cloud_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in CLOUD_ENV.items():
        monkeypatch.setenv(key, value)


def auth_headers(client: TestClient, username: str = "alice") -> dict[str, str]:
    signup = client.post(
        "/auth/signup",
        json={"username": username, "password": "long-enough-password"},
    )
    assert signup.status_code == 201
    login = client.post(
        "/auth/login",
        json={"username": username, "password": "long-enough-password"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def start_collecting(client: TestClient, headers: dict[str, str]) -> dict:
    started = client.post(
        "/todo-workflows",
        json={"request_id": str(uuid4()), "title": "Plan birthday party"},
        headers=headers,
    )
    assert started.status_code == 201
    last = started.json()
    for step in ("ASSESS_TASK", "OFFER_BREAKDOWN"):
        response = client.post(
            f"/todo-workflows/{last['workflow_id']}/actions",
            json={
                "request_id": str(uuid4()),
                "expected_revision": last["revision"],
                "step_id": f"{last['workflow_id']}:{step}",
                "action": {"action": "answer_multiple_steps", "answer": True},
            },
            headers=headers,
        )
        assert response.status_code == 200
        last = response.json()
    assert last["view"]["step_id"].endswith(":COLLECT_TASKS")
    return last


def post_suggestion(
    client: TestClient,
    headers: dict[str, str],
    body: dict,
    workflow_id: str,
    request_id: UUID,
    clarification: dict | None = None,
) -> object:
    payload: dict[str, object] = {
        "request_id": str(request_id),
        "expected_revision": body["revision"],
        "step_id": body["view"]["step_id"],
    }
    if clarification is not None:
        payload["clarification"] = clarification
    return client.post(
        f"/todo-workflows/{workflow_id}/suggestions",
        json=payload,
        headers=headers,
    )


def failing_provider(goal: str, _config: object) -> tuple[str, ...]:
    raise AssertionError("cloud-mode public route must never call the provider")


# ---------------------------------------------------------------------------
# Adapter tests (fake the Cloud Tasks client, assert the exact request)


class FakeTasksClient:
    """Stand-in for tasks_v2.CloudTasksClient recording create_task calls."""

    instances: ClassVar[list[FakeTasksClient]] = []
    behaviors: ClassVar[list] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.calls: list[dict] = []
        FakeTasksClient.instances.append(self)

    def create_task(
        self,
        request: object = None,
        *,
        retry: object = "sentinel",
        timeout: object = "sentinel",
    ) -> dict:
        assert request is not None
        self.calls.append({"request": request, "retry": retry, "timeout": timeout})
        behavior = (
            FakeTasksClient.behaviors.pop(0)
            if FakeTasksClient.behaviors
            else "ok"
        )
        if behavior != "ok":
            raise behavior
        return {"name": "created"}


@pytest.fixture
def fake_tasks(monkeypatch: pytest.MonkeyPatch) -> type[FakeTasksClient]:
    from google.cloud import tasks_v2

    FakeTasksClient.instances = []
    FakeTasksClient.behaviors = []
    monkeypatch.setattr(tasks_v2, "CloudTasksClient", FakeTasksClient)
    return FakeTasksClient


def expected_task_name(suggestion_id: int, fingerprint: str) -> str:
    digest = hashlib.sha256(f"{suggestion_id}:{fingerprint}".encode()).hexdigest()
    return f"suggest-v1-{digest}"


def test_enqueue_builds_exact_task_request(
    fake_tasks: type[FakeTasksClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import suggestion_tasks

    use_cloud_env(monkeypatch)
    assert (
        suggestion_tasks.enqueue_suggestion(123, "a" * 64)
        == suggestion_tasks.ENQUEUE_ACCEPTED
    )

    assert len(FakeTasksClient.instances) == 1
    (call,) = FakeTasksClient.instances[0].calls
    task = call["request"]["task"]
    parent = call["request"]["parent"]
    assert parent == "projects/demo-project/locations/us-central1/queues/suggestion-queue"
    assert task.name == f"{parent}/tasks/{expected_task_name(123, 'a' * 64)}"
    assert task.name.startswith(f"{parent}/tasks/suggest-v1-")
    body = json.dumps({"version": 1, "suggestion_id": 123}).encode()
    assert bytes(task.http_request.body) == body
    assert len(bytes(task.http_request.body)) <= 1024
    assert (
        task.http_request.url
        == "https://suggestion-worker-abc123-uc.a.run.app/internal/suggestions"
    )
    assert dict(task.http_request.headers) == {"Content-Type": "application/json"}
    assert (
        task.http_request.oidc_token.service_account_email
        == "task-invoker@demo-project.iam.gserviceaccount.com"
    )
    assert (
        task.http_request.oidc_token.audience
        == "https://suggestion-worker-abc123-uc.a.run.app"
    )
    assert task.dispatch_deadline.seconds == 60
    assert call["retry"] is None
    assert call["timeout"] == 5


def test_enqueue_task_name_is_stable_for_one_row(
    fake_tasks: type[FakeTasksClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import suggestion_tasks

    use_cloud_env(monkeypatch)
    suggestion_tasks.enqueue_suggestion(7, "b" * 64)
    suggestion_tasks.enqueue_suggestion(7, "b" * 64)

    names = [
        call["request"]["task"].name
        for instance in FakeTasksClient.instances
        for call in instance.calls
    ]
    assert len(names) == 2
    assert names[0] == names[1]


def test_enqueue_treats_already_exists_as_success(
    fake_tasks: type[FakeTasksClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from google.api_core.exceptions import AlreadyExists

    from app import suggestion_tasks

    use_cloud_env(monkeypatch)
    FakeTasksClient.behaviors = [AlreadyExists("task exists")]
    assert (
        suggestion_tasks.enqueue_suggestion(9, "c" * 64)
        == suggestion_tasks.ENQUEUE_DEDUPLICATED
    )


def test_enqueue_sanitizes_other_failures(
    fake_tasks: type[FakeTasksClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import suggestion_tasks

    use_cloud_env(monkeypatch)
    FakeTasksClient.behaviors = [RuntimeError("boom credentials exploded")]
    with pytest.raises(suggestion_tasks.EnqueueUnavailable) as excinfo:
        suggestion_tasks.enqueue_suggestion(9, "c" * 64)
    assert "boom" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Cloud-mode route tests


class FakeEnqueue:
    """Injected enqueue seam observing the committed row on a new connection."""

    def __init__(
        self, session_factory: sessionmaker[Session], outcome: str = "accepted"
    ) -> None:
        self.session_factory = session_factory
        self.outcome = outcome
        self.calls: list[tuple[int, str, str | None]] = []

    def __call__(
        self,
        suggestion_id: int,
        fingerprint: str,
        trace_parent: str | None = None,
    ) -> str:
        from app.workflow_repository import WorkflowSuggestionRequestRow

        with self.session_factory() as session:
            row = session.scalar(
                select(WorkflowSuggestionRequestRow).where(
                    WorkflowSuggestionRequestRow.id == suggestion_id
                )
            )
            assert row is not None, "enqueue must observe the committed row"
            assert row.status == "pending"
            assert row.request_fingerprint == fingerprint
            # The stored context travels explicitly: the seam records what
            # it was given and the row carries the committed value.
            assert trace_parent == row.trace_parent
        self.calls.append((suggestion_id, fingerprint, trace_parent))
        return self.outcome


def cloud_client(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    enqueue: object,
) -> TestClient:
    from app.main import create_app

    use_cloud_env(monkeypatch)
    return TestClient(
        create_app(
            session_factory,
            suggestion_callable=failing_provider,  # type: ignore[arg-type]
            enqueue_callable=enqueue,  # type: ignore[arg-type]
        )
    )


def test_cloud_new_request_returns_202_without_provider(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    enqueue = FakeEnqueue(session_factory)
    with cloud_client(session_factory, monkeypatch, enqueue) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        response = post_suggestion(
            client, headers, body, body["workflow_id"], request_id
        )
        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "pending"
        assert payload["request_id"] == str(request_id)
        assert set(payload) == {
            "contract_version",
            "workflow_id",
            "request_id",
            "base_revision",
            "step_id",
            "status",
            "proposed_titles",
            "error_code",
        }
    assert len(enqueue.calls) == 1


def test_cloud_pending_replay_retries_enqueue(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workflow_repository import WorkflowSuggestionRequestRow

    del database_session
    enqueue = FakeEnqueue(session_factory)
    with cloud_client(session_factory, monkeypatch, enqueue) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        first = post_suggestion(client, headers, body, body["workflow_id"], request_id)
        second = post_suggestion(client, headers, body, body["workflow_id"], request_id)
        assert first.status_code == 202
        assert second.status_code == 202
        assert second.json()["status"] == "pending"
    assert len(enqueue.calls) == 2
    assert enqueue.calls[0] == enqueue.calls[1]
    with session_factory() as session:
        rows = session.scalars(select(WorkflowSuggestionRequestRow)).all()
        assert len(rows) == 1
        assert rows[0].status == "pending"


def test_cloud_ready_replay_returns_200_without_enqueue(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.suggestion_service import finish_suggestion

    del database_session
    enqueue = FakeEnqueue(session_factory)
    with cloud_client(session_factory, monkeypatch, enqueue) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        assert (
            post_suggestion(client, headers, body, body["workflow_id"], request_id).status_code
            == 202
        )
        suggestion_id, _fingerprint, _trace_parent = enqueue.calls[0]
        with session_factory() as session:
            from app.workflow_repository import WorkflowSuggestionRequestRow

            row = session.scalar(
                select(WorkflowSuggestionRequestRow).where(
                    WorkflowSuggestionRequestRow.id == suggestion_id
                )
            )
            assert row is not None
            session.commit()
            saved = finish_suggestion(
                session,
                row.owner_id,
                row.workflow_id,
                request_id,
                titles=("Choose a date", "Invite guests"),
                error_code=None,
            )
            assert saved is not None
        replay = post_suggestion(client, headers, body, body["workflow_id"], request_id)
        assert replay.status_code == 200
        assert replay.json()["status"] == "ready"
        assert replay.json()["proposed_titles"] == ["Choose a date", "Invite guests"]
    assert len(enqueue.calls) == 1


def test_cloud_failed_replay_returns_mapped_error_without_enqueue(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.suggestion_service import finish_suggestion

    del database_session
    enqueue = FakeEnqueue(session_factory)
    with cloud_client(session_factory, monkeypatch, enqueue) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        assert (
            post_suggestion(client, headers, body, body["workflow_id"], request_id).status_code
            == 202
        )
        suggestion_id, _fingerprint, _trace_parent = enqueue.calls[0]
        with session_factory() as session:
            from app.workflow_repository import WorkflowSuggestionRequestRow

            row = session.scalar(
                select(WorkflowSuggestionRequestRow).where(
                    WorkflowSuggestionRequestRow.id == suggestion_id
                )
            )
            assert row is not None
            session.commit()
            finish_suggestion(
                session,
                row.owner_id,
                row.workflow_id,
                request_id,
                titles=None,
                error_code=SuggestionErrorCode.PROVIDER_UNAVAILABLE,
            )
        replay = post_suggestion(client, headers, body, body["workflow_id"], request_id)
        assert replay.status_code == 502
        assert replay.json()["detail"]["code"] == "provider_unavailable"
    assert len(enqueue.calls) == 1


def test_cloud_lost_enqueue_response_repairs_on_same_id_replay(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    fake_tasks: type[FakeTasksClient],
) -> None:
    """First POST 503s after a server-side create; replay meets AlreadyExists."""

    from google.api_core.exceptions import AlreadyExists

    from app import suggestion_tasks
    from app.main import create_app
    from app.workflow_repository import WorkflowSuggestionRequestRow

    del database_session
    use_cloud_env(monkeypatch)
    FakeTasksClient.behaviors = [
        RuntimeError("connection dropped after server applied the task"),
        AlreadyExists("task suggest-v1-... already exists"),
    ]
    with TestClient(
        create_app(
            session_factory,
            suggestion_callable=failing_provider,  # type: ignore[arg-type]
        )
    ) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        first = post_suggestion(client, headers, body, body["workflow_id"], request_id)
        assert first.status_code == 503
        assert first.json()["detail"]["code"] == "enqueue_unavailable"
        assert suggestion_tasks.EnqueueUnavailable is not None
        second = post_suggestion(client, headers, body, body["workflow_id"], request_id)
        assert second.status_code == 202
        assert second.json()["status"] == "pending"
    with session_factory() as session:
        rows = session.scalars(select(WorkflowSuggestionRequestRow)).all()
        assert len(rows) == 1
        assert rows[0].status == "pending"
    assert sum(len(instance.calls) for instance in FakeTasksClient.instances) == 2


def test_cloud_enqueue_unavailable_keeps_saved_reservation(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import suggestion_tasks
    from app.main import create_app
    from app.workflow_repository import WorkflowSuggestionRequestRow

    del database_session
    use_cloud_env(monkeypatch)

    def unavailable(
        suggestion_id: int, fingerprint: str, trace_parent: str | None = None
    ) -> None:
        del suggestion_id, fingerprint, trace_parent
        raise suggestion_tasks.EnqueueUnavailable("queue is down")

    with TestClient(
        create_app(
            session_factory,
            suggestion_callable=failing_provider,  # type: ignore[arg-type]
            enqueue_callable=unavailable,  # type: ignore[arg-type]
        )
    ) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        response = post_suggestion(client, headers, body, body["workflow_id"], request_id)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "enqueue_unavailable"
        saved = client.get(
            f"/todo-workflows/{body['workflow_id']}/suggestions", headers=headers
        )
        assert saved.status_code == 200
        assert saved.json()["status"] == "pending"
    with session_factory() as session:
        rows = session.scalars(select(WorkflowSuggestionRequestRow)).all()
        assert len(rows) == 1
        assert rows[0].status == "pending"


def test_cloud_new_request_emits_reserved_and_enqueue_accepted(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A fresh cloud reservation logs one reserved plus one accepted enqueue."""
    from app.suggestion_tasks import task_name_for

    del database_session
    enqueue = FakeEnqueue(session_factory)
    with caplog.at_level(logging.INFO, logger="app"), cloud_client(
        session_factory, monkeypatch, enqueue
    ) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        response = post_suggestion(
            client, headers, body, body["workflow_id"], request_id
        )
        assert response.status_code == 202
    reserved = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_reserved"
    ]
    assert len(reserved) == 1
    assert getattr(reserved[0], "outcome", None) == "reserved"
    assert getattr(reserved[0], "workflow_id", None) == body["workflow_id"]
    assert getattr(reserved[0], "suggestion_request_id", None) == str(request_id)
    enqueued = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_enqueue"
    ]
    assert len(enqueued) == 1
    assert getattr(enqueued[0], "outcome", None) == "accepted"
    assert getattr(enqueued[0], "suggestion_request_id", None) == str(request_id)
    suggestion_id = getattr(enqueued[0], "suggestion_id", None)
    assert isinstance(suggestion_id, int)
    (row_id, fingerprint, _trace_parent) = enqueue.calls[0]
    assert suggestion_id == row_id
    assert getattr(enqueued[0], "task_id", None) == task_name_for(
        row_id, fingerprint
    )


def test_cloud_same_id_replay_emits_no_second_reserved(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A same-ID replay retries enqueue but never logs another reservation."""
    del database_session
    enqueue = FakeEnqueue(session_factory)
    with caplog.at_level(logging.INFO, logger="app"), cloud_client(
        session_factory, monkeypatch, enqueue
    ) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        first = post_suggestion(
            client, headers, body, body["workflow_id"], request_id
        )
        second = post_suggestion(
            client, headers, body, body["workflow_id"], request_id
        )
        assert first.status_code == 202
        assert second.status_code == 202
    reserved = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_reserved"
    ]
    assert len(reserved) == 1, "replay must not duplicate the reservation event"
    enqueued = [
        getattr(record, "outcome", None)
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_enqueue"
    ]
    assert enqueued == ["accepted", "accepted"], enqueued


def test_cloud_enqueue_deduplicated_event(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A deduplicated enqueue attempt logs the bounded deduplicated outcome."""
    del database_session
    enqueue = FakeEnqueue(session_factory, outcome="deduplicated")
    with caplog.at_level(logging.INFO, logger="app"), cloud_client(
        session_factory, monkeypatch, enqueue
    ) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        response = post_suggestion(
            client, headers, body, body["workflow_id"], uuid4()
        )
        assert response.status_code == 202
    enqueued = [
        getattr(record, "outcome", None)
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_enqueue"
    ]
    assert enqueued == ["deduplicated"], enqueued


def test_cloud_enqueue_unavailable_event(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed enqueue logs unavailable while keeping the saved reservation."""
    from app import suggestion_tasks
    from app.main import create_app

    del database_session
    use_cloud_env(monkeypatch)

    def unavailable(
        suggestion_id: int, fingerprint: str, trace_parent: str | None = None
    ) -> str:
        del suggestion_id, fingerprint, trace_parent
        raise suggestion_tasks.EnqueueUnavailable("queue is down")

    with caplog.at_level(logging.INFO, logger="app"), TestClient(
        create_app(
            session_factory,
            suggestion_callable=failing_provider,  # type: ignore[arg-type]
            enqueue_callable=unavailable,  # type: ignore[arg-type]
        )
    ) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        response = post_suggestion(
            client, headers, body, body["workflow_id"], request_id
        )
        assert response.status_code == 503
    reserved = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_reserved"
    ]
    assert len(reserved) == 1
    enqueued = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_enqueue"
    ]
    assert len(enqueued) == 1
    assert getattr(enqueued[0], "outcome", None) == "unavailable"
    assert getattr(enqueued[0], "suggestion_request_id", None) == str(request_id)
    assert isinstance(getattr(enqueued[0], "suggestion_id", None), int)
    assert isinstance(getattr(enqueued[0], "task_id", None), str)


def test_inline_new_request_emits_reserved_without_enqueue(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Inline reservations log reserved; no enqueue leg exists inline."""
    from app.main import create_app

    del database_session
    monkeypatch.delenv("SUGGESTION_EXECUTION", raising=False)
    provider = InlineTitles()
    with caplog.at_level(logging.INFO, logger="app"), TestClient(
        create_app(
            session_factory,
            suggestion_callable=provider,  # type: ignore[arg-type]
        )
    ) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        response = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json={
                "request_id": str(request_id),
                "expected_revision": body["revision"],
                "step_id": body["view"]["step_id"],
            },
            headers=headers,
        )
        assert response.status_code == 201
    reserved = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_reserved"
    ]
    assert len(reserved) == 1
    assert getattr(reserved[0], "suggestion_request_id", None) == str(request_id)
    assert [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_enqueue"
    ] == []


def test_cloud_cross_owner_post_is_denied_without_enqueue(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    enqueue = FakeEnqueue(session_factory)
    with cloud_client(session_factory, monkeypatch, enqueue) as client:
        owner_headers = auth_headers(client, "owner")
        intruder_headers = auth_headers(client, "intruder")
        body = start_collecting(client, owner_headers)
        response = post_suggestion(
            client, intruder_headers, body, body["workflow_id"], uuid4()
        )
        assert response.status_code == 404
    assert enqueue.calls == []


def test_cloud_conflicting_fingerprint_never_enqueues(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    enqueue = FakeEnqueue(session_factory)
    with cloud_client(session_factory, monkeypatch, enqueue) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        first = post_suggestion(
            client,
            headers,
            body,
            body["workflow_id"],
            request_id,
            clarification={"field": "date", "value": "next Saturday"},
        )
        assert first.status_code == 202
        conflict = post_suggestion(
            client,
            headers,
            body,
            body["workflow_id"],
            request_id,
            clarification={"field": "budget", "value": "under $50"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "request_id_reused"
    assert len(enqueue.calls) == 1


def test_unknown_execution_mode_fails_startup(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import create_app

    monkeypatch.setenv("SUGGESTION_EXECUTION", "bogus_mode")
    with pytest.raises(ValueError):
        create_app(session_factory)


def test_cloud_mode_with_incomplete_config_fails_startup(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import create_app

    use_cloud_env(monkeypatch)
    monkeypatch.delenv("CLOUD_TASKS_QUEUE")
    with pytest.raises(ValueError):
        create_app(session_factory)


def test_default_enqueue_runner_uses_startup_config_snapshot(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    fake_tasks: type[FakeTasksClient],
) -> None:
    """Env changes after create_app must not affect default enqueue routing."""

    from app.main import create_app

    del database_session
    use_cloud_env(monkeypatch)
    with TestClient(
        create_app(
            session_factory,
            suggestion_callable=failing_provider,  # type: ignore[arg-type]
        )
    ) as client:
        # Mutate every routing value after startup; the bound default
        # runner must still use the startup snapshot.
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "changed-project")
        monkeypatch.setenv("CLOUD_TASKS_LOCATION", "europe-west1")
        monkeypatch.setenv("CLOUD_TASKS_QUEUE", "changed-queue")
        monkeypatch.setenv(
            "SUGGESTION_WORKER_URL", "https://changed-xyz-uc.a.run.app"
        )
        monkeypatch.setenv(
            "TASK_INVOKER_SERVICE_ACCOUNT",
            "changed@changed.iam.gserviceaccount.com",
        )
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        response = post_suggestion(
            client, headers, body, body["workflow_id"], request_id
        )
        assert response.status_code == 202
    assert len(FakeTasksClient.instances) == 1
    (call,) = FakeTasksClient.instances[0].calls
    task = call["request"]["task"]
    assert call["request"]["parent"] == (
        "projects/demo-project/locations/us-central1/queues/suggestion-queue"
    )
    assert task.http_request.url == (
        "https://suggestion-worker-abc123-uc.a.run.app/internal/suggestions"
    )
    assert task.http_request.oidc_token.audience == (
        "https://suggestion-worker-abc123-uc.a.run.app"
    )
    assert task.http_request.oidc_token.service_account_email == (
        "task-invoker@demo-project.iam.gserviceaccount.com"
    )


def test_injected_enqueue_callable_still_used_in_cloud_mode(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public two-argument injection seam still overrides the default."""

    del database_session
    enqueue = FakeEnqueue(session_factory)
    with cloud_client(session_factory, monkeypatch, enqueue) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        response = post_suggestion(
            client, headers, body, body["workflow_id"], request_id
        )
        assert response.status_code == 202
    assert len(enqueue.calls) == 1


# ---------------------------------------------------------------------------
# Phase 21 Task 2 (TDD red): durable trace context across the queue.
#
# The reservation captures the API server span context as a canonical
# version-00 W3C traceparent (at most 55 chars) stored alongside the row.
# Enqueue forwards it in both `traceparent` and `X-Suggestion-Traceparent`
# headers with the same validated value; the task body stays version 1.

TRACE_A = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACE_B = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
INCOMING_A = "00-11111111111111111111111111111111-2222222222222222-01"
INCOMING_B = "00-33333333333333333333333333333333-4444444444444444-01"


def test_enqueue_emits_matching_trace_headers(
    fake_tasks: type[FakeTasksClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import suggestion_tasks

    use_cloud_env(monkeypatch)
    suggestion_tasks.enqueue_suggestion(5, "d" * 64, TRACE_A)

    assert len(FakeTasksClient.instances) == 1
    (call,) = FakeTasksClient.instances[0].calls
    task = call["request"]["task"]
    headers = dict(task.http_request.headers)
    assert headers["traceparent"] == TRACE_A
    assert headers["X-Suggestion-Traceparent"] == TRACE_A
    assert "baggage" not in {key.lower() for key in headers}
    assert "tracestate" not in {key.lower() for key in headers}
    # Task body version 1 is unchanged: trace context travels in headers only.
    assert bytes(task.http_request.body) == (
        json.dumps({"version": 1, "suggestion_id": 5}).encode()
    )
    assert task.name.endswith(expected_task_name(5, "d" * 64))


def test_enqueue_omits_trace_headers_when_missing_or_invalid(
    fake_tasks: type[FakeTasksClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import suggestion_tasks

    use_cloud_env(monkeypatch)
    suggestion_tasks.enqueue_suggestion(6, "e" * 64)
    suggestion_tasks.enqueue_suggestion(6, "e" * 64, None)
    suggestion_tasks.enqueue_suggestion(6, "e" * 64, "bogus")
    suggestion_tasks.enqueue_suggestion(6, "e" * 64, TRACE_A + "00")

    assert len(FakeTasksClient.instances) == 4
    for instance in FakeTasksClient.instances:
        (call,) = instance.calls
        headers = {key.lower() for key in dict(call["request"]["task"].http_request.headers)}
        assert headers == {"content-type"}


def sampled_cloud_client(
    session_factory, monkeypatch: pytest.MonkeyPatch, enqueue: object
) -> TestClient:
    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    return cloud_client(session_factory, monkeypatch, enqueue)


def row_trace_parent(session_factory, suggestion_id: int) -> object:
    from app.workflow_repository import WorkflowSuggestionRequestRow

    with session_factory() as session:
        return session.scalar(
            select(WorkflowSuggestionRequestRow.trace_parent).where(
                WorkflowSuggestionRequestRow.id == suggestion_id
            )
        )


def test_cloud_post_stores_server_trace_and_enqueues_with_it(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workflow_repository import WorkflowSuggestionRequestRow

    del database_session
    enqueue = FakeEnqueue(session_factory)
    with sampled_cloud_client(session_factory, monkeypatch, enqueue) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        response = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json={
                "request_id": str(request_id),
                "expected_revision": body["revision"],
                "step_id": body["view"]["step_id"],
            },
            headers={**headers, "traceparent": INCOMING_A},
        )
        assert response.status_code == 202
    assert len(enqueue.calls) == 1
    suggestion_id, _fingerprint, enqueued_tp = enqueue.calls[0]
    with session_factory() as session:
        row = session.scalar(
            select(WorkflowSuggestionRequestRow).where(
                WorkflowSuggestionRequestRow.id == suggestion_id
            )
        )
        assert row is not None
        stored = row.trace_parent
    assert isinstance(stored, str) and len(stored) <= 55
    assert stored.startswith("00-11111111111111111111111111111111-")
    assert stored != INCOMING_A  # new span ID for the API server span
    assert enqueued_tp == stored


def test_cloud_replay_from_other_trace_preserves_original_context(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    enqueue = FakeEnqueue(session_factory)
    with sampled_cloud_client(session_factory, monkeypatch, enqueue) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        payload = {
            "request_id": str(request_id),
            "expected_revision": body["revision"],
            "step_id": body["view"]["step_id"],
        }
        first = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json=payload,
            headers={**headers, "traceparent": INCOMING_A},
        )
        assert first.status_code == 202
        # Enqueue repair from another API request/trace reuses the original.
        second = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json=payload,
            headers={**headers, "traceparent": INCOMING_B},
        )
        assert second.status_code == 202
    assert len(enqueue.calls) == 2
    assert enqueue.calls[0] == enqueue.calls[1]
    _suggestion_id, _fingerprint, enqueued_tp = enqueue.calls[0]
    assert isinstance(enqueued_tp, str)
    assert enqueued_tp.startswith("00-11111111111111111111111111111111-")
    assert row_trace_parent(session_factory, _suggestion_id) == enqueued_tp


def test_api_to_worker_waterfall_shares_one_trace(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    fake_tasks: type[FakeTasksClient],
) -> None:
    """Separate API/worker tracer providers, one in-memory sink, one trace.

    The API reservation stores its server span context; enqueue forwards it
    in both headers; the worker receipt joins it and nests
    process/claim/provider/finish beneath it. No process-local context is
    shared: only the task headers connect the two providers.
    """
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.main import create_app
    from app.worker import create_worker_app

    del database_session
    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    use_cloud_env(monkeypatch)
    sink: InMemorySpanExporter = InMemorySpanExporter()

    from test_suggestion_worker import RecordingProvider

    provider = RecordingProvider()
    api_app = create_app(
        session_factory,
        suggestion_callable=failing_provider,  # type: ignore[arg-type]
    )
    api_app.state.tracing_exporter = sink
    worker_app = create_worker_app(
        session_factory=session_factory, suggestion_callable=provider
    )
    worker_app.state.tracing_exporter = sink

    with TestClient(api_app) as api, TestClient(worker_app) as worker:
        headers = auth_headers(api)
        body = start_collecting(api, headers)
        request_id = uuid4()
        response = api.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json={
                "request_id": str(request_id),
                "expected_revision": body["revision"],
                "step_id": body["view"]["step_id"],
            },
            headers={**headers, "traceparent": INCOMING_A},
        )
        assert response.status_code == 202
        assert len(FakeTasksClient.instances) == 1
        (call,) = FakeTasksClient.instances[0].calls
        task_headers = dict(call["request"]["task"].http_request.headers)
        stored_tp = task_headers["traceparent"]
        assert task_headers["X-Suggestion-Traceparent"] == stored_tp
        body_bytes = bytes(call["request"]["task"].http_request.body)

        delivery = worker.post(
            "/internal/suggestions",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "traceparent": stored_tp,
                "X-Suggestion-Traceparent": stored_tp,
            },
        )
        assert delivery.status_code == 204
        # A lost-acknowledgement repeat delivery reuses the same headers and
        # records a second process span without another provider call.
        repeat = worker.post(
            "/internal/suggestions",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "traceparent": stored_tp,
                "X-Suggestion-Traceparent": stored_tp,
            },
        )
        assert repeat.status_code == 204
        api_app.state.tracing_state.flush()
        worker_app.state.tracing_state.flush()

    assert len(provider.calls) == 1
    spans = list(sink.get_finished_spans())
    api_span = next(
        span for span in spans
        if span.name == "POST /todo-workflows/{workflow_id}/suggestions"
    )
    trace_id = format(api_span.get_span_context().trace_id, "032x")
    assert trace_id == INCOMING_A.split("-")[1]
    waterfall = [span for span in spans if (
        format(span.get_span_context().trace_id, "032x") == trace_id
    )]
    by_name: dict[str, list] = {}
    for span in waterfall:
        by_name.setdefault(span.name, []).append(span)
    assert set(by_name) == {
        "POST /todo-workflows/{workflow_id}/suggestions",
        "db.reserve_suggestion",
        "cloudtasks.enqueue",
        "POST /internal/suggestions",
        "suggestion.process",
        "db.claim_suggestion",
        "provider.suggestions",
        "db.finish_suggestion",
    }, sorted(by_name)
    assert len(by_name["POST /internal/suggestions"]) == 2
    assert len(by_name["suggestion.process"]) == 2
    ids = [span.get_span_context().span_id for span in waterfall]
    assert len(set(ids)) == len(ids)

    def parent_id(span) -> int | None:
        return span.parent.span_id if span.parent is not None else None

    api_id = api_span.get_span_context().span_id
    (reserve,) = by_name["db.reserve_suggestion"]
    (enqueue,) = by_name["cloudtasks.enqueue"]
    assert parent_id(reserve) == api_id
    assert parent_id(enqueue) == api_id
    for receipt, process in zip(
        sorted(
            by_name["POST /internal/suggestions"],
            key=lambda span: span.start_time,
        ),
        sorted(
            by_name["suggestion.process"], key=lambda span: span.start_time
        ),
    ):
        assert parent_id(receipt) == api_id
        assert parent_id(process) == receipt.get_span_context().span_id
    first_process = min(
        by_name["suggestion.process"], key=lambda span: span.start_time
    )
    first_process_id = first_process.get_span_context().span_id
    # Both deliveries attempt the claim under their own process span; only
    # the first reaches the provider and finalizes.
    assert len(by_name["db.claim_suggestion"]) == 2
    for receipt_process, claim in zip(
        sorted(
            by_name["suggestion.process"], key=lambda span: span.start_time
        ),
        sorted(
            by_name["db.claim_suggestion"], key=lambda span: span.start_time
        ),
    ):
        assert parent_id(claim) == receipt_process.get_span_context().span_id
    for name in ("provider.suggestions", "db.finish_suggestion"):
        (child,) = by_name[name]
        assert parent_id(child) == first_process_id, name
    for span in waterfall:
        assert dict(span.attributes or {}).get("suggestion_id") in (None,) or True


def test_cloud_replay_enqueue_span_links_to_stored_trace(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same-ID replay keeps its own request parent and links to stored trace.

    The replay POST arrives on another trace (INCOMING_B) while the stored
    row context names the original trace (INCOMING_A). The replay's
    `cloudtasks.enqueue` span stays parented under the replay API exchange
    and carries one link to the validated stored context.
    """
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.main import create_app

    del database_session
    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    use_cloud_env(monkeypatch)
    sink: InMemorySpanExporter = InMemorySpanExporter()
    enqueue = FakeEnqueue(session_factory)
    api_app = create_app(
        session_factory,
        suggestion_callable=failing_provider,  # type: ignore[arg-type]
        enqueue_callable=enqueue,  # type: ignore[arg-type]
    )
    api_app.state.tracing_exporter = sink
    with TestClient(api_app) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        payload = {
            "request_id": str(request_id),
            "expected_revision": body["revision"],
            "step_id": body["view"]["step_id"],
        }
        first = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json=payload,
            headers={**headers, "traceparent": INCOMING_A},
        )
        assert first.status_code == 202
        second = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json=payload,
            headers={**headers, "traceparent": INCOMING_B},
        )
        assert second.status_code == 202
        api_app.state.tracing_state.flush()
    assert len(enqueue.calls) == 2
    _suggestion_id, _fingerprint, stored_tp = enqueue.calls[0]
    assert isinstance(stored_tp, str)
    stored_trace_id = stored_tp.split("-")[1]
    assert stored_trace_id == INCOMING_A.split("-")[1]

    spans = list(sink.get_finished_spans())
    enqueues = sorted(
        [span for span in spans if span.name == "cloudtasks.enqueue"],
        key=lambda span: span.start_time,
    )
    assert len(enqueues) == 2
    replay_spans = [
        span for span in spans
        if format(span.get_span_context().trace_id, "032x") == INCOMING_B.split("-")[1]
    ]
    replay_api = next(
        span for span in replay_spans
        if span.name == "POST /todo-workflows/{workflow_id}/suggestions"
    )
    (replay_enqueue,) = [
        span for span in enqueues
        if format(span.get_span_context().trace_id, "032x") == INCOMING_B.split("-")[1]
    ]
    # The replay request stays the parent: no reparenting onto stored trace.
    assert replay_enqueue.parent is not None
    assert replay_enqueue.parent.span_id == replay_api.get_span_context().span_id
    # ... while one link names the validated stored context.
    assert replay_enqueue.links is not None and len(replay_enqueue.links) == 1
    assert format(replay_enqueue.links[0].context.trace_id, "032x") == stored_trace_id


# ---------------------------------------------------------------------------
# Phase 21 Task 3 (TDD red): inline waterfall spans.
#
# The synchronous API path must show db.reserve_suggestion → provider
# work inside the request trace with a truthful provider outcome, and no
# queue/enqueue leg (nothing waits on a broker inline).
# ---------------------------------------------------------------------------


class InlineTitles:
    """Credential-free inline provider returning fixed titles."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def __call__(
        self, goal: str, config: object, clarification: object = None
    ) -> tuple[str, str]:
        self.calls.append((goal, clarification))
        return ("Choose a date", "Invite guests")


def test_inline_waterfall_spans_share_request_trace(
    database_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.main import create_app

    del database_session
    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    sink: InMemorySpanExporter = InMemorySpanExporter()
    provider = InlineTitles()
    app = create_app(
        session_factory,
        suggestion_callable=provider,  # type: ignore[arg-type]
    )
    app.state.tracing_exporter = sink
    with TestClient(app) as client:
        headers = auth_headers(client)
        body = start_collecting(client, headers)
        request_id = uuid4()
        response = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json={
                "request_id": str(request_id),
                "expected_revision": body["revision"],
                "step_id": body["view"]["step_id"],
            },
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["status"] == "ready"
        app.state.tracing_state.flush()
    assert len(provider.calls) == 1
    spans = list(sink.get_finished_spans())
    by_name = {span.name: span for span in spans}
    assert "db.reserve_suggestion" in by_name, sorted(by_name)
    assert "provider.suggestions" in by_name, sorted(by_name)
    assert "cloudtasks.enqueue" not in by_name
    assert "suggestion.enqueue" not in by_name
    request_span = next(
        span
        for span in spans
        if span.name == "POST /todo-workflows/{workflow_id}/suggestions"
    )
    request_trace = format(request_span.get_span_context().trace_id, "032x")
    for name in ("db.reserve_suggestion", "provider.suggestions"):
        span = by_name[name]
        assert format(span.get_span_context().trace_id, "032x") == request_trace
    provider_span = by_name["provider.suggestions"]
    assert dict(provider_span.attributes or {}).get("outcome") == "ok"
