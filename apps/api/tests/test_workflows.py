import asyncio
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app import main as main_module
from app.main import YesNoWorkflowView, create_app
from app.suggestion_provider import (
    InvalidSuggestionOutput,
    OpenRouterConfig,
    ProviderUnavailable,
    SuggestionTimeout,
)
from app.workflow_repository import WorkflowSuggestionRequestRow

MAX_REVISION = 2147483647


@pytest.fixture
def client(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> Iterator[TestClient]:
    del database_session
    with TestClient(create_app(session_factory)) as test_client:
        yield test_client


@pytest.fixture
def suggestion_client(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> Iterator[tuple[TestClient, list[str]]]:
    del database_session
    calls: list[str] = []

    async def suggest(goal: str, _config: object) -> tuple[str, ...]:
        calls.append(goal)
        return ("Choose a date", "Invite guests")

    with TestClient(
        create_app(session_factory, suggestion_callable=suggest)
    ) as test_client:
        yield test_client, calls


def signup(client: TestClient, username: str = "alice") -> None:
    response = client.post(
        "/auth/signup", json={"username": username, "password": "long-enough-password"}
    )
    assert response.status_code == 201


def auth_headers(client: TestClient, username: str = "alice") -> dict[str, str]:
    signup(client, username)
    login = client.post(
        "/auth/login", json={"username": username, "password": "long-enough-password"}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def start_workflow_request(
    client: TestClient,
    headers: dict[str, str],
    title: str = "Plan birthday party",
    request_id: UUID | None = None,
) -> tuple[object, UUID]:
    request_id = request_id or uuid4()
    response = client.post(
        "/todo-workflows",
        json={"request_id": str(request_id), "title": title},
        headers=headers,
    )
    return response, request_id


def advance_workflow_request(
    client: TestClient,
    headers: dict[str, str],
    last: dict[str, object],
    action: dict[str, object],
    request_id: UUID | None = None,
) -> tuple[object, UUID]:
    request_id = request_id or uuid4()
    view = last["view"]
    assert isinstance(view, dict)
    response = client.post(
        f"/todo-workflows/{last['workflow_id']}/actions",
        json={
            "request_id": str(request_id),
            "expected_revision": last["revision"],
            "step_id": view["step_id"],
            "action": action,
        },
        headers=headers,
    )
    return response, request_id


def test_start_returns_assess_task_without_todos(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = auth_headers(client)

    response, _ = start_workflow_request(client, headers)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "workflow_id",
        "revision",
        "definition_version",
        "view_contract_version",
        "state",
        "title",
        "context",
        "result",
        "view",
    }
    assert body["revision"] == 0
    assert body["definition_version"] == 1
    assert body["view_contract_version"] == 1
    assert body["state"] == "ASSESS_TASK"
    assert body["title"] == "Plan birthday party"
    assert body["context"] == {
        "involves_multiple_steps": None,
        "proposed_todo_titles": [],
    }
    assert body["result"] is None
    workflow_id = body["workflow_id"]
    assert body["view"] == {
        "type": "yes_no",
        "step_id": f"{workflow_id}:ASSESS_TASK",
        "title": "Plan birthday party",
        "question": "Does this task involve multiple steps?",
        "actions": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
    }
    assert client.get("/todos", headers=headers).json() == []


def test_start_replay_returns_identical_201_without_duplicate(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    request_id = uuid4()

    first, _ = start_workflow_request(client, headers, request_id=request_id)
    assert first.status_code == 201
    replay, _ = start_workflow_request(client, headers, request_id=request_id)

    assert replay.status_code == 201
    assert replay.json() == first.json()
    with session_factory() as verification_session:
        rows = verification_session.scalars(select(WorkflowRow)).all()
        assert len(rows) == 1


def test_start_request_id_reuse_with_different_title_conflicts(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    request_id = uuid4()
    first, _ = start_workflow_request(
        client, headers, title="Plan birthday party", request_id=request_id
    )
    assert first.status_code == 201

    response = client.post(
        "/todo-workflows",
        json={"request_id": str(request_id), "title": "Different plan"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "request_id_reused",
            "message": "This request ID was already used with different details.",
        }
    }
    with session_factory() as verification_session:
        rows = verification_session.scalars(select(WorkflowRow)).all()
        assert len(rows) == 1


def test_suggestions_return_exact_proposal_and_do_not_create_todos(
    suggestion_client: tuple[TestClient, list[str]],
) -> None:
    client, calls = suggestion_client
    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    offered, _ = advance_workflow_request(
        client, headers, last, {"action": "answer_multiple_steps", "answer": True}
    )
    collecting, _ = advance_workflow_request(
        client,
        headers,
        offered.json(),
        {"action": "answer_multiple_steps", "answer": True},
    )
    body = collecting.json()
    workflow_id = body["workflow_id"]
    request_id = uuid4()
    response = client.post(
        f"/todo-workflows/{workflow_id}/suggestions",
        json={
            "request_id": str(request_id),
            "expected_revision": body["revision"],
            "step_id": body["view"]["step_id"],
        },
        headers=headers,
    )
    assert response.status_code == 201
    assert set(response.json()) == {
        "contract_version",
        "workflow_id",
        "request_id",
        "base_revision",
        "step_id",
        "status",
        "proposed_titles",
        "error_code",
    }
    assert response.json()["status"] == "ready"
    assert response.json()["proposed_titles"] == ["Choose a date", "Invite guests"]
    assert response.json()["error_code"] is None
    assert calls == ["Plan birthday party"]
    assert client.get("/todos", headers=headers).json() == []

    replay = client.post(
        f"/todo-workflows/{workflow_id}/suggestions",
        json={
            "request_id": str(request_id),
            "expected_revision": body["revision"],
            "step_id": body["view"]["step_id"],
        },
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json() == response.json()
    assert calls == ["Plan birthday party"]

    saved = client.get(f"/todo-workflows/{workflow_id}/suggestions", headers=headers)
    assert saved.status_code == 200
    assert saved.json() == response.json()


def test_ready_replay_does_not_require_provider_configuration(
    database_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    calls = 0

    async def suggest(
        goal: str, config: OpenRouterConfig
    ) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        assert goal == "Plan birthday party"
        assert config.model == "test-model"
        return ("Choose a date", "Invite guests")

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "test-model")
    monkeypatch.setattr(main_module, "request_todo_suggestions", suggest)

    with TestClient(create_app(session_factory)) as client:
        headers = auth_headers(client)
        started, _ = start_workflow_request(client, headers)
        offered, _ = advance_workflow_request(
            client,
            headers,
            started.json(),
            {"action": "answer_multiple_steps", "answer": True},
        )
        collecting, _ = advance_workflow_request(
            client,
            headers,
            offered.json(),
            {"action": "answer_multiple_steps", "answer": True},
        )
        body = collecting.json()
        payload = {
            "request_id": str(uuid4()),
            "expected_revision": body["revision"],
            "step_id": body["view"]["step_id"],
        }
        first = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json=payload,
            headers=headers,
        )
        assert first.status_code == 201
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

        replay = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json=payload,
            headers=headers,
        )

    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert calls == 1


def test_suggestion_post_rejects_other_owner_and_invalid_step_or_revision(
    suggestion_client: tuple[TestClient, list[str]],
) -> None:
    client, calls = suggestion_client
    alice_headers = auth_headers(client, "alice")
    bob_headers = auth_headers(client, "bob")
    started, _ = start_workflow_request(client, alice_headers)
    body = started.json()
    payload = {
        "request_id": str(uuid4()),
        "expected_revision": body["revision"],
        "step_id": body["view"]["step_id"],
    }
    hidden = client.post(
        f"/todo-workflows/{body['workflow_id']}/suggestions",
        json=payload,
        headers=bob_headers,
    )
    assert hidden.status_code == 404
    assert calls == []
    invalid_state = client.post(
        f"/todo-workflows/{body['workflow_id']}/suggestions",
        json=payload,
        headers=alice_headers,
    )
    assert invalid_state.status_code == 409
    assert invalid_state.json()["detail"]["code"] == "invalid_state"
    assert calls == []

    offered, _ = advance_workflow_request(
        client,
        alice_headers,
        body,
        {"action": "answer_multiple_steps", "answer": True},
    )
    collecting, _ = advance_workflow_request(
        client,
        alice_headers,
        offered.json(),
        {"action": "answer_multiple_steps", "answer": True},
    )
    collect_body = collecting.json()
    for invalid in (
        {
            **payload,
            "request_id": str(uuid4()),
            "expected_revision": collect_body["revision"] - 1,
            "step_id": collect_body["view"]["step_id"],
        },
        {
            **payload,
            "request_id": str(uuid4()),
            "expected_revision": collect_body["revision"],
            "step_id": f"{body['workflow_id']}:OFFER_BREAKDOWN",
        },
    ):
        response = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json=invalid,
            headers=alice_headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "stale_step"
    assert calls == []


@pytest.mark.parametrize(
    ("provider_error", "status_code", "error_code"),
    [
        (SuggestionTimeout("timeout"), 504, "timeout"),
        (InvalidSuggestionOutput("invalid"), 502, "invalid_output"),
    ],
)
def test_suggestion_provider_failures_are_typed_and_persisted(
    database_session: Session,
    session_factory: sessionmaker[Session],
    provider_error: Exception,
    status_code: int,
    error_code: str,
) -> None:
    del database_session

    async def fail(_goal: str, _config: object) -> tuple[str, ...]:
        raise provider_error

    with TestClient(create_app(session_factory, suggestion_callable=fail)) as client:
        headers = auth_headers(client)
        started, _ = start_workflow_request(client, headers)
        offered, _ = advance_workflow_request(
            client,
            headers,
            started.json(),
            {"action": "answer_multiple_steps", "answer": True},
        )
        collecting, _ = advance_workflow_request(
            client,
            headers,
            offered.json(),
            {"action": "answer_multiple_steps", "answer": True},
        )
        body = collecting.json()
        response = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json={
                "request_id": str(uuid4()),
                "expected_revision": body["revision"],
                "step_id": body["view"]["step_id"],
            },
            headers=headers,
        )
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == error_code


def test_failed_suggestion_replay_is_saved_and_does_not_call_provider_twice(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    calls = 0

    async def fail(_goal: str, _config: object) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        raise ProviderUnavailable("provider body must not escape")

    with TestClient(create_app(session_factory, suggestion_callable=fail)) as client:
        headers = auth_headers(client)
        started, _ = start_workflow_request(client, headers)
        offered, _ = advance_workflow_request(
            client, headers, started.json(), {"action": "answer_multiple_steps", "answer": True}
        )
        collecting, _ = advance_workflow_request(
            client, headers, offered.json(), {"action": "answer_multiple_steps", "answer": True}
        )
        body = collecting.json()
        payload = {
            "request_id": str(uuid4()),
            "expected_revision": body["revision"],
            "step_id": body["view"]["step_id"],
        }
        first = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json=payload,
            headers=headers,
        )
        second = client.post(
            f"/todo-workflows/{body['workflow_id']}/suggestions",
            json=payload,
            headers=headers,
        )
        assert first.status_code == second.status_code == 502
        assert first.json() == second.json()
        assert first.json()["detail"]["code"] == "provider_unavailable"
        assert "provider body" not in str(first.json())
        assert calls == 1


def test_deferred_suggestion_becomes_stale_after_workflow_cancellation(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    provider_started = Event()
    release_provider = Event()

    async def deferred(_goal: str, _config: object) -> tuple[str, ...]:
        provider_started.set()
        await asyncio.to_thread(release_provider.wait)
        return ("Choose a date", "Invite guests")

    with TestClient(create_app(session_factory, suggestion_callable=deferred)) as client:
        headers = auth_headers(client)
        started, _ = start_workflow_request(client, headers)
        offered, _ = advance_workflow_request(
            client, headers, started.json(), {"action": "answer_multiple_steps", "answer": True}
        )
        collecting, _ = advance_workflow_request(
            client, headers, offered.json(), {"action": "answer_multiple_steps", "answer": True}
        )
        body = collecting.json()
        workflow_id = body["workflow_id"]
        payload = {
            "request_id": str(uuid4()),
            "expected_revision": body["revision"],
            "step_id": body["view"]["step_id"],
        }
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                client.post,
                f"/todo-workflows/{workflow_id}/suggestions",
                json=payload,
                headers=headers,
            )
            try:
                assert provider_started.wait(timeout=5)
                assert (
                    client.get(
                        f"/todo-workflows/{workflow_id}", headers=headers
                    ).status_code
                    == 200
                )
                cancelled, _ = advance_workflow_request(
                    client, headers, body, {"action": "cancel"}
                )
                assert cancelled.status_code == 200
            finally:
                release_provider.set()
            result = pending.result(timeout=5)

        assert result.status_code == 409
        assert result.json()["detail"]["code"] == "stale_suggestion"
        with session_factory() as verification_session:
            row = verification_session.scalar(
                select(WorkflowSuggestionRequestRow).where(
                    WorkflowSuggestionRequestRow.request_id
                    == UUID(payload["request_id"])
                )
            )
            assert row is not None
            assert row.proposed_titles == []
        assert client.get(
            f"/todo-workflows/{workflow_id}/suggestions", headers=headers
        ).status_code == 404
        assert client.get("/todos", headers=headers).json() == []


def test_pending_and_superseded_suggestions_return_conflicts(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    first_started = Event()
    second_started = Event()
    release_provider = Event()
    calls = 0

    async def deferred(_goal: str, _config: object) -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        (first_started if calls == 1 else second_started).set()
        await asyncio.to_thread(release_provider.wait)
        return ("Choose a date", "Invite guests")

    with TestClient(create_app(session_factory, suggestion_callable=deferred)) as client:
        headers = auth_headers(client)
        started, _ = start_workflow_request(client, headers)
        offered, _ = advance_workflow_request(
            client,
            headers,
            started.json(),
            {"action": "answer_multiple_steps", "answer": True},
        )
        collecting, _ = advance_workflow_request(
            client,
            headers,
            offered.json(),
            {"action": "answer_multiple_steps", "answer": True},
        )
        body = collecting.json()
        path = f"/todo-workflows/{body['workflow_id']}/suggestions"
        old_payload = {
            "request_id": str(uuid4()),
            "expected_revision": body["revision"],
            "step_id": body["view"]["step_id"],
        }
        new_payload = {**old_payload, "request_id": str(uuid4())}
        with ThreadPoolExecutor(max_workers=2) as executor:
            old_request = executor.submit(
                client.post, path, json=old_payload, headers=headers
            )
            try:
                assert first_started.wait(timeout=5)
                in_progress = client.post(
                    path, json=old_payload, headers=headers
                )
                assert in_progress.status_code == 409
                assert in_progress.json()["detail"]["code"] == "suggestion_in_progress"

                new_request = executor.submit(
                    client.post, path, json=new_payload, headers=headers
                )
                assert second_started.wait(timeout=5)
                superseded = client.post(
                    path, json=old_payload, headers=headers
                )
                assert superseded.status_code == 409
                assert superseded.json()["detail"]["code"] == "stale_suggestion"
            finally:
                release_provider.set()
            assert old_request.result(timeout=5).status_code == 409
            assert new_request.result(timeout=5).status_code == 201
        assert calls == 2


def test_missing_configuration_is_saved_as_failed_suggestion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    offered, _ = advance_workflow_request(
        client, headers, started.json(), {"action": "answer_multiple_steps", "answer": True}
    )
    collecting, _ = advance_workflow_request(
        client, headers, offered.json(), {"action": "answer_multiple_steps", "answer": True}
    )
    body = collecting.json()
    payload = {
        "request_id": str(uuid4()),
        "expected_revision": body["revision"],
        "step_id": body["view"]["step_id"],
    }

    response = client.post(
        f"/todo-workflows/{body['workflow_id']}/suggestions",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "not_configured"

    saved = client.get(
        f"/todo-workflows/{body['workflow_id']}/suggestions", headers=headers
    )
    assert saved.status_code == 200
    assert saved.json()["status"] == "failed"
    assert saved.json()["error_code"] == "not_configured"


def test_other_owner_suggestions_are_missing(
    suggestion_client: tuple[TestClient, list[str]],
) -> None:
    client, _calls = suggestion_client
    alice_headers = auth_headers(client, "alice")
    bob_headers = auth_headers(client, "bob")
    started, _ = start_workflow_request(client, alice_headers)
    workflow_id = started.json()["workflow_id"]
    assert (
        client.get(f"/todo-workflows/{workflow_id}/suggestions", headers=bob_headers)
        .status_code
        == 404
    )


def test_yes_branch_collects_then_confirms_three_todos(
    client: TestClient,
) -> None:
    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    workflow_id = last["workflow_id"]

    collecting, _ = advance_workflow_request(
        client, headers, last, {"action": "answer_multiple_steps", "answer": True}
    )
    assert collecting.status_code == 200
    last = collecting.json()
    assert last["revision"] == 1
    assert last["state"] == "OFFER_BREAKDOWN"
    assert last["view"]["question"] == (
        "Would you like to split it into smaller todos?"
    )
    assert last["view"]["step_id"] == f"{workflow_id}:OFFER_BREAKDOWN"

    breakdown, _ = advance_workflow_request(
        client, headers, last, {"action": "answer_multiple_steps", "answer": True}
    )
    last = breakdown.json()
    assert last["revision"] == 2
    assert last["state"] == "COLLECT_TASKS"
    assert last["view"] == {
        "type": "task_breakdown",
        "step_id": f"{workflow_id}:COLLECT_TASKS",
        "title": "Break it into smaller todos",
        "min_titles": 2,
        "max_titles": 10,
    }

    review, _ = advance_workflow_request(
        client,
        headers,
        last,
        {
            "action": "submit_tasks",
            "titles": ["Send invitations", "Buy decorations", "Book venue"],
        },
    )
    assert review.status_code == 200
    last = review.json()
    assert last["revision"] == 3
    assert last["state"] == "REVIEW"
    assert last["context"]["proposed_todo_titles"] == [
        "Send invitations",
        "Buy decorations",
        "Book venue",
    ]
    assert last["view"] == {
        "type": "review",
        "step_id": f"{workflow_id}:REVIEW",
        "title": "Review your plan",
        "proposed_titles": ["Send invitations", "Buy decorations", "Book venue"],
    }

    completed, _ = advance_workflow_request(
        client, headers, last, {"action": "confirm"}
    )
    assert completed.status_code == 200
    last = completed.json()
    assert last["revision"] == 4
    assert last["state"] == "COMPLETED"
    assert last["definition_version"] == 1
    assert last["view_contract_version"] == 1
    created = last["result"]["created_todos"]
    assert [todo["title"] for todo in created] == [
        "Send invitations",
        "Buy decorations",
        "Book venue",
    ]
    assert [todo["completed"] for todo in created] == [False, False, False]
    assert last["view"] == {
        "type": "completion",
        "step_id": f"{workflow_id}:COMPLETED",
        "title": "Plan complete",
        "outcome": "completed",
        "created_todos": created,
    }

    todos = client.get("/todos", headers=headers).json()
    assert [todo["title"] for todo in todos] == [
        "Send invitations",
        "Buy decorations",
        "Book venue",
    ]


def test_action_replay_returns_identical_200_without_second_effect(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    request_id = uuid4()

    first, _ = advance_workflow_request(
        client,
        headers,
        last,
        {"action": "answer_multiple_steps", "answer": True},
        request_id=request_id,
    )
    assert first.status_code == 200
    replay, _ = advance_workflow_request(
        client,
        headers,
        last,
        {"action": "answer_multiple_steps", "answer": True},
        request_id=request_id,
    )

    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.json()["revision"] == 1
    with session_factory() as verification_session:
        row = verification_session.scalar(
            select(WorkflowRow).where(
                WorkflowRow.public_id == UUID(last["workflow_id"])
            )
        )
        assert row is not None
        assert row.revision == 1


def test_action_request_id_reuse_with_different_payload_conflicts(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    request_id = uuid4()
    first, _ = advance_workflow_request(
        client,
        headers,
        last,
        {"action": "answer_multiple_steps", "answer": True},
        request_id=request_id,
    )
    assert first.status_code == 200

    response, _ = advance_workflow_request(
        client,
        headers,
        last,
        {"action": "answer_multiple_steps", "answer": False},
        request_id=request_id,
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "request_id_reused",
            "message": "This request ID was already used with different details.",
        }
    }
    with session_factory() as verification_session:
        row = verification_session.scalar(
            select(WorkflowRow).where(
                WorkflowRow.public_id == UUID(last["workflow_id"])
            )
        )
        assert row is not None
        assert row.revision == 1
        assert row.state == "OFFER_BREAKDOWN"


@pytest.mark.parametrize(
    "tamper",
    [
        {"expected_revision": 999},
        {"step_id": "00000000-0000-0000-0000-000000000000:ASSESS_TASK"},
    ],
)
def test_stale_revision_or_step_conflicts_without_mutation(
    client: TestClient, session_factory: sessionmaker[Session], tamper: dict[str, object]
) -> None:
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    view = last["view"]
    assert isinstance(view, dict)
    payload = {
        "request_id": str(uuid4()),
        "expected_revision": last["revision"],
        "step_id": view["step_id"],
        "action": {"action": "answer_multiple_steps", "answer": True},
    }
    payload.update(tamper)

    response = client.post(
        f"/todo-workflows/{last['workflow_id']}/actions",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "stale_step",
            "message": "This plan changed. Reload it and try again.",
        }
    }
    with session_factory() as verification_session:
        row = verification_session.scalar(
            select(WorkflowRow).where(
                WorkflowRow.public_id == UUID(last["workflow_id"])
            )
        )
        assert row is not None
        assert row.revision == 0
        assert row.state == "ASSESS_TASK"


def test_offer_no_reviews_original_with_views(
    client: TestClient,
) -> None:
    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    workflow_id = last["workflow_id"]

    offered, _ = advance_workflow_request(
        client, headers, last, {"action": "answer_multiple_steps", "answer": True}
    )
    assert offered.status_code == 200
    last = offered.json()
    assert last["state"] == "OFFER_BREAKDOWN"
    assert last["context"] == {
        "involves_multiple_steps": True,
        "proposed_todo_titles": [],
    }
    assert last["view"]["question"] == (
        "Would you like to split it into smaller todos?"
    )
    assert last["view"]["step_id"] == f"{workflow_id}:OFFER_BREAKDOWN"

    review, _ = advance_workflow_request(
        client, headers, last, {"action": "answer_multiple_steps", "answer": False}
    )
    last = review.json()
    assert review.status_code == 200
    assert last["state"] == "REVIEW"
    assert last["context"] == {
        "involves_multiple_steps": True,
        "proposed_todo_titles": ["Plan birthday party"],
    }
    assert last["view"] == {
        "type": "review",
        "step_id": f"{workflow_id}:REVIEW",
        "title": "Review your plan",
        "proposed_titles": ["Plan birthday party"],
    }
    assert client.get("/todos", headers=headers).json() == []


def test_no_branch_reviews_and_creates_original_title(
    client: TestClient,
) -> None:
    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()

    review, _ = advance_workflow_request(
        client, headers, last, {"action": "answer_multiple_steps", "answer": False}
    )
    last = review.json()
    assert review.status_code == 200
    assert last["state"] == "REVIEW"
    assert last["context"]["proposed_todo_titles"] == ["Plan birthday party"]

    completed, _ = advance_workflow_request(
        client, headers, last, {"action": "confirm"}
    )
    last = completed.json()
    assert completed.status_code == 200
    assert [todo["title"] for todo in last["result"]["created_todos"]] == [
        "Plan birthday party"
    ]
    assert [todo["title"] for todo in client.get("/todos", headers=headers).json()] == [
        "Plan birthday party"
    ]


@pytest.mark.parametrize("path", ["assess", "offer", "collect", "review"])
def test_cancel_from_each_active_state(client: TestClient, path: str) -> None:
    headers = auth_headers(client)
    first, _ = start_workflow_request(client, headers)
    second, _ = start_workflow_request(client, headers)
    third, _ = start_workflow_request(client, headers)
    fourth, _ = start_workflow_request(client, headers)
    bodies = [first.json(), second.json(), third.json(), fourth.json()]
    answered, _ = advance_workflow_request(
        client, headers, bodies[1], {"action": "answer_multiple_steps", "answer": True}
    )
    bodies[1] = answered.json()
    for index in (2, 3):
        answered, _ = advance_workflow_request(
            client,
            headers,
            bodies[index],
            {"action": "answer_multiple_steps", "answer": True},
        )
        bodies[index] = answered.json()
        offered, _ = advance_workflow_request(
            client,
            headers,
            bodies[index],
            {"action": "answer_multiple_steps", "answer": True},
        )
        bodies[index] = offered.json()
    submitted, _ = advance_workflow_request(
        client,
        headers,
        bodies[3],
        {"action": "submit_tasks", "titles": ["Send invitations", "Buy cake"]},
    )
    bodies[3] = submitted.json()
    target = {"assess": 0, "offer": 1, "collect": 2, "review": 3}[path]

    cancelled, _ = advance_workflow_request(
        client, headers, bodies[target], {"action": "cancel"}
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "CANCELLED"
    assert cancelled.json()["result"] is None
    assert client.get("/todos", headers=headers).json() == []


def test_offer_rejects_misplaced_actions(
    client: TestClient,
) -> None:
    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    offered, _ = advance_workflow_request(
        client, headers, last, {"action": "answer_multiple_steps", "answer": True}
    )
    last = offered.json()

    for action in (
        {"action": "submit_tasks", "titles": ["Send invitations", "Buy cake"]},
        {"action": "confirm"},
    ):
        response, _ = advance_workflow_request(client, headers, last, action)

        assert response.status_code == 409
        assert response.json() == {
            "detail": {
                "code": "invalid_action",
                "message": "Action is not valid for the current workflow state.",
            }
        }


def test_known_view_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        YesNoWorkflowView.model_validate(
            {
                "type": "yes_no",
                "step_id": f"{uuid4()}:ASSESS_TASK",
                "title": "Plan birthday party",
                "question": "Does this task involve multiple steps?",
                "actions": [
                    {"id": "yes", "label": "Yes"},
                    {"id": "no", "label": "No"},
                ],
                "extra": True,
            }
        )


@pytest.mark.parametrize("state", ["COMPLETED", "CANCELLED"])
@pytest.mark.parametrize(
    "action",
    [
        {"action": "answer_multiple_steps", "answer": True},
        {"action": "submit_tasks", "titles": ["Send invitations", "Buy cake"]},
        {"action": "confirm"},
        {"action": "cancel"},
    ],
)
def test_terminal_states_reject_every_action(
    client: TestClient, state: str, action: dict[str, object]
) -> None:
    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    if state == "COMPLETED":
        reviewed, _ = advance_workflow_request(
            client, headers, last, {"action": "answer_multiple_steps", "answer": False}
        )
        last = reviewed.json()
        confirmed, _ = advance_workflow_request(
            client, headers, last, {"action": "confirm"}
        )
        last = confirmed.json()
    else:
        cancelled, _ = advance_workflow_request(
            client, headers, last, {"action": "cancel"}
        )
        last = cancelled.json()

    response, _ = advance_workflow_request(client, headers, last, action)

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "terminal_workflow",
            "message": "Todo workflow is already terminal.",
        }
    }


def test_unsupported_definition_conflicts_on_fetch_discovery_and_advance(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    workflow_id = last["workflow_id"]
    with session_factory() as setup_session:
        setup_session.execute(
            update(WorkflowRow)
            .where(WorkflowRow.public_id == UUID(workflow_id))
            .values(definition_version=2)
        )
        setup_session.commit()

    fetched = client.get(f"/todo-workflows/{workflow_id}", headers=headers)
    assert fetched.status_code == 409
    assert fetched.json() == {
        "detail": {
            "code": "unsupported_workflow_definition",
            "message": "This plan uses an unsupported workflow definition.",
        }
    }

    discovered = client.get("/todo-workflows", headers=headers)
    assert discovered.status_code == 409
    assert discovered.json()["detail"]["code"] == "unsupported_workflow_definition"

    request_id = uuid4()
    view = last["view"]
    assert isinstance(view, dict)
    advanced = client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={
            "request_id": str(request_id),
            "expected_revision": last["revision"],
            "step_id": view["step_id"],
            "action": {"action": "answer_multiple_steps", "answer": True},
        },
        headers=headers,
    )
    assert advanced.status_code == 409
    assert advanced.json()["detail"]["code"] == "unsupported_workflow_definition"

    with session_factory() as restore_session:
        restore_session.execute(
            update(WorkflowRow)
            .where(WorkflowRow.public_id == UUID(workflow_id))
            .values(definition_version=1)
        )
        restore_session.commit()
    retried = client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={
            "request_id": str(request_id),
            "expected_revision": last["revision"],
            "step_id": view["step_id"],
            "action": {"action": "answer_multiple_steps", "answer": True},
        },
        headers=headers,
    )
    assert retried.status_code == 200
    assert retried.json()["revision"] == last["revision"] + 1
    assert retried.json()["state"] == "OFFER_BREAKDOWN"


def test_revision_exhausted_rejects_new_action_but_replays_recorded(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    request_id = uuid4()
    first, _ = advance_workflow_request(
        client,
        headers,
        last,
        {"action": "answer_multiple_steps", "answer": True},
        request_id=request_id,
    )
    assert first.status_code == 200
    accepted = first.json()
    with session_factory() as setup_session:
        setup_session.execute(
            update(WorkflowRow)
            .where(WorkflowRow.public_id == UUID(last["workflow_id"]))
            .values(revision=MAX_REVISION)
        )
        setup_session.commit()

    fresh_view = accepted["view"]
    assert isinstance(fresh_view, dict)
    fresh = client.post(
        f"/todo-workflows/{last['workflow_id']}/actions",
        json={
            "request_id": str(uuid4()),
            "expected_revision": MAX_REVISION,
            "step_id": fresh_view["step_id"],
            "action": {"action": "answer_multiple_steps", "answer": True},
        },
        headers=headers,
    )
    assert fresh.status_code == 409
    assert fresh.json() == {
        "detail": {
            "code": "revision_exhausted",
            "message": "This plan has reached its revision limit.",
        }
    }

    replay, _ = advance_workflow_request(
        client,
        headers,
        last,
        {"action": "answer_multiple_steps", "answer": True},
        request_id=request_id,
    )
    assert replay.status_code == 200
    assert replay.json() == accepted


def test_corrupt_recorded_snapshot_returns_503_on_replay(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.workflow_repository import WorkflowStartRequestRow

    headers = auth_headers(client)
    request_id = uuid4()
    first, _ = start_workflow_request(client, headers, request_id=request_id)
    assert first.status_code == 201
    with session_factory() as setup_session:
        setup_session.execute(
            update(WorkflowStartRequestRow)
            .where(WorkflowStartRequestRow.request_id == request_id)
            .values(accepted_snapshot={"bogus": True})
        )
        setup_session.commit()

    replay, _ = start_workflow_request(client, headers, request_id=request_id)

    assert replay.status_code == 503
    assert replay.json() == {"detail": "Database unavailable."}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "Plan birthday party"},
        {"request_id": "not-a-uuid", "title": "Plan birthday party"},
        {"request_id": str(uuid4()), "title": ""},
        {"request_id": str(uuid4()), "title": "x" * 121},
        {"request_id": str(uuid4()), "title": "Bad\x00title"},
        {"request_id": str(uuid4()), "title": 42},
        {"request_id": str(uuid4()), "title": "Known", "extra": 1},
    ],
)
def test_start_rejects_invalid_envelopes(client: TestClient, payload: object) -> None:
    headers = auth_headers(client)

    response = client.post("/todo-workflows", json=payload, headers=headers)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "answer_multiple_steps", "answer": "yes"},
        {"action": "answer_multiple_steps"},
        {"action": "submit_tasks", "titles": ["Only one"]},
        {"action": "submit_tasks", "titles": [f"T{index}" for index in range(11)]},
        {"action": "submit_tasks", "titles": ["Fine", "   "]},
        {"action": "dance"},
        {},
        {"action": "confirm", "extra": True},
    ],
)
def test_actions_reject_malformed_bodies(client: TestClient, payload: object) -> None:
    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    view = last["view"]
    assert isinstance(view, dict)

    response = client.post(
        f"/todo-workflows/{last['workflow_id']}/actions",
        json={
            "request_id": str(uuid4()),
            "expected_revision": last["revision"],
            "step_id": view["step_id"],
            "action": payload,
        },
        headers=headers,
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "envelope",
    [
        {"expected_revision": 0, "step_id": "step", "action": {"action": "cancel"}},
        {"request_id": str(uuid4()), "step_id": "step", "action": {"action": "cancel"}},
        {"request_id": str(uuid4()), "expected_revision": 0, "action": {"action": "cancel"}},
        {
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "step_id": "step",
            "action": {"action": "cancel"},
            "extra": True,
        },
        {"request_id": "not-a-uuid", "expected_revision": 0, "step_id": "step", "action": {"action": "cancel"}},
        {"request_id": str(uuid4()), "expected_revision": True, "step_id": "step", "action": {"action": "cancel"}},
        {"request_id": str(uuid4()), "expected_revision": 1.5, "step_id": "step", "action": {"action": "cancel"}},
        {"request_id": str(uuid4()), "expected_revision": "0", "step_id": "step", "action": {"action": "cancel"}},
        {"request_id": str(uuid4()), "expected_revision": -1, "step_id": "step", "action": {"action": "cancel"}},
        {"request_id": str(uuid4()), "expected_revision": MAX_REVISION + 1, "step_id": "step", "action": {"action": "cancel"}},
        {"request_id": str(uuid4()), "expected_revision": 0, "step_id": 42, "action": {"action": "cancel"}},
    ],
)
def test_action_envelope_rejects_strict_shape_violations(
    client: TestClient, envelope: dict[str, object]
) -> None:
    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    workflow_id = started.json()["workflow_id"]

    response = client.post(
        f"/todo-workflows/{workflow_id}/actions", json=envelope, headers=headers
    )

    assert response.status_code == 422


