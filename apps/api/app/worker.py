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
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from typing import Protocol

from fastapi import FastAPI, HTTPException, Request, Response
from opentelemetry.trace import Link, get_current_span
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.analytics_export import LoadRows, bigquery_loader, export_events
from app.database import (
    create_database_engine,
    create_session_factory,
    get_database_url,
)
from app.observability import (
    RequestLoggingMiddleware,
    configure_logging,
    log_event,
    log_unexpected_fault,
)
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
    ClaimResult,
    Clarification,
    InvalidStoredSuggestion,
    SuggestionErrorCode,
    SuggestionInProgress,
    SuggestionSnapshot,
    SuggestionStatus,
    claim_suggestion_result,
    expire_suggestions_with_context,
    finish_claimed_suggestion,
)
from app.suggestion_tasks import SUGGESTION_TRACEPARENT_HEADER
from app.tracing import (
    ResponseStatusMiddleware,
    TracingMiddleware,
    extract_stored_context,
    init_tracing,
    safe_span_attributes,
    set_span_outcome,
    shutdown_tracing,
    start_safe_span,
    start_stored_span,
)
from app.workflow_repository import WorkflowSuggestionRequestRow

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


def read_stored_trace_parent(
    factory: sessionmaker[Session], suggestion_id: int
) -> str | None:
    """Lightweight lineage pre-read so each delivery can join the stored trace.

    Returns the stored traceparent or None. Never raises: the claim right
    after surfaces database errors through the sanitized mapping.
    """
    try:
        with factory() as session:
            return session.scalar(
                select(WorkflowSuggestionRequestRow.trace_parent).where(
                    WorkflowSuggestionRequestRow.id == suggestion_id
                )
            )
    except Exception:  # noqa: BLE001 - the claim reports the failure
        return None


def _incoming_trace_candidate(
    app_raw: str | None,
    std_raw: str | None,
) -> tuple[str | None, object]:
    """Prefer the app-owned lineage header, fall back to `traceparent`.

    Returns (raw value, validated context) or (None, None). Both headers
    carry the same value on the happy path; when a managed intermediary
    rewrites the standard header, the app header preserves application
    lineage. Baggage is never read.
    """
    for raw in (app_raw, std_raw):
        if raw is None:
            continue
        context = extract_stored_context(raw)
        if context is not None:
            return raw.strip(), context
    return None, None


def _trace_diagnosis(
    *,
    app_raw: str | None,
    std_raw: str | None,
    incoming_raw: str | None,
    incoming_ctx: object,
    stored_ctx: object,
) -> str | None:
    """Bounded diagnosis for observability-input problems.

    Returns one of missing/invalid/mismatch/modified, else None. Never
    rejects work or carries header values; the caller logs only the code.
    """
    if incoming_ctx is None:
        if stored_ctx is None:
            return None
        if app_raw is None and std_raw is None:
            return "missing"
        return "invalid"
    if stored_ctx is not None:
        incoming_trace = (
            get_current_span(incoming_ctx).get_span_context().trace_id  # type: ignore[arg-type]
        )
        stored_trace = (
            get_current_span(stored_ctx).get_span_context().trace_id  # type: ignore[arg-type]
        )
        if incoming_trace != stored_trace:
            return "mismatch"
    if (
        app_raw is not None
        and incoming_raw == app_raw.strip()
        and std_raw != app_raw.strip()
    ):
        return "modified"
    return None


@contextmanager
def _delivery_span(
    tracer: object,
    suggestion_id: int,
    *,
    stored_ctx: object,
    incoming_ctx: object,
):
    """One `suggestion.process` span per delivery in the stored trace.

    Stored row context controls processing lineage where available; without
    it, the validated app lineage header does. A receipt span on another
    trace (tampered standard header, mismatched delivery) is linked, never
    reparented. Stored parents inherit their sampling decision; header
    parents go through the normal boundary decision. Yields None when
    tracing is unavailable.
    """
    attributes = {"operation": "process", "suggestion_id": suggestion_id}
    if tracer is None:
        yield None
        return
    lineage_ctx = stored_ctx if stored_ctx is not None else incoming_ctx
    trusted = stored_ctx is not None
    if lineage_ctx is None:
        with start_safe_span(  # type: ignore[arg-type]
            tracer, "suggestion.process", attributes=attributes
        ) as span:
            yield span
        return
    lineage_id = get_current_span(lineage_ctx).get_span_context()  # type: ignore[arg-type]
    receipt = get_current_span().get_span_context()
    if receipt.is_valid and receipt.trace_id == lineage_id.trace_id:
        with start_safe_span(  # type: ignore[arg-type]
            tracer, "suggestion.process", attributes=attributes
        ) as span:
            yield span
    elif trusted:
        links = [Link(receipt)] if receipt.is_valid else None
        with start_stored_span(  # type: ignore[arg-type]
            tracer,
            lineage_ctx,  # type: ignore[arg-type]
            "suggestion.process",
            attributes=attributes,
            links=links,
        ) as span:
            yield span
    else:
        links = [Link(receipt)] if receipt.is_valid else None
        with start_safe_span(  # type: ignore[arg-type]
            tracer,
            "suggestion.process",
            context=lineage_ctx,  # type: ignore[arg-type]
            attributes=attributes,
            links=links,
        ) as span:
            yield span


