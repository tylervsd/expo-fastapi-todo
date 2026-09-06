from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_database_engine, create_session_factory
from app.main import create_app
from app.todo_repository import TodoRow


@pytest.fixture
def client(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> Iterator[TestClient]:
    del database_session
    with TestClient(create_app(session_factory)) as test_client:
        yield test_client


def test_new_app_starts_with_empty_ordered_collection(client: TestClient) -> None:
    response = client.get("/todos")

    assert response.status_code == 200
    assert response.json() == []


def test_todos_persist_across_app_instances(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    with TestClient(create_app(session_factory)) as first_client:
        response = first_client.post("/todos", json={"title": "Private"})
        assert response.status_code == 201
        created = response.json()

    with TestClient(create_app(session_factory)) as second_client:
        response = second_client.get("/todos")

    assert response.status_code == 200
    assert response.json() == [created]


def test_create_returns_canonical_active_todo_with_uuid(
    client: TestClient,
) -> None:
    response = client.post(
        "/todos",
        json={"title": "\uFEFF\u2003Buy milk\u2029"},
    )

    assert response.status_code == 201
    todo = response.json()
    UUID(todo["id"])
    assert todo == {
        "id": todo["id"],
        "title": "Buy milk",
        "completed": False,
    }


def test_duplicate_titles_keep_insertion_order_and_distinct_ids(
    client: TestClient,
) -> None:
    first = client.post("/todos", json={"title": "Repeat"})
    second = client.post("/todos", json={"title": "Repeat"})

    assert first.status_code == 201
    assert second.status_code == 201
    first_todo = first.json()
    second_todo = second.json()
    assert first_todo["id"] != second_todo["id"]

    response = client.get("/todos")

    assert response.status_code == 200
    assert response.json() == [first_todo, second_todo]


def test_create_rejects_nul_title(client: TestClient) -> None:
    response = client.post("/todos", json={"title": "Contains\u0000Nul"})

    assert response.status_code == 422


def test_create_rejects_unpaired_surrogate_without_encoding_failure(
    client: TestClient,
) -> None:
    response = client.post(
        "/todos",
        content=b'{"title":"\\ud800"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_patch_sets_requested_boolean_and_preserves_order(
    client: TestClient,
) -> None:
    first = client.post("/todos", json={"title": "First"}).json()
    second = client.post("/todos", json={"title": "Second"}).json()

    for completed in (True, True, False):
        response = client.patch(
            f"/todos/{first['id']}",
            json={"completed": completed},
        )

        assert response.status_code == 200
        assert response.json() == {
            "id": first["id"],
            "title": "First",
            "completed": completed,
        }
        assert [todo["id"] for todo in client.get("/todos").json()] == [
            first["id"],
            second["id"],
        ]


def test_post_and_patch_commit_before_independent_session_observes_them(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    created = client.post("/todos", json={"title": "Committed"})

    assert created.status_code == 201
    public_id = UUID(created.json()["id"])
    with session_factory() as verification_session:
        row = verification_session.scalar(
            select(TodoRow).where(TodoRow.public_id == public_id)
        )
        assert row is not None
        assert row.title == "Committed"
        assert row.completed is False

    updated = client.patch(f"/todos/{public_id}", json={"completed": True})

    assert updated.status_code == 200
    with session_factory() as verification_session:
        row = verification_session.scalar(
            select(TodoRow).where(TodoRow.public_id == public_id)
        )
        assert row is not None
        assert row.completed is True


@pytest.mark.parametrize("completed", [0, 1, "true", "false"])
def test_patch_rejects_non_boolean_completed_values(
    client: TestClient,
    completed: object,
) -> None:
    todo = client.post("/todos", json={"title": "Strict"}).json()
    response = client.patch(
        f"/todos/{todo['id']}",
        json={"completed": completed},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [{}, {"completed": True, "extra": False}, {"completed": None}, []],
)
def test_patch_rejects_malformed_bodies(
    client: TestClient,
    payload: object,
) -> None:
    todo = client.post("/todos", json={"title": "Strict"}).json()
    response = client.patch(f"/todos/{todo['id']}", json=payload)

    assert response.status_code == 422


def test_patch_rejects_malformed_uuid(client: TestClient) -> None:
    response = client.patch("/todos/not-a-uuid", json={"completed": True})

    assert response.status_code == 422


def test_patch_returns_exact_not_found_contract_for_absent_uuid(
    client: TestClient,
) -> None:
    response = client.patch(f"/todos/{uuid4()}", json={"completed": True})

    assert response.status_code == 404
    assert response.json() == {"detail": "Todo not found."}


def test_openapi_publishes_todo_paths_and_schema_references(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    todos_path = document["paths"]["/todos"]
    patch_path = document["paths"]["/todos/{todo_id}"]
    assert set(todos_path) == {"get", "post"}
    assert set(patch_path) == {"patch"}
    get_schema = todos_path["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert get_schema["type"] == "array"
    assert get_schema["items"] == {"$ref": "#/components/schemas/Todo"}
    assert (
        todos_path["post"]["requestBody"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/TodoCreate"
    )
    assert (
        todos_path["post"]["responses"]["201"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/Todo"
    )
    assert (
        patch_path["patch"]["requestBody"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/TodoCompletedUpdate"
    )
    assert (
        patch_path["patch"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/Todo"
    )
    assert {"Todo", "TodoCreate", "TodoCompletedUpdate"} <= set(
        document["components"]["schemas"]
    )


def test_cors_allows_health_get_preflight(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:8081"
    )
    assert "GET" in response.headers["access-control-allow-methods"]


@pytest.mark.parametrize(
    ("path", "method"),
    [("/todos", "POST"), ("/todos/00000000-0000-0000-0000-000000000000", "PATCH")],
)
def test_cors_allows_todo_mutation_preflight(
    client: TestClient,
    path: str,
    method: str,
) -> None:
    response = client.options(
        path,
        headers={
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "Content-Type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:8081"
    )
    assert method in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_cors_does_not_allow_unlisted_origin(client: TestClient) -> None:
    response = client.options(
        "/todos",
        headers={
            "Origin": "http://localhost:9999",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_todo_routes_return_exact_503_when_database_is_unavailable() -> None:
    engine: Engine = create_database_engine(
        "postgresql+psycopg://todo_test:todo_test@127.0.0.1:65534/todo_test"
    )
    session_factory = create_session_factory(engine)
    try:
        with TestClient(create_app(session_factory)) as client:
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}
            for response in (
                client.get("/todos"),
                client.post("/todos", json={"title": "Unavailable"}),
                client.patch(f"/todos/{uuid4()}", json={"completed": True}),
            ):
                assert response.status_code == 503
                assert response.json() == {"detail": "Database unavailable."}
    finally:
        engine.dispose()
