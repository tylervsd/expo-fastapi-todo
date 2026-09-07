from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app


@pytest.fixture
def client(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> Iterator[TestClient]:
    del database_session
    with TestClient(create_app(session_factory)) as test_client:
        yield test_client


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


def test_start_returns_assess_task_without_todos(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    headers = auth_headers(client)

    response = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"workflow_id", "state", "title", "context", "result"}
    assert body["state"] == "ASSESS_TASK"
    assert body["title"] == "Plan birthday party"
    assert body["context"] == {
        "involves_multiple_steps": None,
        "proposed_todo_titles": [],
    }
    assert body["result"] is None
    assert client.get("/todos", headers=headers).json() == []


def test_yes_branch_collects_then_confirms_three_todos(
    client: TestClient,
) -> None:
    headers = auth_headers(client)
    workflow_id = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    ).json()["workflow_id"]

    collecting = client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={"action": "answer_multiple_steps", "answer": True},
        headers=headers,
    )
    assert collecting.status_code == 200
    assert collecting.json()["state"] == "COLLECT_TASKS"

    review = client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={
            "action": "submit_tasks",
            "titles": ["Send invitations", "Buy decorations", "Book venue"],
        },
        headers=headers,
    )
    assert review.status_code == 200
    assert review.json()["state"] == "REVIEW"
    assert review.json()["context"]["proposed_todo_titles"] == [
        "Send invitations",
        "Buy decorations",
        "Book venue",
    ]

    completed = client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={"action": "confirm"},
        headers=headers,
    )
    assert completed.status_code == 200
    assert completed.json()["state"] == "COMPLETED"
    created = completed.json()["result"]["created_todos"]
    assert [todo["title"] for todo in created] == [
        "Send invitations",
        "Buy decorations",
        "Book venue",
    ]
    assert [todo["completed"] for todo in created] == [False, False, False]

    todos = client.get("/todos", headers=headers).json()
    assert [todo["title"] for todo in todos] == [
        "Send invitations",
        "Buy decorations",
        "Book venue",
    ]


def test_no_branch_reviews_and_creates_original_title(
    client: TestClient,
) -> None:
    headers = auth_headers(client)
    workflow_id = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    ).json()["workflow_id"]

    review = client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={"action": "answer_multiple_steps", "answer": False},
        headers=headers,
    )
    assert review.status_code == 200
    assert review.json()["state"] == "REVIEW"
    assert review.json()["context"]["proposed_todo_titles"] == ["Plan birthday party"]

    completed = client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={"action": "confirm"},
        headers=headers,
    )
    assert completed.status_code == 200
    assert [todo["title"] for todo in completed.json()["result"]["created_todos"]] == [
        "Plan birthday party"
    ]
    assert [todo["title"] for todo in client.get("/todos", headers=headers).json()] == [
        "Plan birthday party"
    ]


@pytest.mark.parametrize("path", ["assess", "collect", "review"])
def test_cancel_from_each_active_state(client: TestClient, path: str) -> None:
    headers = auth_headers(client)
    first = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    ).json()["workflow_id"]
    second = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    ).json()["workflow_id"]
    third = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    ).json()["workflow_id"]
    client.post(
        f"/todo-workflows/{second}/actions",
        json={"action": "answer_multiple_steps", "answer": True},
        headers=headers,
    )
    client.post(
        f"/todo-workflows/{third}/actions",
        json={"action": "answer_multiple_steps", "answer": True},
        headers=headers,
    )
    client.post(
        f"/todo-workflows/{third}/actions",
        json={"action": "submit_tasks", "titles": ["Send invitations", "Buy cake"]},
        headers=headers,
    )
    target = {"assess": first, "collect": second, "review": third}[path]

    cancelled = client.post(
        f"/todo-workflows/{target}/actions",
        json={"action": "cancel"},
        headers=headers,
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "CANCELLED"
    assert cancelled.json()["result"] is None
    assert client.get("/todos", headers=headers).json() == []


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
    workflow_id = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    ).json()["workflow_id"]
    if state == "COMPLETED":
        client.post(
            f"/todo-workflows/{workflow_id}/actions",
            json={"action": "answer_multiple_steps", "answer": False},
            headers=headers,
        )
        client.post(
            f"/todo-workflows/{workflow_id}/actions",
            json={"action": "confirm"},
            headers=headers,
        )
    else:
        client.post(
            f"/todo-workflows/{workflow_id}/actions",
            json={"action": "cancel"},
            headers=headers,
        )

    response = client.post(
        f"/todo-workflows/{workflow_id}/actions", json=action, headers=headers
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Todo workflow is already terminal."}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "x" * 121},
        {"title": "Bad\x00title"},
        {"title": 42},
        {"title": "Known", "extra": 1},
    ],
)
def test_start_rejects_invalid_titles(client: TestClient, payload: object) -> None:
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
    workflow_id = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    ).json()["workflow_id"]

    response = client.post(
        f"/todo-workflows/{workflow_id}/actions", json=payload, headers=headers
    )

    assert response.status_code == 422


