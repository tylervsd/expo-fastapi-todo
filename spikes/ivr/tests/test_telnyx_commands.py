import asyncio
import base64
import json

import httpx
import pytest

from telnyx_commands import (
    CommandError,
    DialIdentity,
    DialRequest,
    make_command,
    make_dial,
    send_command,
    send_dial,
)


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    async def no_delay(seconds):
        assert seconds == 1

    monkeypatch.setattr("telnyx_commands.asyncio.sleep", no_delay)


@pytest.mark.parametrize("action", ["answer", "gather_using_speak", "speak", "hangup"])
def test_retry_keeps_identity_and_fixed_origin(action):
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(
            503 if len(seen) == 1 else 200, json={"data": {"result": "ok"}}
        )

    async def exercise():
        command = make_command("call/token", action, {"payload": "test"})
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer test-only"},
            transport=httpx.MockTransport(transport),
            follow_redirects=True,
        ) as client:
            await send_command(client, command)
        assert len(seen) == 2
        assert seen[0].content == seen[1].content == command.body
        assert (
            seen[0].url.raw_path == f"/v2/calls/call%2Ftoken/actions/{action}".encode()
        )
        assert seen[0].url.host == "api.telnyx.com"
        assert seen[0].headers["authorization"] == "Bearer test-only"
        assert seen[0].headers["content-type"] == "application/json"
        body = json.loads(command.body)
        assert body["command_id"] == command.command_id
        assert body["client_state"] == command.client_state
        assert len(base64.b64decode(command.client_state)) == 36
        assert make_command("call/token", action, {}).command_id != command.command_id

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "status,body,headers,count,reason",
    [
        (401, {}, {}, 1, "rejected"),
        (422, {}, {}, 1, "rejected"),
        (302, {}, {"Location": "https://other.invalid"}, 1, "rejected"),
        (429, {}, {}, 2, "uncertain"),
        (500, {}, {}, 2, "uncertain"),
        (429, {}, {"Retry-After": "20"}, 1, "uncertain"),
        (429, {}, {"Retry-After": "tomorrow"}, 1, "uncertain"),
        (429, {}, {"Retry-After": "-1"}, 1, "uncertain"),
        (200, {}, {}, 1, "invalid_response"),
        (200, [], {}, 1, "invalid_response"),
        (200, {"data": {"result": "no"}}, {}, 1, "invalid_response"),
        (201, {"data": {"result": "ok"}}, {}, 1, "rejected"),
    ],
)
def test_bounded_failure(status, body, headers, count, reason, caplog):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            with pytest.raises(CommandError) as error:
                await send_command(client, make_command("SECRET_TOKEN", "answer", {}))
            assert error.value.reason == reason
            assert "SECRET_TOKEN" not in str(error.value)
            assert "SECRET_TOKEN" not in error.value.reason
            assert "SECRET_TOKEN" not in caplog.text
        assert len(requests) == count

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "mode", ["read_timeout", "network", "invalid_json", "total_timeout"]
)
def test_errors_are_sanitized_and_bounded(mode, monkeypatch):
    calls = []

    def transport(request):
        calls.append(request)
        if mode == "read_timeout":
            raise httpx.ReadTimeout("SECRET", request=request)
        if mode == "network":
            raise httpx.ConnectError("SECRET", request=request)
        return httpx.Response(200, text="SECRET")

    if mode == "total_timeout":

        class Timeout:
            async def __aenter__(self):
                calls.append(None)
                raise TimeoutError("SECRET")

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(
            "telnyx_commands.asyncio.timeout", lambda seconds: Timeout()
        )

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            with pytest.raises(CommandError) as error:
                await send_command(client, make_command("SECRET", "answer", {}))
            assert str(error.value) in ("uncertain", "invalid_response")
        assert len(calls) == (1 if mode == "invalid_json" else 2)

    asyncio.run(exercise())


def test_forbidden_action():
    with pytest.raises(ValueError):
        make_command("call", "dial", {})


def _string_identities(body):
    """Collect nonempty string identities from a mocked dial body."""
    found = []
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict):
        for key in ("call_control_id", "call_leg_id"):
            value = data.get(key)
            if isinstance(value, str) and value:
                found.append(value)
    return found


def _dial_fields():
    return {
        "connection_id": "app-id",
        "from": "+15550001111",
        "to": "+15550002222",
        "timeout_secs": 30,
        "time_limit_secs": 180,
        "transcription": True,
        "transcription_config": {
            "transcription_engine": "Google",
            "transcription_engine_config": {
                "transcription_engine": "Google",
                "language": "en",
                "interim_results": False,
            },
            "transcription_tracks": "outbound",
        },
    }


