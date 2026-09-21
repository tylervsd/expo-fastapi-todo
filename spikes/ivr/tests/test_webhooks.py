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
                "event_type": "unknown.event",
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
            == 200
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
                assert response.status_code == 200
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
            == 200
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


@pytest.fixture(autouse=True)
def fixture_settings(monkeypatch, offline_environment):
    monkeypatch.setenv("TELNYX_API_KEY", "test-only")
    monkeypatch.setenv("IVR_CONNECTION_ID", "app")


def test_client_needs_no_fixture_settings(private, monkeypatch):
    monkeypatch.delenv("TELNYX_API_KEY")
    monkeypatch.delenv("IVR_CONNECTION_ID")
    with TestClient(client_app) as client:
        assert client.get("/health").status_code == 200
    for app in (ivr_app, public_app):
        with (
            pytest.raises(RuntimeError, match="^Invalid fixture configuration$"),
            TestClient(app),
        ):
            pass


@pytest.mark.parametrize("app", [ivr_app, public_app])
def test_signed_dispatch_acknowledges_before_network(private, monkeypatch, app):
    from datetime import UTC, datetime
    from uuid import uuid4

    import webhooks

    sent = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(client, command):
        sent.append(command)
        if command.action == "answer":
            entered.set()
            await release.wait()

    monkeypatch.setattr(webhooks, "send_command", send)

    def body(kind, **payload):
        return envelope(
            id=str(uuid4()),
            event_type=kind,
            occurred_at=datetime.now(UTC).isoformat(),
            payload={
                "connection_id": "app",
                "call_control_id": "SECRET_CALL_TOKEN",
                "call_leg_id": "leg",
                "direction": "incoming",
                **payload,
            },
        )

    def post(client, data, path="/webhooks/test-ivr", signed=True):
        return client.post(
            path, content=data, headers=headers(private, data) if signed else {}
        )

    with TestClient(app) as client:
        initiated = body("call.initiated")
        assert post(client, initiated, signed=False).status_code == 401
        assert sent == []
        wrong_app = body("call.initiated", connection_id="other")
        assert post(client, wrong_app).status_code == 200
        assert sent == []
        malformed = body("call.initiated", call_control_id="")
        assert post(client, malformed).status_code == 400
        assert sent == []
        if app is public_app:
            assert post(client, initiated, path="/webhooks/client").status_code == 200
            assert sent == []
        response = post(client, initiated)
        assert response.status_code == 200 and response.content == b""
        client.portal.call(asyncio.wait_for, entered.wait(), 1)
        assert len(sent) == 1 and not release.is_set()
        assert post(client, initiated).status_code == 200
        answered = body("call.answered", client_state=sent[0].client_state)
        assert post(client, answered).status_code == 200
        client.portal.call(release.set)
        client.portal.call(app.state.ivr.drain)
        assert [cmd.action for cmd in sent] == ["answer", "gather_using_speak"]
        assert post(client, body("call.hangup")).status_code == 200
    assert app.state.ivr.active is None
    assert not app.state.ivr.tasks


def test_full_flow_logs_are_private(private, monkeypatch, caplog):
    from datetime import UTC, datetime
    from uuid import uuid4

    import webhooks
    from telnyx_commands import CommandError

    sent = []
    monkeypatch.setenv("IVR_CHALLENGE_OVERRIDE", "0742")

    async def send(client, command):
        sent.append(command)
        if command.action == "hangup":
            raise CommandError("uncertain")

    monkeypatch.setattr(webhooks, "send_command", send)
    caplog.set_level(logging.INFO)
    with TestClient(public_app) as client:

        def post(kind, **payload):
            body = envelope(
                id=str(uuid4()),
                event_type=kind,
                occurred_at=datetime.now(UTC).isoformat(),
                payload={
                    "connection_id": "app",
                    "call_control_id": "SECRET_CALL_TOKEN",
                    "call_leg_id": "leg",
                    "direction": "incoming",
                    "from": "+15555550123",
                    **payload,
                },
            )
            assert (
                client.post(
                    "/webhooks/test-ivr", content=body, headers=headers(private, body)
                ).status_code
                == 200
            )
            client.portal.call(public_app.state.ivr.drain)

        post("call.initiated")
        post("call.answered", client_state=sent[-1].client_state)
        for digits in ("1", "0742#", "1", "000123456#", "1"):
            post(
                "call.gather.ended",
                client_state=sent[-1].client_state,
                status="valid",
                digits=digits,
            )
        post("call.speak.ended", client_state=sent[-1].client_state, status="completed")
        post("call.hangup")
        for path in (
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/calls",
            "/scenario",
        ):
            assert client.get(path).status_code == 404
    for secret in (
        "test-only",
        "0742",
        "000123456",
        "1425.30",
        "+15555550123",
        "SECRET_CALL_TOKEN",
    ):
        assert secret not in caplog.text
    assert "result_spoken" in caplog.text
    assert "uncertain" in caplog.text


class RecordingCaller:
    def __init__(self):
        self.seen = []

    async def accept(self, data):
        self.seen.append(data)

    async def tick(self):
        pass

    async def close(self):
        pass


def _client_event(**payload):
    from datetime import UTC, datetime
    from uuid import uuid4

    return envelope(
        id=str(uuid4()),
        event_type="call.answered",
        occurred_at=datetime.now(UTC).isoformat(),
        payload={
            "connection_id": "client-app",
            "call_control_id": "call",
            "call_leg_id": "leg",
            **payload,
        },
    )


