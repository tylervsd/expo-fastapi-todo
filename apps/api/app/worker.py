"""Private Cloud Tasks worker: execute and expire suggestion reservations.

Ponytail only: this is the single suggestion execution entry point, not a
generic task framework. It mounts no public auth, todo, agent, or workflow
routes; Cloud Run IAM protects it in deployment and there is no
production auth-bypass flag. Local tests instantiate `create_worker_app`
with fake provider/session seams.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, HTTPException, Request, Response
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.database import (
    create_database_engine,
    create_session_factory,
    get_database_url,
)
from app.observability import RequestLoggingMiddleware, configure_logging
from app.suggestion_provider import (
    InvalidSuggestionOutput,
    OpenRouterConfig,
    ProviderUnavailable,
    SuggestionsNotConfigured,
    SuggestionTimeout,
    get_openrouter_config,
    request_todo_suggestions,
)
from app.suggestion_service import (
    ClaimedSuggestion,
    Clarification,
    InvalidStoredSuggestion,
    SuggestionErrorCode,
    SuggestionInProgress,
    claim_suggestion,
    expire_suggestions,
    finish_claimed_suggestion,
)
from app.tracing import (
    ResponseStatusMiddleware,
    TracingMiddleware,
    init_tracing,
    shutdown_tracing,
)

logger = logging.getLogger(__name__)

TASK_VERSION = 1
MAX_TASK_BODY_BYTES = 1024
DB_READY_TIMEOUT_SECONDS = 5.0


class SuggestionCallable(Protocol):
    async def __call__(
        self,
        goal: str,
        config: OpenRouterConfig,
        *,
        clarification: Clarification | None = None,
    ) -> tuple[str, ...]: ...


def create_worker_app(
    *,
    session_factory: sessionmaker[Session] | None = None,
    suggestion_callable: SuggestionCallable | None = None,
) -> FastAPI:
    """Build the private worker application with its injected seams."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine: Engine | None = None
        factory = session_factory
        if factory is None:
            engine = create_database_engine(get_database_url())
            factory = create_session_factory(engine)
        app.state.session_factory = factory
        # Lifespan-owned tracer/exporter setup, closed on shutdown. Tests
        # inject an in-memory exporter via app.state.tracing_exporter.
        app.state.tracing_state = init_tracing(
            "todo-worker",
            exporter=getattr(app.state, "tracing_exporter", None),
        )
        try:
            yield
        finally:
            shutdown_tracing(getattr(app.state, "tracing_state", None))
            app.state.tracing_state = None
            if engine is not None:
                engine.dispose()

    configure_logging("todo-worker")
    app = FastAPI(
        title="Suggestion worker",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(ResponseStatusMiddleware)
    app.add_middleware(RequestLoggingMiddleware, service="todo-worker")
    app.add_middleware(
        TracingMiddleware,
        state_provider=lambda: getattr(app.state, "tracing_state", None),
    )
    if session_factory is not None:
        app.state.session_factory = session_factory
    suggestion_runner: SuggestionCallable = (
        suggestion_callable or request_todo_suggestions
    )
    use_real_provider_config = suggestion_callable is None

    def get_session_factory(request: Request) -> sessionmaker[Session] | None:
        return getattr(request.app.state, "session_factory", None)

    def worker_unavailable() -> HTTPException:
        # Sanitized transport error: never carries database, provider, or
        # credential detail so Cloud Tasks can safely retry the delivery.
        return HTTPException(
            status_code=503,
            detail={
                "code": "worker_unavailable",
                "message": "Suggestion worker is temporarily unavailable.",
            },
        )

    def log_outcome(
        suggestion_id: int,
        outcome: str,
        started: float,
        error_code: SuggestionErrorCode | None = None,
    ) -> None:
        # Only IDs, outcome, duration, and safe error codes are logged; never
        # goals, clarification, proposals, tokens, or raw exception text.
        extra: dict[str, object] = {
            "suggestion_id": suggestion_id,
            "outcome": outcome,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        if error_code is not None:
            extra["error_code"] = error_code.value
        logger.info("suggestion_task", extra=extra)

    async def read_bounded_body(request: Request) -> bytes:
        # Enforce the 1024-byte task limit while reading chunks: Content-Length
        # may be absent or forged on a retried delivery.
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_TASK_BODY_BYTES:
                logger.warning("suggestion_task_rejected", extra={"outcome": "oversized"})
                raise HTTPException(
                    status_code=413, detail="Task body is too large."
                )
        return bytes(data)

    def parse_task_body(raw: bytes) -> int:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(
                status_code=422, detail="Task body must be JSON."
            ) from None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=422, detail="Task body must be a JSON object."
            )
        if set(payload) != {"version", "suggestion_id"}:
            raise HTTPException(
                status_code=422, detail="Task body has unexpected fields."
            )
        version = payload["version"]
        suggestion_id = payload["suggestion_id"]
        # `type(...) is int` rejects booleans, floats, and numeric strings;
        # Cloud Tasks bodies carry strict version 1 integer IDs only.
        if type(version) is not int or type(suggestion_id) is not int:
            raise HTTPException(
                status_code=422, detail="Task body fields must be integers."
            )
        if version != TASK_VERSION:
            raise HTTPException(
                status_code=400, detail="Unsupported task version."
            )
        if suggestion_id <= 0:
            raise HTTPException(
                status_code=422, detail="Task suggestion_id must be positive."
            )
        return suggestion_id

    def claim_once(
        factory: sessionmaker[Session], suggestion_id: int
    ) -> ClaimedSuggestion | None:
        with factory() as session:
            return claim_suggestion(session, suggestion_id)

    def finish_ready(
        factory: sessionmaker[Session],
        claim: ClaimedSuggestion,
        titles: tuple[str, ...],
    ) -> object:
        with factory() as session:
            return finish_claimed_suggestion(
                session, claim, titles=titles, error_code=None
            )

    def finish_failed(
        factory: sessionmaker[Session],
        claim: ClaimedSuggestion,
        error_code: SuggestionErrorCode,
    ) -> object:
        with factory() as session:
            return finish_claimed_suggestion(
                session, claim, titles=None, error_code=error_code
            )

    async def execute_provider(
        claim: ClaimedSuggestion,
    ) -> tuple[tuple[str, ...] | None, SuggestionErrorCode | None]:
        # Same provider exception-to-error-code mapping as the public route:
        # known failures persist as failed results, never as retries.
        try:
            config = (
                get_openrouter_config()
                if use_real_provider_config
                else OpenRouterConfig(api_key="", model="")
            )
        except SuggestionsNotConfigured:
            return None, SuggestionErrorCode.NOT_CONFIGURED
        try:
            # Without clarification the legacy two-argument seam is retained;
            # the keyword is only used when a clarification was supplied.
            if claim.reservation.clarification is None:
                titles = await suggestion_runner(claim.reservation.goal, config)
            else:
                titles = await suggestion_runner(
                    claim.reservation.goal,
                    config,
                    clarification=claim.reservation.clarification,
                )
        except SuggestionTimeout:
            return None, SuggestionErrorCode.TIMEOUT
        except ProviderUnavailable:
            return None, SuggestionErrorCode.PROVIDER_UNAVAILABLE
        except InvalidSuggestionOutput:
            return None, SuggestionErrorCode.INVALID_OUTPUT
        except SuggestionsNotConfigured:
            return None, SuggestionErrorCode.NOT_CONFIGURED
        except Exception:  # noqa: BLE001 - isolate provider failures
            return None, SuggestionErrorCode.PROVIDER_UNAVAILABLE
        return tuple(titles), None

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request) -> dict[str, str]:
        factory = get_session_factory(request)
        if factory is None:
            raise worker_unavailable()

        def check_once() -> None:
            with factory() as session, session.begin():
                session.execute(text("SET LOCAL statement_timeout = '5s'"))
                session.execute(text("SELECT 1"))

        try:
            await asyncio.wait_for(
                run_in_threadpool(check_once),
                timeout=DB_READY_TIMEOUT_SECONDS,
            )
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - readiness stays sanitized
            logger.warning("worker_ready_check_failed", extra={"outcome": "not_ready"})
            raise worker_unavailable() from None
        return {"status": "ok"}

    @app.post("/internal/suggestions", status_code=204)
    async def handle_suggestion(request: Request) -> Response:
        started = time.monotonic()
        raw = await read_bounded_body(request)
        try:
            suggestion_id = parse_task_body(raw)
        except HTTPException:
            logger.warning(
                "suggestion_task_rejected", extra={"outcome": "malformed"}
            )
            raise
        factory = get_session_factory(request)
        if factory is None:
            raise worker_unavailable()
        # Claim first and commit; the provider runs outside any transaction.
        try:
            claim = await run_in_threadpool(claim_once, factory, suggestion_id)
        except SuggestionInProgress:
            # A live claim means another delivery is executing: ask Cloud
            # Tasks to retry later without a second provider call.
            log_outcome(suggestion_id, "live_claim_retry", started)
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "suggestion_in_progress",
                    "message": "Suggestion execution is already in progress.",
                },
            ) from None
        except InvalidStoredSuggestion:
            # Fail-closed stored rows never reach the provider.
            log_outcome(suggestion_id, "invalid_stored_row", started)
            raise worker_unavailable() from None
        except (OperationalError, SQLAlchemyTimeoutError):
            log_outcome(suggestion_id, "claim_unavailable", started)
            raise worker_unavailable() from None
        except Exception:  # noqa: BLE001 - worker errors stay sanitized
            log_outcome(suggestion_id, "claim_failed", started)
            raise worker_unavailable() from None
        if claim is None:
            # Missing, terminal, legacy, expired, superseded, cancelled, or
            # stale rows never call the provider; acknowledge to discard.
            log_outcome(suggestion_id, "no_work", started)
            return Response(status_code=204)
        # The claim is committed; provider time holds no database resources.
        titles, error_code = await execute_provider(claim)
        # Finalize in a fresh transaction; late writes are silent no-ops that
        # still acknowledge the delivery.
        try:
            if error_code is not None:
                await run_in_threadpool(finish_failed, factory, claim, error_code)
                log_outcome(suggestion_id, "failed", started, error_code)
            else:
                assert titles is not None
                try:
                    await run_in_threadpool(finish_ready, factory, claim, titles)
                except (TypeError, ValueError):
                    await run_in_threadpool(
                        finish_failed,
                        factory,
                        claim,
                        SuggestionErrorCode.INVALID_OUTPUT,
                    )
                    error_code = SuggestionErrorCode.INVALID_OUTPUT
                    log_outcome(suggestion_id, "failed", started, error_code)
                else:
                    log_outcome(suggestion_id, "ready", started)
        except (OperationalError, SQLAlchemyTimeoutError):
            log_outcome(suggestion_id, "finalize_unavailable", started)
            raise worker_unavailable() from None
        except Exception:  # noqa: BLE001 - worker errors stay sanitized
            log_outcome(suggestion_id, "finalize_failed", started)
            raise worker_unavailable() from None
        return Response(status_code=204)

    @app.post("/internal/suggestions/expire")
    async def expire(request: Request) -> dict[str, int]:
        raw = await read_bounded_body(request)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(
                status_code=422, detail="Expiry body must be JSON."
            ) from None
        if not isinstance(payload, dict) or payload != {}:
            logger.warning(
                "suggestion_task_rejected", extra={"outcome": "malformed"}
            )
            raise HTTPException(
                status_code=422, detail="Expiry body must be an empty object."
            )
        factory = get_session_factory(request)
        if factory is None:
            raise worker_unavailable()

        def sweep_once() -> int:
            with factory() as session:
                return expire_suggestions(session)

        try:
            expired = await run_in_threadpool(sweep_once)
        except (OperationalError, SQLAlchemyTimeoutError):
            logger.warning("worker_expire_failed", extra={"outcome": "unavailable"})
            raise worker_unavailable() from None
        except Exception:  # noqa: BLE001 - worker errors stay sanitized
            logger.warning("worker_expire_failed", extra={"outcome": "failed"})
            raise worker_unavailable() from None
        logger.info("suggestion_expire", extra={"expired": expired})
        return {"expired": expired}

    return app


app = create_worker_app()
