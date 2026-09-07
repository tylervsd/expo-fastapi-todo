from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.main import create_app
from app.passwords import DUMMY_PASSWORD_HASH


@pytest.fixture
def client(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> Iterator[TestClient]:
    del database_session
    with TestClient(create_app(session_factory)) as test_client:
        yield test_client


def signup(client: TestClient, username: str = "alice") -> dict[str, object]:
    response = client.post(
        "/auth/signup", json={"username": username, "password": "long-enough-password"}
    )
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, username: str = "alice") -> dict[str, object]:
    response = client.post(
        "/auth/login", json={"username": username, "password": "long-enough-password"}
    )
    assert response.status_code == 200
    return response.json()


def test_signup_then_login_then_me_then_logout(client: TestClient) -> None:
    created = signup(client)
    assert set(created) == {"id", "username"}

    session = login(client)
    assert set(session) == {"token", "expires_at", "user"}
    assert session["user"] == created
    headers = {"Authorization": f"Bearer {session['token']}"}

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json() == created

    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.post("/auth/logout", headers=headers).status_code == 204

    gone = client.get("/auth/me", headers=headers)
    assert gone.status_code == 401
    assert gone.json() == {"detail": "Not authenticated."}


def test_signup_rejects_duplicate_username(client: TestClient) -> None:
    signup(client)
    response = client.post(
        "/auth/signup", json={"username": "alice", "password": "long-enough-password"}
    )

    assert response.status_code == 422


def test_login_rejects_unknown_user_and_wrong_password(client: TestClient) -> None:
    signup(client)

    for payload in (
        {"username": "nobody", "password": "long-enough-password"},
        {"username": "alice", "password": "wrong-password-ok"},
    ):
        response = client.post("/auth/login", json=payload)

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid username or password."}


def test_unknown_user_login_verifies_against_dummy_hash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    verified: list[tuple[str, str]] = []

    def record_verify(password: str, password_hash: str) -> bool:
        verified.append((password, password_hash))
        return False

    monkeypatch.setattr("app.main.verify_password", record_verify)
    response = client.post(
        "/auth/login",
        json={"username": "nobody", "password": "long-enough-password"},
    )

    assert response.status_code == 401
    assert verified == [("long-enough-password", DUMMY_PASSWORD_HASH)]


def test_todos_and_me_reject_unauthenticated_shapes(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me").json() == {"detail": "Not authenticated."}
    assert client.get("/todos").status_code == 401
    assert client.post("/todos", json={"title": "Nope"}).status_code == 401
    assert (
        client.patch(f"/todos/{uuid4()}", json={"completed": True}).status_code == 401
    )
    assert client.delete(f"/todos/{uuid4()}").status_code == 401
    assert (
        client.get("/todos", headers={"Authorization": "NotBearer abc"}).status_code
        == 401
    )


def test_cross_user_todos_are_missing_not_forbidden(client: TestClient) -> None:
    signup(client, "alice")
    signup(client, "bob")
    alice_headers = {"Authorization": f"Bearer {login(client, 'alice')['token']}"}
    bob_headers = {"Authorization": f"Bearer {login(client, 'bob')['token']}"}

    created = client.post("/todos", json={"title": "Alice row"}, headers=alice_headers)
    assert created.status_code == 201
    todo_id = created.json()["id"]

    assert client.get("/todos", headers=bob_headers).json() == []
    assert (
        client.patch(
            f"/todos/{todo_id}", json={"completed": True}, headers=bob_headers
        ).status_code
        == 404
    )
    assert client.delete(f"/todos/{todo_id}", headers=bob_headers).status_code == 404
    assert client.get("/todos", headers=alice_headers).json() == [created.json()]
