"""Test-only FastAPI entry point for Phase 12 E2E.

Builds the real application through :func:`app.main.create_app` with both
credential-free provider seams injected, so neither path can fall back to
OpenRouter. Normal ``app.main:app`` is unchanged. Requires an explicitly
supplied ``E2E_DATABASE_URL``; never reads ``DATABASE_URL``/``TEST_DATABASE_URL``
or application ``.env`` files.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from app.database import create_database_engine, create_session_factory
from app.main import create_app
from e2e.support import choice, suggestions, validated_database_url

_ingress_logger = logging.getLogger("e2e.ingress")
_ingress_logger.setLevel(logging.INFO)
# Uvicorn's default logging config leaves the root logger without
# handlers, which would silently drop INFO records. Attach a stdout handler
# only when nothing up the logger chain would emit them (test runners such
# as pytest's caplog provide their own). Method/path/status/timing only;
# never bodies, headers, query strings, or credentials.


def _logger_chain_has_handlers(logger):
    candidate = logger
    while candidate is not None:
        if getattr(candidate, "handlers", []):
            return True
        candidate = candidate.parent
    return False


if not _logger_chain_has_handlers(_ingress_logger):
    _ingress_handler = logging.StreamHandler(sys.stdout)
    _ingress_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    _ingress_logger.addHandler(_ingress_handler)


class _IngressTimingMiddleware:
    """Test-only request ingress/response timing attribution.

    Logs one line when an HTTP request arrives and one when its response
    starts, carrying only method, path, status, and elapsed seconds. Pure
    passthrough: scope/receive/send messages are forwarded unmodified, so
    request/response behavior is unchanged. A START line without a matching
    END line in ``api.log`` proves the request arrived but the handler never
    produced a response (backend stall) rather than a client/network failure.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "-")
        path = scope.get("path", "-")
        start = time.monotonic()
        _ingress_logger.info(
            "e2e-ingress start method=%s path=%s t=%.3f", method, path, start
        )

        async def _send(message):
            if message.get("type") == "http.response.start":
                elapsed = time.monotonic() - start
                _ingress_logger.info(
                    "e2e-ingress end method=%s path=%s status=%s dt=%.3f",
                    method,
                    path,
                    message.get("status", "-"),
                    elapsed,
                )
            await send(message)

        await self.app(scope, receive, _send)


try:
    _database_url = validated_database_url(os.environ.get("E2E_DATABASE_URL", ""))
except ValueError as exc:
    raise RuntimeError(
        "E2E_DATABASE_URL must target the isolated todo_e2e database"
    ) from exc

_engine = create_database_engine(_database_url)
_session_factory = create_session_factory(_engine)

app = create_app(
    _session_factory,
    suggestion_callable=suggestions,
    agent_choice=choice,
)


_e2e_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan_with_e2e_engine(app_):
    try:
        async with _e2e_lifespan(app_):
            yield
    finally:
        _engine.dispose()


app.router.lifespan_context = _lifespan_with_e2e_engine

app.add_middleware(_IngressTimingMiddleware)
