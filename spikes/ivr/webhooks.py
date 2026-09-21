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

from fixture import Fixture, load_settings
from telnyx_commands import send_command


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
    if not getattr(app.state, "fixture_enabled", False):
        yield
        return
    settings = load_settings()
    # HTTP request URLs contain call-control tokens; keep them out of default logs.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {settings.api_key}"},
        timeout=5,
        follow_redirects=False,
    ) as client:
        ivr = Fixture(
            settings, partial(send_command, client), started_at=datetime.now(UTC)
        )
        app.state.ivr = ivr

        async def watchdog():
            while True:
                await asyncio.sleep(1)
                await ivr.tick()

        watcher = asyncio.create_task(watchdog())
        try:
            yield
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            await ivr.close()


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
