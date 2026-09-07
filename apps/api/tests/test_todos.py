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


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    client.post(
        "/auth/signup",
        json={"username": "alice", "password": "long-enough-password"},
    )
    login = client.post(
        "/auth/login",
        json={"username": "alice", "password": "long-enough-password"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_new_app_starts_with_empty_ordered_collection(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/todos", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_todos_persist_across_app_instances(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    with TestClient(create_app(session_factory)) as first_client:
        first_client.post(
            "/auth/signup",
            json={"username": "alice", "password": "long-enough-password"},
        )
        login = first_client.post(
            "/auth/login",
            json={"username": "alice", "password": "long-enough-password"},
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        response = first_client.post(
            "/todos", json={"title": "Private"}, headers=headers
        )
        assert response.status_code == 201
        created = response.json()

    with TestClient(create_app(session_factory)) as second_client:
        response = second_client.get("/todos", headers=headers)

    assert response.status_code == 200
    assert response.json() == [created]


def test_create_returns_canonical_active_todo_with_uuid(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/todos",
        json={"title": "\ufeff\u2003Buy milk\u2029"},
        headers=auth_headers,
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
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    first = client.post("/todos", json={"title": "Repeat"}, headers=auth_headers)
    second = client.post("/todos", json={"title": "Repeat"}, headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 201
    first_todo = first.json()
    second_todo = second.json()
    assert first_todo["id"] != second_todo["id"]

    response = client.get("/todos", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == [first_todo, second_todo]


def test_create_rejects_nul_title(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/todos", json={"title": "Contains\u0000Nul"}, headers=auth_headers
    )

    assert response.status_code == 422


def test_create_rejects_unpaired_surrogate_without_encoding_failure(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/todos",
        content=b'{"title":"\\ud800"}',
        headers={"Content-Type": "application/json", **auth_headers},
    )

    assert response.status_code == 422


def test_patch_sets_requested_boolean_and_preserves_order(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    first = client.post("/todos", json={"title": "First"}, headers=auth_headers).json()
    second = client.post(
        "/todos", json={"title": "Second"}, headers=auth_headers
    ).json()

    for completed in (True, True, False):
        response = client.patch(
            f"/todos/{first['id']}",
            json={"completed": completed},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json() == {
            "id": first["id"],
            "title": "First",
            "completed": completed,
        }
        assert [
            todo["id"] for todo in client.get("/todos", headers=auth_headers).json()
        ] == [
            first["id"],
            second["id"],
        ]


def test_post_and_patch_commit_before_independent_session_observes_them(
    client: TestClient,
    session_factory: sessionmaker[Session],
    auth_headers: dict[str, str],
) -> None:
    created = client.post("/todos", json={"title": "Committed"}, headers=auth_headers)

    assert created.status_code == 201
    public_id = UUID(created.json()["id"])
    with session_factory() as verification_session:
        row = verification_session.scalar(
            select(TodoRow).where(TodoRow.public_id == public_id)
        )
        assert row is not None
        assert row.title == "Committed"
        assert row.completed is False

    updated = client.patch(
        f"/todos/{public_id}", json={"completed": True}, headers=auth_headers
    )

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
    auth_headers: dict[str, str],
) -> None:
    todo = client.post("/todos", json={"title": "Strict"}, headers=auth_headers).json()
    response = client.patch(
        f"/todos/{todo['id']}",
        json={"completed": completed},
        headers=auth_headers,
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"completed": True, "extra": False},
        {"completed": None},
        {"title": "Known", "completed": None},
        {"title": None, "completed": True},
        [],
    ],
)
def test_patch_rejects_malformed_bodies(
    client: TestClient,
    payload: object,
    auth_headers: dict[str, str],
) -> None:
    todo = client.post("/todos", json={"title": "Strict"}, headers=auth_headers).json()
    response = client.patch(f"/todos/{todo['id']}", json=payload, headers=auth_headers)

    assert response.status_code == 422


def test_patch_rejects_malformed_uuid(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.patch(
        "/todos/not-a-uuid", json={"completed": True}, headers=auth_headers
    )

    assert response.status_code == 422


def test_patch_returns_exact_not_found_contract_for_absent_uuid(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.patch(
        f"/todos/{uuid4()}", json={"completed": True}, headers=auth_headers
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Todo not found."}


def test_openapi_publishes_todo_paths_and_schema_references(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert set(document["paths"]) >= {
        "/todos",
        "/todos/{todo_id}",
        "/auth/signup",
        "/auth/login",
        "/auth/logout",
        "/auth/me",
    }
    todos_path = document["paths"]["/todos"]
    patch_path = document["paths"]["/todos/{todo_id}"]
    assert set(todos_path) == {"get", "post"}
    assert set(patch_path) == {"patch", "delete"}
    get_schema = todos_path["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert get_schema["type"] == "array"
    assert get_schema["items"] == {"$ref": "#/components/schemas/Todo"}
    assert (
        todos_path["post"]["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/TodoCreate"
    )
    assert (
        todos_path["post"]["responses"]["201"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/Todo"
    )
    assert (
        patch_path["patch"]["requestBody"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/TodoUpdate"
    )
    assert (
        patch_path["patch"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/Todo"
    )
    assert patch_path["delete"]["responses"]["204"]["description"] is not None
    assert {"Todo", "TodoCreate", "TodoUpdate"} <= set(
        document["components"]["schemas"]
    )
    assert {"UserPublic", "UserSignup", "UserLogin", "SessionResponse"} <= set(
        document["components"]["schemas"]
    )


def test_openapi_publishes_bearer_auth_for_protected_operations(client: TestClient) -> None:
    document = client.get("/openapi.json").json()

    assert document["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert document["paths"]["/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert document["paths"]["/todos"]["get"]["security"] == [{"HTTPBearer": []}]
    assert document["paths"]["/auth/logout"]["post"]["security"] == [{"HTTPBearer": []}]


def test_cors_allows_health_get_preflight(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ("http://localhost:8081")
    assert "GET" in response.headers["access-control-allow-methods"]


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/todos", "POST"),
        ("/todos/00000000-0000-0000-0000-000000000000", "PATCH"),
        ("/todos/00000000-0000-0000-0000-000000000000", "DELETE"),
    ],
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
            "Access-Control-Request-Headers": "Content-Type, Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ("http://localhost:8081")
    assert method in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


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
                client.post(
                    "/auth/signup",
                    json={"username": "alice", "password": "long-enough-password"},
                ),
                client.post(
                    "/auth/login",
                    json={"username": "alice", "password": "long-enough-password"},
                ),
                client.get("/todos", headers={"Authorization": "Bearer " + "0" * 64}),
                client.post(
                    "/todos",
                    json={"title": "Unavailable"},
                    headers={"Authorization": "Bearer " + "0" * 64},
                ),
                client.delete(
                    f"/todos/{uuid4()}",
                    headers={"Authorization": "Bearer " + "0" * 64},
                ),
                client.get("/auth/me", headers={"Authorization": "Bearer " + "0" * 64}),
                client.post(
                    "/auth/logout", headers={"Authorization": "Bearer " + "0" * 64}
                ),
            ):
                assert response.status_code == 503
                assert response.json() == {"detail": "Database unavailable."}
            for response in (
                client.get("/todos"),
                client.post("/todos", json={"title": "Unavailable"}),
            ):
                assert response.status_code == 401
                assert response.json() == {"detail": "Not authenticated."}
    finally:
        engine.dispose()


def test_patch_renames_title_and_preserves_order(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    first = client.post("/todos", json={"title": "First"}, headers=auth_headers).json()
    second = client.post(
        "/todos", json={"title": "Second"}, headers=auth_headers
    ).json()

    response = client.patch(
        f"/todos/{first['id']}", json={"title": "  Renamed  "}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": first["id"],
        "title": "Renamed",
        "completed": False,
    }
    assert [
        todo["id"] for todo in client.get("/todos", headers=auth_headers).json()
    ] == [
        first["id"],
        second["id"],
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "Both", "completed": True},
        {"title": None},
        {"completed": None},
        {"title": 42},
        {"completed": "true"},
        {"title": "Known", "extra": "rejected"},
    ],
)
def test_patch_rejects_non_exact_single_field(
    client: TestClient, payload: object, auth_headers: dict[str, str]
) -> None:
    todo = client.post("/todos", json={"title": "Strict"}, headers=auth_headers).json()
    response = client.patch(f"/todos/{todo['id']}", json=payload, headers=auth_headers)

    assert response.status_code == 422


def test_delete_returns_empty_204_and_removes_row(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post("/todos", json={"title": "Gone"}, headers=auth_headers).json()

    response = client.delete(f"/todos/{created['id']}", headers=auth_headers)

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/todos", headers=auth_headers).json() == []


def test_delete_returns_exact_not_found_for_absent_uuid(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.delete(f"/todos/{uuid4()}", headers=auth_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Todo not found."}


def test_repeated_delete_returns_exact_not_found(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post("/todos", json={"title": "Gone"}, headers=auth_headers).json()

    assert (
        client.delete(f"/todos/{created['id']}", headers=auth_headers).status_code
        == 204
    )
    repeated = client.delete(f"/todos/{created['id']}", headers=auth_headers)

    assert repeated.status_code == 404
    assert repeated.json() == {"detail": "Todo not found."}


def test_delete_rejects_malformed_uuid(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.delete("/todos/not-a-uuid", headers=auth_headers)

    assert response.status_code == 422


def test_delete_commits_before_independent_session_observes_it(
    client: TestClient,
    session_factory: sessionmaker[Session],
    auth_headers: dict[str, str],
) -> None:
    created = client.post("/todos", json={"title": "Committed"}, headers=auth_headers)

    assert created.status_code == 201
    public_id = UUID(created.json()["id"])

    deleted = client.delete(f"/todos/{public_id}", headers=auth_headers)

    assert deleted.status_code == 204
    with session_factory() as verification_session:
        assert (
            verification_session.scalar(
                select(TodoRow).where(TodoRow.public_id == public_id)
            )
            is None
        )