def test_confirm_in_assess_task_returns_409_without_mutation(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.todo_repository import TodoRow
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    workflow_id = last["workflow_id"]
    public_id = UUID(workflow_id)

    def read_row() -> tuple[object, ...]:
        with session_factory() as verification_session:
            row = verification_session.scalar(
                select(WorkflowRow).where(WorkflowRow.public_id == public_id)
            )
            assert row is not None
            todos = verification_session.scalars(select(TodoRow)).all()
            return (
                row.state,
                row.title,
                row.involves_multiple_steps,
                tuple(row.proposed_todo_titles),
                row.completion_result,
                row.revision,
                tuple(todo.public_id for todo in todos),
            )

    before = read_row()

    response, _ = advance_workflow_request(
        client, headers, last, {"action": "confirm"}
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "invalid_action",
            "message": "Action is not valid for the current workflow state.",
        }
    }
    assert read_row() == before


def test_other_owner_workflows_are_missing(client: TestClient) -> None:
    alice_headers = auth_headers(client, "alice")
    bob_headers = auth_headers(client, "bob")
    started, _ = start_workflow_request(client, alice_headers)
    last = started.json()
    workflow_id = last["workflow_id"]

    assert client.get(f"/todo-workflows/{workflow_id}", headers=bob_headers).status_code == 404
    response, _ = advance_workflow_request(
        client, bob_headers, last, {"action": "cancel"}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Todo workflow not found."}
    assert (
        client.get(f"/todo-workflows/{workflow_id}", headers=alice_headers).json()["state"]
        == "ASSESS_TASK"
    )


def test_discovery_returns_active_workflows_newest_first(client: TestClient) -> None:
    headers = auth_headers(client)

    empty = client.get("/todo-workflows", headers=headers)
    assert empty.status_code == 200
    assert empty.json() == {"items": []}

    explicit = client.get("/todo-workflows?status=active", headers=headers)
    assert explicit.status_code == 200
    assert explicit.json() == {"items": []}

    first, _ = start_workflow_request(client, headers, title="First plan")
    second, _ = start_workflow_request(client, headers, title="Second plan")
    third, _ = start_workflow_request(client, headers, title="Third plan")
    first_body, second_body, third_body = first.json(), second.json(), third.json()

    discovered = client.get("/todo-workflows", headers=headers)
    assert discovered.status_code == 200
    items = discovered.json()["items"]
    assert [item["workflow_id"] for item in items] == [
        third_body["workflow_id"],
        second_body["workflow_id"],
        first_body["workflow_id"],
    ]
    assert items[0] == third_body
    for item in items:
        assert item["revision"] == 0
        assert item["definition_version"] == 1
        assert item["view_contract_version"] == 1

    confirmed, _ = advance_workflow_request(
        client, headers, first_body, {"action": "answer_multiple_steps", "answer": False}
    )
    done, _ = advance_workflow_request(
        client, headers, confirmed.json(), {"action": "confirm"}
    )
    assert done.json()["state"] == "COMPLETED"
    cancelled, _ = advance_workflow_request(
        client, headers, second_body, {"action": "cancel"}
    )
    assert cancelled.json()["state"] == "CANCELLED"

    remaining = client.get("/todo-workflows", headers=headers).json()["items"]
    assert [item["workflow_id"] for item in remaining] == [third_body["workflow_id"]]


def test_discovery_rejects_unknown_status_and_hides_other_owners(
    client: TestClient,
) -> None:
    alice_headers = auth_headers(client, "alice")
    bob_headers = auth_headers(client, "bob")
    started, _ = start_workflow_request(client, alice_headers)
    assert started.status_code == 201

    assert client.get("/todo-workflows?status=all", headers=alice_headers).status_code == 422
    assert client.get("/todo-workflows?status=", headers=alice_headers).status_code == 422
    assert client.get("/todo-workflows", headers=bob_headers).json() == {"items": []}
    assert (
        client.get("/todo-workflows?status=active", headers=bob_headers).json()
        == {"items": []}
    )


def test_discovery_reads_without_side_effects(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()

    first = client.get("/todo-workflows", headers=headers)
    second = client.get("/todo-workflows", headers=headers)

    assert first.json() == second.json()
    with session_factory() as verification_session:
        row = verification_session.scalar(
            select(WorkflowRow).where(
                WorkflowRow.public_id == UUID(last["workflow_id"])
            )
        )
        assert row is not None
        assert row.revision == 0


def test_workflow_uuid_shapes(client: TestClient) -> None:
    headers = auth_headers(client)

    assert client.get("/todo-workflows/not-a-uuid", headers=headers).status_code == 422
    assert client.get(f"/todo-workflows/{uuid4()}", headers=headers).status_code == 404
    assert (
        client.post(
            "/todo-workflows/not-a-uuid/actions",
            json={
                "request_id": str(uuid4()),
                "expected_revision": 0,
                "step_id": "not-a-uuid:ASSESS_TASK",
                "action": {"action": "cancel"},
            },
            headers=headers,
        ).status_code
        == 422
    )


def test_workflow_routes_reject_unauthenticated(client: TestClient) -> None:
    request_id = str(uuid4())
    assert (
        client.post(
            "/todo-workflows",
            json={"request_id": request_id, "title": "Plan birthday party"},
        ).status_code
        == 401
    )
    assert client.get(f"/todo-workflows/{uuid4()}").status_code == 401
    assert client.get("/todo-workflows").status_code == 401
    assert client.get(f"/todo-workflows/{uuid4()}/suggestions").status_code == 401
    assert (
        client.post(
            f"/todo-workflows/{uuid4()}/suggestions",
            json={
                "request_id": request_id,
                "expected_revision": 2,
                "step_id": "step",
            },
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"/todo-workflows/{uuid4()}/actions",
            json={
                "request_id": request_id,
                "expected_revision": 0,
                "step_id": f"{uuid4()}:ASSESS_TASK",
                "action": {"action": "cancel"},
            },
        ).status_code
        == 401
    )


def test_progress_survives_fresh_client_without_side_effects(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.main import create_app

    headers = auth_headers(client)
    started, _ = start_workflow_request(client, headers)
    last = started.json()
    workflow_id = last["workflow_id"]
    answered, _ = advance_workflow_request(
        client, headers, last, {"action": "answer_multiple_steps", "answer": True}
    )
    last = answered.json()
    offered, _ = advance_workflow_request(
        client, headers, last, {"action": "answer_multiple_steps", "answer": True}
    )
    assert offered.json()["state"] == "COLLECT_TASKS"
    before_todos = client.get("/todos", headers=headers).json()

    with TestClient(create_app(session_factory)) as fresh_client:
        fetched = fresh_client.get(f"/todo-workflows/{workflow_id}", headers=headers)

    assert fetched.status_code == 200
    assert fetched.json()["state"] == "COLLECT_TASKS"
    assert fetched.json()["revision"] == 2
    assert fetched.json()["context"]["proposed_todo_titles"] == []
    assert client.get("/todos", headers=headers).json() == before_todos


def test_workflow_routes_return_503_when_database_unavailable() -> None:
    from sqlalchemy import Engine

    from app.database import create_database_engine, create_session_factory

    engine: Engine = create_database_engine(
        "postgresql+psycopg://todo_test:todo_test@127.0.0.1:65534/todo_test"
    )
    session_factory = create_session_factory(engine)
    request_id = str(uuid4())
    workflow_id = uuid4()
    try:
        with TestClient(create_app(session_factory)) as bad_client:
            dead_headers = {"Authorization": "Bearer " + "0" * 64}
            assert (
                bad_client.post(
                    "/todo-workflows",
                    json={"request_id": request_id, "title": "Plan birthday party"},
                    headers=dead_headers,
                ).status_code
                == 503
            )
            assert (
                bad_client.get(
                    f"/todo-workflows/{workflow_id}", headers=dead_headers
                ).status_code
                == 503
            )
            assert (
                bad_client.get("/todo-workflows", headers=dead_headers).status_code
                == 503
            )
            assert (
                bad_client.post(
                    f"/todo-workflows/{workflow_id}/actions",
                    json={
                        "request_id": request_id,
                        "expected_revision": 0,
                        "step_id": f"{workflow_id}:ASSESS_TASK",
                        "action": {"action": "cancel"},
                    },
                    headers=dead_headers,
                ).status_code
                == 503
            )
            assert (
                bad_client.post(
                    f"/todo-workflows/{workflow_id}/suggestions",
                    json={
                        "request_id": request_id,
                        "expected_revision": 2,
                        "step_id": f"{workflow_id}:COLLECT_TASKS",
                    },
                    headers=dead_headers,
                ).status_code
                == 503
            )
            assert (
                bad_client.get(
                    f"/todo-workflows/{workflow_id}/suggestions",
                    headers=dead_headers,
                ).status_code
                == 503
            )
    finally:
        engine.dispose()


def test_openapi_publishes_workflow_contract(client: TestClient) -> None:
    document = client.get("/openapi.json").json()

    assert set(document["paths"]) >= {
        "/todo-workflows",
        "/todo-workflows/{workflow_id}",
        "/todo-workflows/{workflow_id}/actions",
        "/todo-workflows/{workflow_id}/suggestions",
    }
    discovery = document["paths"]["/todo-workflows"]["get"]
    assert (
        discovery["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/TodoWorkflowList"
    )
    start = document["paths"]["/todo-workflows"]["post"]
    assert (
        start["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/TodoWorkflowStart"
    )
    assert (
        start["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/TodoWorkflowResponse"
    )
    assert set(document["components"]["schemas"]["TodoWorkflowStart"]["required"]) == {
        "request_id",
        "title",
    }
    actions = document["paths"]["/todo-workflows/{workflow_id}/actions"]["post"]
    assert (
        actions["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/TodoWorkflowActionRequest"
    )
    envelope_required = set(
        document["components"]["schemas"]["TodoWorkflowActionRequest"]["required"]
    )
    assert envelope_required == {"request_id", "expected_revision", "step_id", "action"}
    action_schema = document["components"]["schemas"]["TodoWorkflowActionRequest"][
        "properties"
    ]["action"]
    assert action_schema["discriminator"]["propertyName"] == "action"
    assert action_schema["discriminator"]["mapping"] == {
        "answer_multiple_steps": "#/components/schemas/AnswerMultipleStepsAction",
        "submit_tasks": "#/components/schemas/SubmitTasksAction",
        "confirm": "#/components/schemas/ConfirmAction",
        "cancel": "#/components/schemas/CancelAction",
    }
    assert {
        "AnswerMultipleStepsAction",
        "SubmitTasksAction",
        "ConfirmAction",
        "CancelAction",
    } <= set(document["components"]["schemas"])
    suggestions = document["paths"][
        "/todo-workflows/{workflow_id}/suggestions"
    ]
    assert (
        suggestions["post"]["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/TodoWorkflowSuggestionRequest"
    )
    assert (
        suggestions["post"]["responses"]["201"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/TodoWorkflowSuggestionResponse"
    )
    assert set(
        document["components"]["schemas"]["TodoWorkflowSuggestionRequest"][
            "required"
        ]
    ) == {"request_id", "expected_revision", "step_id"}
    assert set(
        document["components"]["schemas"]["TodoWorkflowSuggestionResponse"][
            "required"
        ]
    ) == {
        "contract_version",
        "workflow_id",
        "request_id",
        "base_revision",
        "step_id",
        "status",
        "proposed_titles",
        "error_code",
    }
    response_required = set(
        document["components"]["schemas"]["TodoWorkflowResponse"]["required"]
    )
    assert {
        "workflow_id",
        "revision",
        "definition_version",
        "view_contract_version",
        "state",
        "title",
        "context",
        "result",
        "view",
    } <= response_required
    view_schema = document["components"]["schemas"]["TodoWorkflowResponse"][
        "properties"
    ]["view"]
    assert view_schema["discriminator"] == {
        "propertyName": "type",
        "mapping": {
            "yes_no": "#/components/schemas/YesNoWorkflowView",
            "task_breakdown": "#/components/schemas/TaskBreakdownWorkflowView",
            "review": "#/components/schemas/ReviewWorkflowView",
            "completion": "#/components/schemas/CompletionWorkflowView",
        },
    }
    assert len(view_schema["oneOf"]) == 4
    assert "TodoWorkflowResponse" in document["components"]["schemas"]
    assert {"type": "http", "scheme": "bearer"} in document["components"][
        "securitySchemes"
    ].values()


def test_workflow_preflight_allows_bearer_and_json(client: TestClient) -> None:
    for path, method in [
        ("/todo-workflows", "POST"),
        ("/todo-workflows", "GET"),
        ("/todo-workflows/00000000-0000-0000-0000-000000000000", "GET"),
        (
            "/todo-workflows/00000000-0000-0000-0000-000000000000/actions",
            "POST",
        ),
        (
            "/todo-workflows/00000000-0000-0000-0000-000000000000/suggestions",
            "POST",
        ),
        (
            "/todo-workflows/00000000-0000-0000-0000-000000000000/suggestions",
            "GET",
        ),
    ]:
        response = client.options(
            path,
            headers={
                "Origin": "http://localhost:8081",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "Content-Type, Authorization",
            },
        )

        assert response.status_code == 200
        assert method in response.headers["access-control-allow-methods"]
        allow_headers = response.headers["access-control-allow-headers"].lower()
        assert "content-type" in allow_headers
        assert "authorization" in allow_headers