def test_client_route_dispatches_only_to_caller(private):
    import webhooks

    recorded = RecordingCaller()
    webhooks.public_app.state.caller = recorded
    try:
        body = _client_event()
        with TestClient(public_app) as client:
            response = client.post(
                "/webhooks/client", content=body, headers=headers(private, body)
            )
            assert response.status_code == 200
            assert response.content == b""
            fixture_body = envelope(
                id="evt-fixture", event_type="unknown.event", payload={}
            )
            assert (
                client.post(
                    "/webhooks/test-ivr",
                    content=fixture_body,
                    headers=headers(private, fixture_body),
                ).status_code
                == 200
            )
    finally:
        for name in ("caller", "caller_enabled"):
            if hasattr(webhooks.public_app.state, name):
                delattr(webhooks.public_app.state, name)
    assert len(recorded.seen) == 1
    assert recorded.seen[0]["payload"]["connection_id"] == "client-app"


def test_rejected_requests_mutate_neither(private):
    import webhooks

    recorded = RecordingCaller()
    webhooks.public_app.state.caller = recorded
    try:
        with TestClient(public_app) as client:
            valid = _client_event()
            assert client.post("/webhooks/client", content=valid).status_code == 401
            malformed = b"not json"
            assert (
                client.post(
                    "/webhooks/client",
                    content=malformed,
                    headers=headers(private, malformed),
                ).status_code
                == 400
            )
            big = b"x" * 65537
            assert (
                client.post(
                    "/webhooks/client",
                    content=big,
                    headers=headers(private, big),
                ).status_code
                == 413
            )
    finally:
        for name in ("caller", "caller_enabled"):
            if hasattr(webhooks.public_app.state, name):
                delattr(webhooks.public_app.state, name)
    assert recorded.seen == []


def test_client_app_receipt_only_without_caller(private):
    assert not hasattr(client_app.state, "caller")
    body = _client_event()
    with TestClient(client_app) as client:
        assert (
            client.post(
                "/webhooks/client", content=body, headers=headers(private, body)
            ).status_code
            == 200
        )
    assert not hasattr(client_app.state, "caller")


def _client_env(monkeypatch, connection="client-app"):
    monkeypatch.setenv("TELNYX_API_KEY", "test-only")
    monkeypatch.setenv("IVR_CONNECTION_ID", "fixture-app")
    monkeypatch.setenv("IVR_CLIENT_CONNECTION_ID", connection)
    monkeypatch.setenv("IVR_CLIENT_FROM_NUMBER", "+15555550100")
    monkeypatch.setenv("IVR_CLIENT_TO_NUMBER", "+15555550199")


def test_cli_lifespan_creates_and_clears_caller(private, monkeypatch):
    import webhooks

    _client_env(monkeypatch)
    webhooks.public_app.state.caller_enabled = True
    try:
        with TestClient(public_app) as client:
            assert webhooks.public_app.state.caller.exit_code is None
            body = _client_event()
            assert (
                client.post(
                    "/webhooks/client",
                    content=body,
                    headers=headers(private, body),
                ).status_code
                == 200
            )
    finally:
        for name in ("caller", "caller_enabled"):
            if hasattr(webhooks.public_app.state, name):
                delattr(webhooks.public_app.state, name)
    assert not hasattr(webhooks.public_app.state, "caller")
    assert not hasattr(webhooks.public_app.state, "caller_enabled")


def test_shutdown_still_closes_caller_and_http_when_fixture_close_fails(
    private, monkeypatch
):
    import httpx

    import webhooks

    _client_env(monkeypatch)
    caller_closed = []
    http_closed = []

    class BoomFixture:
        def __init__(self, *args, **kwargs):
            pass

        async def tick(self):
            pass

        async def close(self):
            raise RuntimeError("boom")

    class QuietCaller:
        _started = True

        def __init__(self, *args, **kwargs):
            pass

        async def tick(self):
            pass

        async def close(self):
            caller_closed.append(1)

    class RecordingClient(httpx.AsyncClient):
        async def aclose(self):
            http_closed.append(1)
            await super().aclose()

    monkeypatch.setattr(webhooks, "Fixture", BoomFixture)
    monkeypatch.setattr(webhooks, "Caller", QuietCaller)
    monkeypatch.setattr(webhooks.httpx, "AsyncClient", RecordingClient)
    webhooks.public_app.state.caller_enabled = True
    try:
        with pytest.raises(RuntimeError, match="boom"), TestClient(public_app):
            pass
    finally:
        for name in ("caller", "caller_enabled"):
            if hasattr(webhooks.public_app.state, name):
                delattr(webhooks.public_app.state, name)
    assert caller_closed == [1]
    assert http_closed != []


def test_combined_mode_requires_distinct_app_ids(private, monkeypatch):
    import webhooks

    _client_env(monkeypatch, connection="fixture-app")
    webhooks.public_app.state.caller_enabled = True
    try:
        with (
            pytest.raises(RuntimeError, match="distinct"),
            TestClient(public_app),
        ):
            pass
    finally:
        for name in ("caller", "caller_enabled"):
            if hasattr(webhooks.public_app.state, name):
                delattr(webhooks.public_app.state, name)