def test_confirm_in_assess_task_returns_409_without_mutation(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from sqlalchemy import select

    from app.todo_repository import TodoRow
    from app.workflow_repository import WorkflowRow

    headers = auth_headers(client)
    workflow_id = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    ).json()["workflow_id"]
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
                tuple(todo.public_id for todo in todos),
            )

    before = read_row()

    response = client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={"action": "confirm"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Action is not valid for the current workflow state."
    }
    assert read_row() == before


def test_other_owner_workflows_are_missing(client: TestClient) -> None:
    alice_headers = auth_headers(client, "alice")
    bob_headers = auth_headers(client, "bob")
    workflow_id = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=alice_headers
    ).json()["workflow_id"]

    assert client.get(f"/todo-workflows/{workflow_id}", headers=bob_headers).status_code == 404
    response = client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={"action": "cancel"},
        headers=bob_headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Todo workflow not found."}
    assert (
        client.get(f"/todo-workflows/{workflow_id}", headers=alice_headers).json()["state"]
        == "ASSESS_TASK"
    )


def test_workflow_uuid_shapes(client: TestClient) -> None:
    headers = auth_headers(client)

    assert client.get("/todo-workflows/not-a-uuid", headers=headers).status_code == 422
    assert client.get(f"/todo-workflows/{uuid4()}", headers=headers).status_code == 404
    assert (
        client.post(
            "/todo-workflows/not-a-uuid/actions",
            json={"action": "cancel"},
            headers=headers,
        ).status_code
        == 422
    )


def test_workflow_routes_reject_unauthenticated(client: TestClient) -> None:
    assert client.post("/todo-workflows", json={"title": "Plan birthday party"}).status_code == 401
    assert client.get(f"/todo-workflows/{uuid4()}").status_code == 401
    assert (
        client.post(f"/todo-workflows/{uuid4()}/actions", json={"action": "cancel"}).status_code
        == 401
    )


def test_progress_survives_fresh_client_without_side_effects(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    from app.main import create_app

    headers = auth_headers(client)
    workflow_id = client.post(
        "/todo-workflows", json={"title": "Plan birthday party"}, headers=headers
    ).json()["workflow_id"]
    client.post(
        f"/todo-workflows/{workflow_id}/actions",
        json={"action": "answer_multiple_steps", "answer": True},
        headers=headers,
    )
    before_todos = client.get("/todos", headers=headers).json()

    with TestClient(create_app(session_factory)) as fresh_client:
        fetched = fresh_client.get(f"/todo-workflows/{workflow_id}", headers=headers)

    assert fetched.status_code == 200
    assert fetched.json()["state"] == "COLLECT_TASKS"
    assert fetched.json()["context"]["proposed_todo_titles"] == []
    assert client.get("/todos", headers=headers).json() == before_todos


def test_workflow_routes_return_503_when_database_unavailable() -> None:
    from sqlalchemy import Engine

    from app.database import create_database_engine, create_session_factory

    engine: Engine = create_database_engine(
        "postgresql+psycopg://todo_test:todo_test@127.0.0.1:65534/todo_test"
    )
    session_factory = create_session_factory(engine)
    try:
        with TestClient(create_app(session_factory)) as bad_client:
            dead_headers = {"Authorization": "Bearer " + "0" * 64}
            assert (
                bad_client.post(
                    "/todo-workflows",
                    json={"title": "Plan birthday party"},
                    headers=dead_headers,
                ).status_code
                == 503
            )
            assert (
                bad_client.get(
                    f"/todo-workflows/{uuid4()}", headers=dead_headers
                ).status_code
                == 503
            )
            assert (
                bad_client.post(
                    f"/todo-workflows/{uuid4()}/actions",
                    json={"action": "cancel"},
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
    }
    start = document["paths"]["/todo-workflows"]["post"]
    assert (
        start["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/TodoWorkflowStart"
    )
    assert (
        start["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/TodoWorkflowResponse"
    )
    actions = document["paths"]["/todo-workflows/{workflow_id}/actions"]["post"]
    action_schema = actions["requestBody"]["content"]["application/json"]["schema"]
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
    assert "TodoWorkflowResponse" in document["components"]["schemas"]
    assert {"type": "http", "scheme": "bearer"} in document["components"][
        "securitySchemes"
    ].values()


def test_workflow_preflight_allows_bearer_and_json(client: TestClient) -> None:
    for path, method in [
        ("/todo-workflows", "POST"),
        ("/todo-workflows/00000000-0000-0000-0000-000000000000", "GET"),
        (
            "/todo-workflows/00000000-0000-0000-0000-000000000000/actions",
            "POST",
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
