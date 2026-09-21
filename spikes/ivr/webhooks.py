"""Lesson 1: authenticate and acknowledge events without controlling calls."""

import base64
import binascii
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response


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
    yield


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
    return Response(status_code=204)


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