@contextmanager
def _child_span(tracer: object, name: str, operation: str, suggestion_id: int):
    """Fixed-name child span for one delivery stage; no-op without tracing."""
    if tracer is None:
        yield None
    else:
        with start_safe_span(  # type: ignore[arg-type]
            tracer,
            name,
            attributes={"operation": operation, "suggestion_id": suggestion_id},
        ) as span:
            yield span


def _emit_expire_span(tracer: object, sweep_context: object, item: object) -> None:
    """One short `suggestion.expire` span for a single expired row.

    Rows carrying stored context are spanned under that context and linked
    to the separate Scheduler sweep trace; legacy/context-less rows stay
    valid as ordinary children of the sweep exchange. Runs after the sweep
    transaction commits and holds no database resources. Telemetry never
    fails expiry: errors are swallowed.
    """
    if tracer is None:
        return
    suggestion_id = getattr(item, "suggestion_id", None)
    trace_parent = getattr(item, "trace_parent", None)
    attributes = {"operation": "expire", "suggestion_id": suggestion_id}
    try:
        stored_ctx = (
            extract_stored_context(trace_parent)
            if isinstance(trace_parent, str) and trace_parent
            else None
        )
        if stored_ctx is not None:
            links = (
                [Link(sweep_context)]  # type: ignore[arg-type]
                if getattr(sweep_context, "is_valid", False)
                else None
            )
            with start_stored_span(  # type: ignore[arg-type]
                tracer,
                stored_ctx,  # type: ignore[arg-type]
                "suggestion.expire",
                attributes=attributes,  # type: ignore[arg-type]
                links=links,
            ) as span:
                set_span_outcome(span, "success")  # type: ignore[arg-type]
        else:
            with start_safe_span(  # type: ignore[arg-type]
                tracer,
                "suggestion.expire",
                attributes=attributes,  # type: ignore[arg-type]
            ) as span:
                set_span_outcome(span, "success")  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001, S110 - telemetry never raises
        pass


def _delivery_error(process_span: object, exc: HTTPException) -> None:
    """Record a bounded outcome on the delivery span for a raised status."""
    if process_span is None:
        return
    code = exc.detail.get("code") if isinstance(exc.detail, dict) else None
    outcome = "server_error" if exc.status_code >= 500 else "client_error"
    set_span_outcome(
        process_span,  # type: ignore[arg-type]
        outcome,
        error_code=str(code)[:64] if code is not None else None,
    )


