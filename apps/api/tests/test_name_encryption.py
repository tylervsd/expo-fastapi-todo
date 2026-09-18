import json
from unittest.mock import Mock
from uuid import uuid4

import google_crc32c
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth_repository import UserRow
from app.main import create_app
from app.name_encryption import NameCipher, NameUnavailable
from e2e.name_kms import FakeNameKms

KEY = "projects/example-project/locations/us-west1/keyRings/fullstack-profile/cryptoKeys/real-name"
NAME = "Élodie 王"
PASSWORD = "long-enough-password"


def test_sdk_integrity_aad_and_no_retry():
    fake = FakeNameKms()
    client = Mock(wraps=fake)
    cipher = NameCipher(KEY, client=client)
    owner = uuid4()
    ciphertext = cipher.encrypt(owner, NAME)
    assert NAME.encode() not in ciphertext
    assert cipher.decrypt(owner, ciphertext) == NAME
    request = client.encrypt.call_args.kwargs
    assert (
        request["request"]["additional_authenticated_data"]
        == f"fullstack:users:real_name:v1:{owner}".encode()
    )
    assert request["request"]["plaintext_crc32c"] == google_crc32c.value(NAME.encode())
    assert request["retry"] is None
    assert request["timeout"] == 3
    assert client.decrypt.call_args.kwargs["request"][
        "ciphertext_crc32c"
    ] == google_crc32c.value(ciphertext)
    with pytest.raises(NameUnavailable):
        cipher.decrypt(uuid4(), ciphertext)
    fake.primary = 2
    assert cipher.decrypt(owner, ciphertext) == NAME
    fake.disabled.add(1)
    with pytest.raises(NameUnavailable):
        cipher.decrypt(owner, ciphertext)


@pytest.mark.parametrize(
    "field",
    [
        "verified_plaintext_crc32c",
        "verified_additional_authenticated_data_crc32c",
        "ciphertext_crc32c",
        "name",
    ],
)
def test_rejects_corrupted_encrypt_response(field):
    fake = FakeNameKms()

    def corrupt(**kwargs):
        response = fake.encrypt(**kwargs)
        setattr(response, field, "wrong-key" if field == "name" else 0)
        return response

    with pytest.raises(NameUnavailable):
        NameCipher(KEY, client=Mock(encrypt=corrupt)).encrypt(uuid4(), NAME)


def test_rejects_corrupted_decrypt_response():
    fake = FakeNameKms()
    owner = uuid4()
    ciphertext = NameCipher(KEY, client=fake).encrypt(owner, NAME)

    def corrupt(**kwargs):
        response = fake.decrypt(**kwargs)
        response.plaintext_crc32c = 0
        return response

    with pytest.raises(NameUnavailable):
        NameCipher(KEY, client=Mock(decrypt=corrupt)).decrypt(owner, ciphertext)


@pytest.fixture
def named_client(database_session, session_factory):
    fake = FakeNameKms()
    with TestClient(
        create_app(session_factory, name_cipher=NameCipher(KEY, client=fake))
    ) as client:
        yield client, fake


def register(client, username="alice", name=NAME):
    return client.post(
        "/auth/signup",
        content=json.dumps(
            {"username": username, "password": PASSWORD, "real_name": name}
        ),
        headers={"Content-Type": "application/json"},
    )


def login(client, username="alice", password=PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def test_signup_persists_only_ciphertext_then_login_and_restore(
    named_client, session_factory, capsys
):
    client, fake = named_client
    created = register(client)
    assert created.status_code == 201
    assert set(created.json()) == {"id", "username"}
    assert fake.decrypt_calls == 0
    with session_factory() as session:
        row = session.scalar(select(UserRow).where(UserRow.username == "alice"))
        assert row.real_name_ciphertext
        assert NAME.encode() not in row.real_name_ciphertext
    signed_in = login(client)
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["real_name"] == NAME
    token = signed_in.json()["token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["real_name"] == NAME
    assert me.headers["cache-control"] == "no-store"
    assert signed_in.headers["cache-control"] == "no-store"
    captured = capsys.readouterr()
    assert NAME not in captured.out + captured.err


def test_encrypt_failure_creates_no_account_and_never_discards_name(
    named_client, session_factory
):
    client, fake = named_client
    fake.unavailable = True
    assert register(client).status_code == 503
    with session_factory() as session:
        assert session.scalar(select(UserRow)) is None
    with TestClient(create_app(session_factory)) as unconfigured:
        assert register(unconfigured).status_code == 503
        assert register(unconfigured, name=None).status_code == 201


def test_authentication_before_decrypt_and_outage_keeps_session(named_client):
    client, fake = named_client
    assert register(client).status_code == 201
    assert login(client, password="wrong-password").status_code == 401
    assert client.get("/auth/me").status_code == 401
    assert fake.decrypt_calls == 0
    fake.unavailable = True
    signed_in = login(client)
    assert signed_in.status_code == 200
    assert "real_name" not in signed_in.json()["user"]
    headers = {"Authorization": f"Bearer {signed_in.json()['token']}"}
    assert client.get("/auth/me", headers=headers).status_code == 200
    fake.unavailable = False
    assert client.get("/auth/me", headers=headers).json()["real_name"] == NAME


def test_swapped_ciphertext_does_not_expose_other_name(named_client, session_factory):
    client, _ = named_client
    assert register(client, "alice", "Alice Example").status_code == 201
    assert register(client, "bob", "Bob Example").status_code == 201
    with session_factory.begin() as session:
        alice = session.scalar(select(UserRow).where(UserRow.username == "alice"))
        bob = session.scalar(select(UserRow).where(UserRow.username == "bob"))
        bob.real_name_ciphertext = alice.real_name_ciphertext
    assert login(client, "alice").json()["user"]["real_name"] == "Alice Example"
    assert "real_name" not in login(client, "bob").json()["user"]


@pytest.mark.parametrize(
    "name", [" ", "x" * 101, "private\x00name", "private\nname", 42, "bad\ud800"]
)
def test_invalid_name_rejected_without_echoing_input(named_client, name):
    client, fake = named_client
    response = register(client, name=name)
    assert response.status_code == 422
    assert all(
        "input" not in error and "ctx" not in error
        for error in response.json()["detail"]
    )
    assert PASSWORD not in response.text
    assert fake.values == {}


def test_bad_key_configuration_fails_before_adc(monkeypatch):
    monkeypatch.setenv("REAL_NAME_KMS_KEY", "not-a-key")
    with pytest.raises(ValueError):
        create_app()
