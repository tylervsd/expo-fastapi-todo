"""Task 2: Cloud Tasks enqueue adapter and cloud-mode suggestion route.

TDD red: this module fails at collection until `google-cloud-tasks` is
added and `app.suggestion_tasks` exists, then its cases fail until the
cloud branch lands in `app.main.create_app`.
"""

from __future__ import annotations

import hashlib
import json
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
    suggestion_tasks.enqueue_suggestion(123, "a" * 64)

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
    suggestion_tasks.enqueue_suggestion(9, "c" * 64)


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

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
        self.calls: list[tuple[int, str]] = []

    def __call__(self, suggestion_id: int, fingerprint: str) -> None:
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
        self.calls.append((suggestion_id, fingerprint))


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
        suggestion_id, _fingerprint = enqueue.calls[0]
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
        suggestion_id, _fingerprint = enqueue.calls[0]
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

    def unavailable(suggestion_id: int, fingerprint: str) -> None:
        del suggestion_id, fingerprint
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
