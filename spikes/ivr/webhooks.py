"""Verified webhook boundary and independently runnable IVR entry points."""

import asyncio
import base64
import binascii
import json
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from functools import partial

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response

from client import Caller, load_client_settings
from fixture import Fixture, load_settings
from telnyx_commands import send_command, send_dial


def verify_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    key: Ed25519PublicKey,
    *,
    now: float,
) -> None:
    try:
        if not timestamp.isascii() or not timestamp.isdecimal():
            raise ValueError
        if abs(now - int(timestamp)) > 300:
            raise ValueError
        key.verify(
            base64.b64decode(signature, validate=True),
            timestamp.encode("ascii") + b"|" + body,
        )
    except ValueError, binascii.Error, InvalidSignature:
        raise ValueError("Invalid authentication") from None


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        key = base64.b64decode(os.environ["TELNYX_PUBLIC_KEY"], validate=True)
        app.state.telnyx_key = Ed25519PublicKey.from_public_bytes(key)
    except KeyError, ValueError, binascii.Error:
        raise RuntimeError("Invalid TELNYX_PUBLIC_KEY configuration") from None
    fixture_on = getattr(app.state, "fixture_enabled", False)
    caller_on = getattr(app.state, "caller_enabled", False)
    if not fixture_on and not caller_on:
        yield
        return
    fixture_settings = load_settings() if fixture_on else None
    client_settings = load_client_settings() if caller_on else None
    if (
        fixture_on
        and caller_on
        and fixture_settings.connection_id == client_settings.connection_id
    ):
        raise RuntimeError("Client and fixture application IDs must be distinct")
    # HTTP request URLs contain call-control tokens; keep them out of default logs.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    http_clients: list[httpx.AsyncClient] = []

    async def _http_client(api_key: str) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5,
            follow_redirects=False,
        )
        http_clients.append(client)
        return client

    try:
        if (
            fixture_on
            and caller_on
            and fixture_settings.api_key == client_settings.api_key
        ):
            shared = await _http_client(fixture_settings.api_key)
            fixture_http = caller_http = shared
        else:
            fixture_http = (
                await _http_client(fixture_settings.api_key) if fixture_on else None
            )
            caller_http = (
                await _http_client(client_settings.api_key) if caller_on else None
            )
        watchers = []
        if fixture_on:
            ivr = Fixture(
                fixture_settings,
                partial(send_command, fixture_http),
                started_at=datetime.now(UTC),
            )
            app.state.ivr = ivr

            async def fixture_watchdog():
                while True:
                    await asyncio.sleep(1)
                    await ivr.tick()

            watchers.append(asyncio.create_task(fixture_watchdog()))
        if caller_on:

            async def _dial(request):
                return await send_dial(caller_http, request)

            async def _send(command):
                await send_command(caller_http, command)

            # The caller never receives a fixture reference, even combined.
            app.state.caller = Caller(client_settings, _dial, _send)

            async def caller_watchdog():
                while True:
                    await asyncio.sleep(1)
                    await app.state.caller.tick()

            watchers.append(asyncio.create_task(caller_watchdog()))
        try:
            yield
        finally:
            first_error: BaseException | None = None
            for watcher in watchers:
                watcher.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await asyncio.gather(*watchers, return_exceptions=False)
            except BaseException as error:  # noqa: BLE001 — keep closing; re-raised below
                first_error = error
            if fixture_on:
                try:
                    await app.state.ivr.close()
                except BaseException as error:  # noqa: BLE001 — caller close must still run
                    if first_error is None:
                        first_error = error
            if caller_on and getattr(app.state.caller, "_started", False):
                try:
                    await app.state.caller.close()
                except BaseException as error:  # noqa: BLE001 — HTTP client must still close
                    if first_error is None:
                        first_error = error
            if first_error is not None:
                raise first_error
    finally:
        for client in http_clients:
            with suppress(Exception):
                await client.aclose()
        # Never retain the prior run's controller or CLI flag. Fixture
        # configuration flags set at import stay; app.state.ivr stays for
        # existing diagnostics.
        for _name in ("caller", "caller_enabled"):
            with suppress(AttributeError, KeyError):
                delattr(app.state, _name)


# Use Uvicorn's configured stderr handler so accepted events are visible by default.
logger = logging.getLogger("ivr.webhooks")
logger.setLevel(logging.INFO)
logger.parent = logging.getLogger("uvicorn.error")


def reject_json_constant(value: str):
    raise ValueError("Invalid JSON constant")


async def receive_event(request: Request, role: str) -> Response:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65536:
            raise HTTPException(413, "Request too large")
        body.extend(chunk)

    timestamps = request.headers.getlist("telnyx-timestamp")
    signatures = request.headers.getlist("telnyx-signature-ed25519")
    if len(timestamps) != 1 or len(signatures) != 1:
        raise HTTPException(401, "Invalid authentication")
    try:
        verify_signature(
            bytes(body),
            timestamps[0],
            signatures[0],
            request.app.state.telnyx_key,
            now=time.time(),
        )
    except ValueError:
        raise HTTPException(401, "Invalid authentication") from None

    try:
        envelope = json.loads(body, parse_constant=reject_json_constant)
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
            raise TypeError
        event_id, event_type = data.get("id"), data.get("event_type")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
            raise ValueError
        if not isinstance(event_type, str) or not 1 <= len(event_type) <= 128:
            raise ValueError
    except ValueError, TypeError, RecursionError:
        raise HTTPException(400, "Invalid envelope") from None

    logger.info(
        json.dumps({"role": role, "event_id": event_id, "event_type": event_type})
    )
    if role == "test-ivr":
        try:
            await request.app.state.ivr.accept(data)
        except ValueError:
            raise HTTPException(400, "Invalid call event") from None
    elif role == "client":
        # Receipt-only when the CLI has not enabled a caller; never touch ivr.
        caller = getattr(request.app.state, "caller", None)
        if caller is not None:
            try:
                await caller.accept(data)
            except ValueError:
                raise HTTPException(400, "Invalid call event") from None
    return Response(status_code=200)


client_router = APIRouter()
test_ivr_router = APIRouter()


@client_router.post("/webhooks/client")
async def client_webhook(request: Request):
    return await receive_event(request, "client")


@test_ivr_router.post("/webhooks/test-ivr")
async def test_ivr_webhook(request: Request):
    return await receive_event(request, "test-ivr")


client_app = FastAPI(lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None)
test_ivr_app = FastAPI(
    lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None
)
public_app = FastAPI(lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None)
test_ivr_app.state.fixture_enabled = True
public_app.state.fixture_enabled = True
client_app.include_router(client_router)
test_ivr_app.include_router(test_ivr_router)
public_app.include_router(client_router)
public_app.include_router(test_ivr_router)


@client_app.get("/health")
async def client_health():
    return {"status": "ok", "role": "client"}


@test_ivr_app.get("/health")
async def test_ivr_health():
    return {"status": "ok", "role": "test-ivr"}
