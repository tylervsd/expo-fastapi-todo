"""Only the four inbound-fixture commands, with immutable retry identities."""

import asyncio
import base64
import json
from dataclasses import dataclass
from urllib.parse import quote
from uuid import uuid4

import httpx

ACTIONS = frozenset({"answer", "gather_using_speak", "speak", "hangup"})


@dataclass(frozen=True, repr=False)
class Command:
    call_control_id: str
    action: str
    command_id: str
    client_state: str
    body: bytes


def make_command(call_control_id: str, action: str, fields: dict) -> Command:
    if action not in ACTIONS:
        raise ValueError("Unsupported command")
    command_id = str(uuid4())
    token = base64.b64encode(str(uuid4()).encode()).decode()
    body = json.dumps(
        fields | {"command_id": command_id, "client_state": token},
        separators=(",", ":"),
    ).encode()
    return Command(call_control_id, action, command_id, token, body)


class CommandError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def send_command(client: httpx.AsyncClient, command: Command) -> None:
    if command.action not in ACTIONS:
        raise ValueError("Unsupported command")
    url = (
        f"https://api.telnyx.com/v2/calls/{quote(command.call_control_id, safe='')}"
        f"/actions/{command.action}"
    )
    for attempt in range(2):
        try:
            async with asyncio.timeout(5):
                response = await client.post(
                    url,
                    content=command.body,
                    headers={"Content-Type": "application/json"},
                    timeout=5,
                    follow_redirects=False,
                )
        except httpx.TransportError, TimeoutError:
            if attempt:
                raise CommandError("uncertain") from None
        else:
            if response.status_code == 200:
                try:
                    data = response.json()
                    if not isinstance(data, dict) or not isinstance(
                        data.get("data"), dict
                    ):
                        raise TypeError
                    if data["data"].get("result") != "ok":
                        raise ValueError
                except ValueError, UnicodeError:
                    raise CommandError("invalid_response") from None
                return
            if response.status_code != 429 and response.status_code < 500:
                raise CommandError("rejected")
            retry_after = response.headers.get("retry-after", "0")
            try:
                retry_allowed = 0 <= float(retry_after) <= 1
            except ValueError:
                retry_allowed = False
            if attempt or not retry_allowed:
                raise CommandError("uncertain")
        await asyncio.sleep(1)