def test_dial_success_fixed_origin_single_submission():
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": {"call_control_id": "client-call", "call_leg_id": "client-leg"}
            },
        )

    async def exercise():
        request = make_dial(_dial_fields())
        assert isinstance(request, DialRequest)
        assert request.command_id and request.client_state
        assert repr(request).find(request.command_id) == -1
        assert repr(request).find(request.client_state) == -1
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer test-only"},
            transport=httpx.MockTransport(transport),
            follow_redirects=True,
        ) as client:
            identity = await send_dial(client, request)
        assert identity == DialIdentity("client-call", "client-leg")
        assert len(seen) == 1
        assert seen[0].url.raw_path == b"/v2/calls"
        assert seen[0].url.host == "api.telnyx.com"
        assert seen[0].headers["authorization"] == "Bearer test-only"
        assert seen[0].headers["content-type"] == "application/json"
        body = json.loads(seen[0].content)
        assert body["connection_id"] == "app-id"
        assert body["transcription"] is True
        assert body["transcription_config"]["transcription_tracks"] == "outbound"
        assert body["command_id"] == request.command_id
        assert body["client_state"] == request.client_state
        assert seen[0].content == request.body
        assert len(base64.b64decode(request.client_state)) == 36
        other = make_dial(_dial_fields())
        assert other.command_id != request.command_id
        assert other.client_state != request.client_state

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "status,body,headers,reason",
    [
        (401, {}, {}, "rejected"),
        (422, {}, {}, "rejected"),
        (302, {}, {"Location": "https://other.invalid"}, "rejected"),
        (429, {}, {}, "uncertain"),
        (500, {}, {}, "uncertain"),
        (200, {"data": {"result": "ok"}}, {}, "invalid_response"),
        (200, {}, {}, "invalid_response"),
        (200, [], {}, "invalid_response"),
        (200, {"data": {}}, {}, "invalid_response"),
        (
            200,
            {"data": {"call_control_id": 1, "call_leg_id": "leg"}},
            {},
            "invalid_response",
        ),
        (
            200,
            {"data": {"call_control_id": "", "call_leg_id": "leg"}},
            {},
            "invalid_response",
        ),
        (
            200,
            {"data": {"call_control_id": "x" * 1025, "call_leg_id": "leg"}},
            {},
            "invalid_response",
        ),
        (
            200,
            {"data": {"call_control_id": "call", "call_leg_id": "y" * 257}},
            {},
            "invalid_response",
        ),
    ],
)
def test_dial_failures_submit_once_sanitized(status, body, headers, reason, caplog):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)

    async def exercise():
        request = make_dial(_dial_fields())
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            with pytest.raises(CommandError) as error:
                await send_dial(client, request)
            assert error.value.reason == reason
            assert request.command_id not in str(error.value)
            assert request.client_state not in str(error.value)
            assert request.command_id not in error.value.reason
            assert request.client_state not in error.value.reason
            assert request.command_id not in caplog.text
            assert request.client_state not in caplog.text
            assert "client-call" not in str(error.value)
            assert "client-leg" not in str(error.value)
            assert "client-call" not in error.value.reason
            assert "client-leg" not in error.value.reason
            assert "client-call" not in caplog.text
            assert "client-leg" not in caplog.text
            for leaked in _string_identities(body):
                assert leaked not in str(error.value)
                assert leaked not in error.value.reason
                assert leaked not in caplog.text
        assert len(requests) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "mode", ["read_timeout", "network", "invalid_json", "total_timeout"]
)
def test_dial_transport_errors_submit_once(mode, monkeypatch, caplog):
    calls = []

    def transport(request):
        calls.append(request)
        if mode == "read_timeout":
            raise httpx.ReadTimeout("SECRET", request=request)
        if mode == "network":
            raise httpx.ConnectError("SECRET", request=request)
        return httpx.Response(200, text="SECRET")

    if mode == "total_timeout":

        class Timeout:
            async def __aenter__(self):
                calls.append(None)
                raise TimeoutError("SECRET")

            async def __aexit__(self, *args):
                return False

        monkeypatch.setattr(
            "telnyx_commands.asyncio.timeout", lambda seconds: Timeout()
        )

    async def exercise():
        request = make_dial(_dial_fields())
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            with pytest.raises(CommandError) as error:
                await send_dial(client, request)
            assert str(error.value) in ("uncertain", "invalid_response")
            assert "SECRET" not in str(error.value)
            assert "SECRET" not in error.value.reason
            assert "SECRET" not in caplog.text
            assert request.command_id not in str(error.value)
            assert request.client_state not in str(error.value)
            assert request.command_id not in error.value.reason
            assert request.client_state not in error.value.reason
            assert request.command_id not in caplog.text
            assert request.client_state not in caplog.text
        assert len(calls) == 1

    asyncio.run(exercise())


def test_send_dtmf_retry_reuses_body():
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(
            503 if len(seen) == 1 else 200, json={"data": {"result": "ok"}}
        )

    async def exercise():
        command = make_command(
            "call-id", "send_dtmf", {"digits": "0742#", "duration_millis": 250}
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            await send_command(client, command)
        assert len(seen) == 2
        assert seen[0].content == seen[1].content == command.body
        body = json.loads(command.body)
        assert body["digits"] == "0742#"
        assert body["command_id"] == command.command_id

    asyncio.run(exercise())


def test_dtmf_digits_never_in_errors(caplog):
    def transport(request):
        return httpx.Response(401, json={})

    async def exercise():
        command = make_command(
            "call-id", "send_dtmf", {"digits": "0742#", "duration_millis": 250}
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ) as client:
            with pytest.raises(CommandError) as error:
                await send_command(client, command)
            assert "0742" not in str(error.value)
            assert command.client_state not in str(error.value)
            assert command.command_id not in str(error.value)
            assert "call-id" not in str(error.value)
            assert "0742" not in error.value.reason
            assert command.client_state not in error.value.reason
            assert command.command_id not in error.value.reason
            assert "call-id" not in error.value.reason
            assert "0742" not in caplog.text
            assert command.client_state not in caplog.text
            assert command.command_id not in caplog.text
            assert "call-id" not in caplog.text

    asyncio.run(exercise())