def create_worker_app(
    *,
    session_factory: sessionmaker[Session] | None = None,
    suggestion_callable: SuggestionCallable | None = None,
    analytics_load: LoadRows | None = None,
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
        table = os.environ.get("ANALYTICS_EVENTS_TABLE")
        app.state.analytics_load = analytics_load or (
            bigquery_loader(table) if table else None
        )
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

    def emit_delivery(
        suggestion_id: int,
        outcome: str,
        started: float,
        error_code: SuggestionErrorCode | None = None,
        queue_wait_ms: int | None = None,
    ) -> None:
        # Delivery/ack taxonomy (`suggestion_delivery`): one event per
        # delivery attempt with the ack outcome. `delivered` means provider
        # work ran and the finish committed — the business outcome lives in
        # the companion `suggestion_finished`; `claim_timeout` /
        # `claim_superseded` name claim-time commits; `discarded`/`no_work`
        # and the failure/retry outcomes commit nothing. Only IDs,
        # durations, queue delay, and safe error codes travel.
        extra: dict[str, object] = {
            "suggestion_id": suggestion_id,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        if queue_wait_ms is not None:
            extra["queue_wait_ms"] = queue_wait_ms
        log_event(
            "suggestion_delivery",
            outcome=outcome,
            error_code=error_code,
            **extra,
        )

    def emit_finished(
        suggestion_id: int,
        outcome: str,
        started: float,
        error_code: SuggestionErrorCode | None = None,
        queue_wait_ms: int | None = None,
    ) -> None:
        # Committed business truth (`suggestion_finished`): emitted only
        # after a terminal transition commits, with the bounded business
        # outcome (`ready`/`failed`/`superseded`) Task 4 metrics count.
        # Never emitted for discards, replays, or uncommitted failures.
        extra: dict[str, object] = {
            "suggestion_id": suggestion_id,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        if queue_wait_ms is not None:
            extra["queue_wait_ms"] = queue_wait_ms
        log_event(
            "suggestion_finished",
            outcome=outcome,
            error_code=error_code,
            **extra,
        )

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
    ) -> ClaimResult:
        with factory() as session:
            return claim_suggestion_result(session, suggestion_id)

    def finish_ready(
        factory: sessionmaker[Session],
        claim: ClaimedSuggestion,
        titles: tuple[str, ...],
    ) -> SuggestionSnapshot | None:
        with factory() as session:
            return finish_claimed_suggestion(
                session, claim, titles=titles, error_code=None
            )

    def finish_failed(
        factory: sessionmaker[Session],
        claim: ClaimedSuggestion,
        error_code: SuggestionErrorCode,
    ) -> SuggestionSnapshot | None:
        with factory() as session:
            return finish_claimed_suggestion(
                session, claim, titles=None, error_code=error_code
            )

    def set_provider_outcome(span: object, outcome: str) -> None:
        # Provider outcomes use their own bounded vocabulary (ok, timeout,
        # unavailable, invalid_output): never the request-span vocabulary
        # and never exception text. Telemetry failures stay silent.
        if span is None:
            return
        try:
            span.set_attributes(safe_span_attributes({"outcome": outcome}))  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001, S110 - telemetry must never raise
            pass

    async def execute_provider(
        claim: ClaimedSuggestion,
        provider_span: object,
    ) -> tuple[tuple[str, ...] | None, SuggestionErrorCode | None]:
        # Same provider exception-to-error-code mapping as the public route:
        # known failures persist as failed results, never as retries.
        # Cancellation is not mapped: it unwinds the delivery instead of
        # persisting as a provider result.
        try:
            config = (
                get_openrouter_config()
                if use_real_provider_config
                else OpenRouterConfig(api_key="", model="")
            )
        except SuggestionsNotConfigured:
            set_provider_outcome(provider_span, "unavailable")
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
            set_provider_outcome(provider_span, "timeout")
            return None, SuggestionErrorCode.TIMEOUT
        except ProviderUnavailable:
            set_provider_outcome(provider_span, "unavailable")
            return None, SuggestionErrorCode.PROVIDER_UNAVAILABLE
        except InvalidSuggestionOutput:
            set_provider_outcome(provider_span, "invalid_output")
            return None, SuggestionErrorCode.INVALID_OUTPUT
        except SuggestionsNotConfigured:
            set_provider_outcome(provider_span, "unavailable")
            return None, SuggestionErrorCode.NOT_CONFIGURED
        except Exception:  # noqa: BLE001 - isolate provider failures
            set_provider_outcome(provider_span, "unavailable")
            return None, SuggestionErrorCode.PROVIDER_UNAVAILABLE
        set_provider_outcome(provider_span, "ok")
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

    async def _deliver_once(
        factory: sessionmaker[Session],
        tracer: object,
        suggestion_id: int,
        started: float,
    ) -> Response:
        # Claim first and commit; the provider runs outside any transaction.
        # Each stage runs in its own fixed-name child span of the delivery.
        try:
            with _child_span(
                tracer, "db.claim_suggestion", "claim_suggestion", suggestion_id
            ):
                claim_result = await run_in_threadpool(claim_once, factory, suggestion_id)
        except SuggestionInProgress:
            # A live claim means another delivery is executing: ask Cloud
            # Tasks to retry later without a second provider call.
            emit_delivery(suggestion_id, "live_claim_retry", started)
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "suggestion_in_progress",
                    "message": "Suggestion execution is already in progress.",
                },
            ) from None
        except InvalidStoredSuggestion:
            # Fail-closed stored rows never reach the provider.
            emit_delivery(suggestion_id, "invalid_stored_row", started)
            raise worker_unavailable() from None
        except (OperationalError, SQLAlchemyTimeoutError):
            emit_delivery(suggestion_id, "claim_unavailable", started)
            raise worker_unavailable() from None
        except Exception:  # noqa: BLE001 - worker errors stay sanitized
            emit_delivery(suggestion_id, "claim_failed", started)
            log_unexpected_fault("claim_failed", location="worker")
            raise worker_unavailable() from None
        if claim_result.claim is None:
            if claim_result.committed is not None:
                # The claim transaction committed a terminal transition
                # (expiry/claim-lapse timeout or supersession) instead of
                # granting provider work. Name it truthfully: no provider
                # call ran, and the business outcome is committed.
                committed = claim_result.committed
                if committed.status is SuggestionStatus.SUPERSEDED:
                    emit_finished(
                        suggestion_id, "superseded", started, None, None
                    )
                    emit_delivery(suggestion_id, "claim_superseded", started)
                else:
                    emit_finished(
                        suggestion_id,
                        "failed",
                        started,
                        committed.error_code,
                        None,
                    )
                    emit_delivery(
                        suggestion_id,
                        "claim_timeout",
                        started,
                        committed.error_code,
                    )
                return Response(status_code=204)
            # Missing, terminal, or legacy rows never call the provider;
            # replays ack without a second commit.
            emit_delivery(suggestion_id, "no_work", started)
            return Response(status_code=204)
        claim = claim_result.claim
        if claim.queue_wait_ms is not None:
            # Database-clock queue delay travels as a diagnostic attribute
            # on the process span (the current span here): no fabricated
            # queue span, and the HTTP/process spans stay closed while the
            # row waited on the broker.
            try:
                get_current_span().set_attributes(
                    safe_span_attributes(
                        {"queue_wait_ms": claim.queue_wait_ms}
                    )
                )
            except Exception:  # noqa: BLE001, S110 - telemetry never raises
                pass
        # The claim is committed; provider time holds no database resources.
        with _child_span(
            tracer, "provider.suggestions", "provider_suggestions", suggestion_id
        ) as provider_span:
            titles, error_code = await execute_provider(claim, provider_span)
        # Finalize in a fresh transaction. The saved snapshot is the truth:
        # None means the row already reached a terminal state (a late
        # result is discarded, never served or logged as ready), while a
        # SUPERSEDED snapshot marks a committed supersession. Terminal logs
        # below run only after the finish transaction commits.
        try:
            with _child_span(
                tracer, "db.finish_suggestion", "finish_suggestion", suggestion_id
            ):
                saved: SuggestionSnapshot | None
                if error_code is not None:
                    saved = await run_in_threadpool(
                        finish_failed, factory, claim, error_code
                    )
                else:
                    assert titles is not None
                    try:
                        saved = await run_in_threadpool(
                            finish_ready, factory, claim, titles
                        )
                    except (TypeError, ValueError):
                        error_code = SuggestionErrorCode.INVALID_OUTPUT
                        saved = await run_in_threadpool(
                            finish_failed, factory, claim, error_code
                        )
                if saved is None:
                    emit_delivery(
                        suggestion_id,
                        "discarded",
                        started,
                        error_code,
                        claim.queue_wait_ms,
                    )
                elif saved.status is SuggestionStatus.SUPERSEDED:
                    emit_finished(
                        suggestion_id,
                        "superseded",
                        started,
                        error_code,
                        claim.queue_wait_ms,
                    )
                    emit_delivery(
                        suggestion_id,
                        "delivered",
                        started,
                        error_code,
                        claim.queue_wait_ms,
                    )
                elif error_code is not None:
                    emit_finished(
                        suggestion_id,
                        "failed",
                        started,
                        error_code,
                        claim.queue_wait_ms,
                    )
                    emit_delivery(
                        suggestion_id,
                        "delivered",
                        started,
                        error_code,
                        claim.queue_wait_ms,
                    )
                else:
                    emit_finished(
                        suggestion_id,
                        "ready",
                        started,
                        None,
                        claim.queue_wait_ms,
                    )
                    emit_delivery(
                        suggestion_id,
                        "delivered",
                        started,
                        None,
                        claim.queue_wait_ms,
                    )
        except (OperationalError, SQLAlchemyTimeoutError):
            emit_delivery(suggestion_id, "finalize_unavailable", started)
            raise worker_unavailable() from None
        except Exception:  # noqa: BLE001 - worker errors stay sanitized
            emit_delivery(suggestion_id, "finalize_failed", started)
            log_unexpected_fault("finalize_failed", location="worker")
            raise worker_unavailable() from None
        return Response(status_code=204)

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
        # Lineage setup runs before any business read: the stored row
        # context controls the delivery span, and header problems are a
        # safe diagnostic, never a rejection. The stored value crosses the
        # threadpool boundary as an explicit return value.
        state = getattr(request.app.state, "tracing_state", None)
        tracer = state.tracer if state is not None else None
        app_raw = request.headers.get(SUGGESTION_TRACEPARENT_HEADER)
        std_raw = request.headers.get("traceparent")
        incoming_raw, incoming_ctx = _incoming_trace_candidate(app_raw, std_raw)
        stored_tp = await run_in_threadpool(
            read_stored_trace_parent, factory, suggestion_id
        )
        stored_ctx = extract_stored_context(stored_tp)
        diagnosis = _trace_diagnosis(
            app_raw=app_raw,
            std_raw=std_raw,
            incoming_raw=incoming_raw,
            incoming_ctx=incoming_ctx,
            stored_ctx=stored_ctx,
        )
        if diagnosis is not None:
            logger.warning(
                "suggestion_trace_context",
                extra={"suggestion_id": suggestion_id, "outcome": diagnosis},
            )
        # Every delivery gets its own span ID in the stored trace, even
        # duplicates and retries that never reach the provider.
        with _delivery_span(
            tracer, suggestion_id, stored_ctx=stored_ctx, incoming_ctx=incoming_ctx
        ) as process_span:
            try:
                response = await _deliver_once(
                    factory,
                    tracer,
                    suggestion_id,
                    started,
                )
            except HTTPException as exc:
                _delivery_error(process_span, exc)
                raise
            if process_span is not None:
                set_span_outcome(process_span, "success")
            return response

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
        # Scheduler sweep trace: the server span for this expire exchange.
        # Per-row `suggestion.expire` spans below link back here while
        # living under each row's stored context, so one sweep never
        # merges different suggestions into a single transaction trace.
        state = getattr(request.app.state, "tracing_state", None)
        tracer = state.tracer if state is not None else None
        sweep_context = get_current_span().get_span_context()
        sweep_started = time.monotonic()

        def sweep_once() -> list:
            with factory() as session:
                return expire_suggestions_with_context(session)

        try:
            expired_rows = await run_in_threadpool(sweep_once)
        except (OperationalError, SQLAlchemyTimeoutError):
            log_event(
                "maintenance_finished",
                outcome="unavailable",
                expired=0,
                duration_ms=int((time.monotonic() - sweep_started) * 1000),
            )
            raise worker_unavailable() from None
        except Exception:  # noqa: BLE001 - worker errors stay sanitized
            log_event(
                "maintenance_finished",
                outcome="failed",
                expired=0,
                duration_ms=int((time.monotonic() - sweep_started) * 1000),
            )
            log_unexpected_fault("expire_failed", location="worker")
            raise worker_unavailable() from None
        expired = len(expired_rows)
        sweep_duration_ms = int((time.monotonic() - sweep_started) * 1000)
        for item in expired_rows:
            _emit_expire_span(tracer, sweep_context, item)
            # Each expired row committed a failed/timeout transition in
            # the sweep transaction: one business terminal event per row,
            # after commit, for the Task 4 outcome metric.
            log_event(
                "suggestion_finished",
                outcome="failed",
                error_code=SuggestionErrorCode.TIMEOUT,
                suggestion_id=getattr(item, "suggestion_id", None),
                duration_ms=sweep_duration_ms,
            )
        log_event(
            "maintenance_finished",
            outcome="success",
            expired=expired,
            duration_ms=sweep_duration_ms,
        )
        return {"expired": expired}

    @app.post("/internal/analytics/export")
    async def analytics_export(request: Request) -> dict[str, int]:
        raw = await read_bounded_body(request)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(
                status_code=422, detail="Export body must be JSON."
            ) from None
        if not isinstance(payload, dict) or payload != {}:
            raise HTTPException(
                status_code=422, detail="Export body must be an empty object."
            )
        load = getattr(request.app.state, "analytics_load", None)
        factory = get_session_factory(request)
        if load is None or factory is None:
            raise worker_unavailable()
        started = time.monotonic()
        try:
            result = await run_in_threadpool(export_events, factory, load)
        except Exception:  # noqa: BLE001 - sanitized; rows stay for retry
            log_event(
                "analytics_export",
                outcome="failed",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            raise HTTPException(
                status_code=500, detail="Analytics export failed."
            ) from None
        log_event(
            "analytics_export",
            outcome="success",
            selected=result.selected,
            loaded=result.loaded,
            pruned=result.pruned,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return {
            "selected": result.selected,
            "loaded": result.loaded,
            "pruned": result.pruned,
        }

    return app


app = create_worker_app()
