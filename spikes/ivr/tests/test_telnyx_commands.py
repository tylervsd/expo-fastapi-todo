import asyncio
import base64
import json

import httpx
import pytest

from telnyx_commands import CommandError, make_command, send_command


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
