import asyncio
import base64
import json
import logging
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from webhooks import client_app, public_app, verify_signature
from webhooks import test_ivr_app as ivr_app


def sign(private, body, stamp="1000"):
    return base64.b64encode(private.sign(stamp.encode() + b"|" + body)).decode()


def test_exact_bytes_and_freshness():
    private = Ed25519PrivateKey.generate()
    body = b'{"data": {"id": "event-1"}}'
    signature = sign(private, body)
    for now in (700, 1000, 1300):
        verify_signature(body, "1000", signature, private.public_key(), now=now)
    for bad_body, stamp, sig, now in (
        (body + b" ", "1000", signature, 1000),
        (body, "1000", signature, 1301),
        (body, "1000", signature, 699),
        (body, "1000", "not base64!", 1000),
        (body, "1000", sign(Ed25519PrivateKey.generate(), body), 1000),
        (body, "no", signature, 1000),
        (body, "+1000", signature, 1000),
        (body, " 1000", signature, 1000),
        (body, "１０００", signature, 1000),
        (body, "", signature, 1000),
        (body, "9" * 5000, signature, 1000),
    ):
        with pytest.raises(ValueError):
            verify_signature(bad_body, stamp, sig, private.public_key(), now=now)


@pytest.fixture
def private(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv(
        "TELNYX_PUBLIC_KEY",
        base64.b64encode(key.public_key().public_bytes_raw()).decode(),
    )
    return key


def headers(private, body, stamp=None):
    stamp = str(int(time.time())) if stamp is None else stamp
    return {
        "telnyx-timestamp": stamp,
        "telnyx-signature-ed25519": sign(private, body, stamp),
    }


def envelope(**changes):
    return json.dumps(
        {
            "data": {
                "id": "evt-1",
                "event_type": "call.initiated",
                "payload": {},
                **changes,
            }
        }
    ).encode()


@pytest.mark.parametrize("app", [client_app, ivr_app, public_app])
@pytest.mark.parametrize("setting", [None, "", "invalid!", "c2VjcmV0", "é"])
def test_startup_fails_closed(monkeypatch, app, setting):
    monkeypatch.delenv("TELNYX_PUBLIC_KEY", raising=False)
    if setting is not None:
        monkeypatch.setenv("TELNYX_PUBLIC_KEY", setting)
    with pytest.raises(RuntimeError) as error, TestClient(app):
        pass
    assert str(error.value) == "Invalid TELNYX_PUBLIC_KEY configuration"
    assert error.value.__suppress_context__


@pytest.mark.parametrize(
    "app,role,other",
    [(client_app, "client", "test-ivr"), (ivr_app, "test-ivr", "client")],
)
def test_independent_apps(private, app, role, other):
    body = envelope()
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok", "role": role}
        assert (
            client.post(
                f"/webhooks/{role}", content=body, headers=headers(private, body)
            ).status_code
            == 204
        )
        assert client.post(f"/webhooks/{other}").status_code == 404
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404


def test_public_routes_and_private_logs(private, caplog):
    body = envelope(
        id="evt-1\nforged",
        event_type="unknown.event",
        payload={"phone": "+15555550123", "secret": "SECRET_SENTINEL"},
    )
    caplog.set_level(logging.INFO, logger="ivr.webhooks")
    with TestClient(public_app) as client:
        for role in ("client", "test-ivr"):
            for _ in range(2):
                response = client.post(
                    f"/webhooks/{role}", content=body, headers=headers(private, body)
                )
                assert response.status_code == 204
                assert response.content == b""
        for path in (
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/calls",
            "/arbitrary",
        ):
            assert client.get(path).status_code == 404
    records = [r.getMessage() for r in caplog.records if r.name == "ivr.webhooks"]
    assert len(records) == 4
    assert [json.loads(r) for r in records] == [
        {"role": role, "event_id": "evt-1\nforged", "event_type": "unknown.event"}
        for role in ("client", "client", "test-ivr", "test-ivr")
    ]
    assert all("\n" not in r for r in records)
    assert "SECRET_SENTINEL" not in caplog.text
    assert "+15555550123" not in caplog.text


@pytest.mark.parametrize("path", ["/webhooks/client", "/webhooks/test-ivr"])
def test_rejected_authentication(private, path, caplog):
    body = envelope()
    valid = headers(private, body)
    invalid = [
        {},
        {"telnyx-timestamp": valid["telnyx-timestamp"]},
        {"telnyx-signature-ed25519": valid["telnyx-signature-ed25519"]},
        {**valid, "telnyx-signature-ed25519": "!"},
        {**valid, "telnyx-timestamp": "nonsense"},
        headers(Ed25519PrivateKey.generate(), body),
        headers(private, body, str(int(time.time()) - 301)),
        headers(private, body, str(int(time.time()) + 302)),
        headers(private, body + b" "),
        list(valid.items()) + [("telnyx-timestamp", valid["telnyx-timestamp"])],
        list(valid.items())
        + [("telnyx-signature-ed25519", valid["telnyx-signature-ed25519"])],
    ]
    caplog.set_level(logging.INFO, logger="ivr.webhooks")
    with TestClient(public_app) as client:
        for request_headers in invalid:
            response = client.post(path, content=body, headers=request_headers)
            assert response.status_code == 401
            assert response.json() == {"detail": "Invalid authentication"}
        assert client.post(path, content=b"not json").status_code == 401
    assert not [r for r in caplog.records if r.name == "ivr.webhooks"]


@pytest.mark.parametrize(
    "body",
    [
        b' {"data":{"id":"e","event_type":"t","payload":{"n":NaN}}}',
        b"not json",
        b"\xff",
        b"null",
        b"[]",
        b"{}",
        b'{"data":null}',
        envelope(id=""),
        envelope(id=1),
        envelope(id="x" * 257),
        envelope(event_type=""),
        envelope(event_type=False),
        envelope(event_type="x" * 129),
        envelope(payload=[]),
        envelope(payload=None),
        b'{"data":{"id":"e","event_type":"t"}}',
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_invalid_signed_envelope(private, body):
    with TestClient(public_app) as client:
        response = client.post(
            "/webhooks/test-ivr", content=body, headers=headers(private, body)
        )
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid envelope"}


def test_body_boundary(private):
    body = envelope(id="x" * 256, event_type="x" * 128)
    body += b" " * (65536 - len(body))
    with TestClient(public_app) as client:
        assert (
            client.post(
                "/webhooks/client", content=body, headers=headers(private, body)
            ).status_code
            == 204
        )
        request = client.build_request(
            "POST", "/webhooks/client", content=iter([b"x" * 32768, b"x" * 32769])
        )
        assert "content-length" not in request.headers
        assert client.send(request).status_code == 413


@pytest.mark.parametrize("length_headers", [[], [(b"content-length", b"1")]])
def test_stream_stops_at_limit(private, length_headers):
    # ASGI chunks prove early stopping; TestClient joins iterator chunks internally.
    async def exercise():
        chunks = iter([b"x" * 32768, b"x" * 32769])
        sent = []

        async def receive():
            return {"type": "http.request", "body": next(chunks), "more_body": True}

        async def send(message):
            sent.append(message)

        with TestClient(public_app):
            await public_app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/webhooks/client",
                    "raw_path": b"/webhooks/client",
                    "query_string": b"",
                    "root_path": "",
                    "headers": length_headers,
                    "server": ("test", 80),
                    "client": ("test", 1),
                },
                receive,
                send,
            )
        assert sent[0]["status"] == 413

    asyncio.run(exercise())
