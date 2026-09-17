"""Phase 21 Task 1: explicit OpenTelemetry tracing lifecycle.

Boundaries only: one server span per HTTP exchange with fixed names and an
explicit safe-attribute allowlist. No automatic instrumentation, no body or
SQL capture, no custom trace-ID parsing (W3C propagation only), and no
baggage. Local runs export nothing unless TRACE_EXPORT_ENABLED is set; tests
inject an in-memory exporter through ``app.state.tracing_exporter``.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagators.textmap import Getter, Setter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import (
    Decision,
    ParentBased,
    Sampler,
    SamplingResult,
    StaticSampler,
)
from opentelemetry.trace import (
    NonRecordingSpan,
    Span,
    SpanContext,
    SpanKind,
    Status,
    StatusCode,
    Tracer,
    get_current_span,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Request flush budget from the design: end application spans and flush
# before final response completion, bounded so a slow backend cannot stall
# business responses.
REQUEST_FLUSH_TIMEOUT_SECONDS = 2.0
REQUEST_FLUSH_TIMEOUT_MILLIS = 2000

# Successful health/readiness probes never become recorded spans. Failure
# logs stay independent of this exclusion.
HEALTH_PATHS = frozenset({"/health", "/ready"})

# Fixed span names carry no user content or identifiers.
REQUEST_SPAN_NAME = "http.request"

# Span attributes are an explicit allowlist shared with logs. IDs are
# diagnostic fields, never metric labels; user content is never attached.
ALLOWED_SPAN_ATTRIBUTE_KEYS = frozenset(
    {
        "http.method",
        "http.route",
        "http.status_code",
        "operation",
        "outcome",
        "error_code",
        "attempt",
        "suggestion_id",
    }
)

# Event fields use the same allowlist policy: fixed names plus safe scalars.
ALLOWED_EVENT_FIELDS = frozenset(
    {"code", "outcome", "error_code", "operation", "status_code"}
)

# Bounded outcome vocabulary for spans.
OUTCOMES = frozenset({"success", "client_error", "server_error", "interrupted"})

OUTCOME_SUCCESS = "success"
OUTCOME_CLIENT_ERROR = "client_error"
OUTCOME_SERVER_ERROR = "server_error"
OUTCOME_INTERRUPTED = "interrupted"

_DEFAULT_SAMPLE_RATE = 0.1
_TRACE_ID_MASK = (1 << 64) - 1

# Set only while starting a span from explicitly stored (database) context.
# Incoming HTTP trace headers are untrusted and never set this flag, so the
# sampler re-decides at the public boundary instead of honoring client flags.
_TRUSTED_STORED_PARENT: ContextVar[bool] = ContextVar(
    "phase21_trusted_stored_parent", default=False
)

_propagator = TraceContextTextMapPropagator()


def read_sample_rate(raw: str | None) -> float:
    """Parse TRACE_SAMPLE_RATE, clamped to [0, 1]; default 0.1."""
    if raw is None or not raw.strip():
        return _DEFAULT_SAMPLE_RATE
    try:
        rate = float(raw)
    except ValueError:
        return _DEFAULT_SAMPLE_RATE
    if math.isnan(rate):
        return _DEFAULT_SAMPLE_RATE
    return min(1.0, max(0.0, rate))


def get_service_revision() -> str:
    """Cloud Run provides K_REVISION; local runs fall back to APP_REVISION."""
    return (
        os.environ.get("K_REVISION")
        or os.environ.get("APP_REVISION")
        or "local"
    )


def outcome_for_status(status_code: int) -> str:
    if status_code < 400:
        return OUTCOME_SUCCESS
    if status_code < 500:
        return OUTCOME_CLIENT_ERROR
    return OUTCOME_SERVER_ERROR


def current_span_ids() -> tuple[str, str]:
    """Active (trace_id, span_id) hex, or zeros when no valid span."""
    context = get_current_span().get_span_context()
    if not context.is_valid:
        return ("0" * 32, "0" * 16)
    return (format(context.trace_id, "032x"), format(context.span_id, "016x"))


class BoundarySampler(Sampler):
    """Root decisions are local; stored parents are inherited.

    Remote parents extracted from untrusted HTTP headers never force the
    decision: the boundary span is sampled deterministically from its trace
    ID and TRACE_SAMPLE_RATE. Local parents are honored, and explicitly
    stored (database) parents are honored while the trusted flag is set.
    """

    def __init__(self, rate: float) -> None:
        self._rate = min(1.0, max(0.0, rate))
        self._root = ParentBased(
            root=StaticSampler(Decision.RECORD_AND_SAMPLE),
            remote_parent_sampled=StaticSampler(Decision.RECORD_AND_SAMPLE),
            remote_parent_not_sampled=StaticSampler(Decision.DROP),
            local_parent_sampled=StaticSampler(Decision.RECORD_AND_SAMPLE),
            local_parent_not_sampled=StaticSampler(Decision.DROP),
        )

    @property
    def rate(self) -> float:
        return self._rate

    def get_description(self) -> str:
        return f"Phase21BoundarySampler{{rate={self._rate}}}"

    def _root_decision(self) -> Decision:
        if self._rate >= 1.0:
            return Decision.RECORD_AND_SAMPLE
        if self._rate <= 0.0:
            return Decision.DROP
        return Decision.RECORD_AND_SAMPLE

    def should_sample(
        self,
        parent_context: otel_context.Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Mapping[str, Any] | None = None,
        links: Any | None = None,
        trace_state: Any | None = None,
    ) -> SamplingResult:
        parent_span = get_current_span(parent_context)
        parent_context_obj = parent_span.get_span_context()
        if parent_context_obj.is_valid and not parent_context_obj.is_remote:
            return self._root.should_sample(
                parent_context,
                trace_id,
                name,
                kind,
                attributes,
                links,
                trace_state,
            )
        if (
            parent_context_obj.is_valid
            and parent_context_obj.is_remote
            and _TRUSTED_STORED_PARENT.get()
        ):
            return self._root.should_sample(
                parent_context,
                trace_id,
                name,
                kind,
                attributes,
                links,
                trace_state,
            )
        if self._rate >= 1.0:
            decision = Decision.RECORD_AND_SAMPLE
        elif self._rate <= 0.0:
            decision = Decision.DROP
        elif (trace_id & _TRACE_ID_MASK) < int(self._rate * (1 << 64)):
            decision = Decision.RECORD_AND_SAMPLE
        else:
            decision = Decision.DROP
        return SamplingResult(decision, attributes, trace_state)


class ResilientExporter(SpanExporter):
    """Bounded wrapper: telemetry failure never fails business work.

    Export errors are swallowed and counted. After
    ``max_consecutive_failures`` the circuit opens for ``cooldown_seconds``
    and spans are dropped instead of retried, so a dead backend cannot grow
    queues, threads, or latency without bound. Always reports SUCCESS to the
    batch processor because failed spans are intentionally not requeued.
    """

    def __init__(
        self,
        delegate: SpanExporter,
        *,
        max_consecutive_failures: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._delegate = delegate
        self._max_consecutive_failures = max_consecutive_failures
        self._cooldown_seconds = cooldown_seconds
        self.attempts = 0
        self.failures = 0
        self.dropped_while_open = 0
        self._consecutive_failures = 0
        self._open_until = 0.0

    @property
    def delegate(self) -> SpanExporter:
        return self._delegate

    def _circuit_open(self) -> bool:
        if self._consecutive_failures < self._max_consecutive_failures:
            return False
        if time.monotonic() >= self._open_until:
            self._consecutive_failures = 0
            return False
        return True

    def export(self, spans: Any) -> SpanExportResult:
        if self._circuit_open():
            try:
                self.dropped_while_open += len(spans)
            except TypeError:  # spans should be sized
                self.dropped_while_open += 1
            return SpanExportResult.SUCCESS
        self.attempts += 1
        try:
            result = self._delegate.export(spans)
        except Exception:  # noqa: BLE001 - telemetry must never raise
            result = SpanExportResult.FAILURE
        if result is SpanExportResult.FAILURE:
            self.failures += 1
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_consecutive_failures:
                self._open_until = time.monotonic() + self._cooldown_seconds
        else:
            self._consecutive_failures = 0
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        try:
            self._delegate.shutdown()
        except Exception:  # noqa: BLE001, S110 - shutdown stays best-effort
            pass


def build_batch_processor(exporter: SpanExporter) -> BatchSpanProcessor:
    return BatchSpanProcessor(
        exporter,
        schedule_delay_millis=2000,
        max_queue_size=2048,
        max_export_batch_size=512,
        export_timeout_millis=5000,
    )


def _build_exporter() -> SpanExporter | None:
    """Production exporter, only when explicitly enabled.

    Ordinary local runs export nothing. Returns None when disabled or when
    construction fails, so telemetry setup can never break startup.
    """
    enabled = os.environ.get("TRACE_EXPORT_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not enabled:
        return None
    try:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or None
        if project_id is not None:
            return CloudTraceSpanExporter(project_id=project_id)
        return CloudTraceSpanExporter()
    except Exception:  # noqa: BLE001 - export is optional, never fatal
        return None


@dataclass
class TracingState:
    """Lifespan-owned tracing setup for one service process."""

    service: str
    revision: str
    provider: TracerProvider
    processor: BatchSpanProcessor | None
    exporter: ResilientExporter | None
    sampler: BoundarySampler
    sample_rate: float
    tracer: Tracer = field(init=False)

    def __post_init__(self) -> None:
        self.tracer = self.provider.get_tracer(
            f"phase21.{self.service}", schema_url=None
        )

    def flush(self, timeout_seconds: float = REQUEST_FLUSH_TIMEOUT_SECONDS) -> bool:
        try:
            return bool(
                self.provider.force_flush(
                    timeout_millis=max(1, int(timeout_seconds * 1000))
                )
            )
        except Exception:  # noqa: BLE001 - flush is best-effort
            return False

    def shutdown(self) -> None:
        try:
            self.provider.shutdown()
        except Exception:  # noqa: BLE001, S110 - shutdown stays best-effort
            pass


def init_tracing(
    service: str,
    *,
    exporter: SpanExporter | None = None,
    sample_rate: float | None = None,
) -> TracingState:
    """Create an isolated tracer provider; safe to call repeatedly.

    Each call builds a fresh provider (never touches the global one), so
    repeated factory construction and lifespan cycles cannot clash. Pass an
    in-memory exporter in tests; production builds the Cloud Trace exporter
    only when TRACE_EXPORT_ENABLED is set.
    """
    rate = sample_rate
    if rate is None:
        rate = read_sample_rate(os.environ.get("TRACE_SAMPLE_RATE"))
    sampler = BoundarySampler(rate)
    resource = Resource.create(
        {"service.name": service, "service.version": get_service_revision()}
    )
    provider = TracerProvider(sampler=sampler, resource=resource)
    delegate = exporter if exporter is not None else _build_exporter()
    resilient: ResilientExporter | None = None
    processor: BatchSpanProcessor | None = None
    if delegate is not None:
        resilient = (
            delegate
            if isinstance(delegate, ResilientExporter)
            else ResilientExporter(delegate)
        )
        processor = build_batch_processor(resilient)
        provider.add_span_processor(processor)
    return TracingState(
        service=service,
        revision=get_service_revision(),
        provider=provider,
        processor=processor,
        exporter=resilient,
        sampler=sampler,
        sample_rate=rate,
    )


def shutdown_tracing(state: TracingState | None) -> None:
    if state is not None:
        state.shutdown()


def flush_tracing(
    state: TracingState | None,
    timeout_seconds: float = REQUEST_FLUSH_TIMEOUT_SECONDS,
) -> bool:
    if state is None:
        return True
    return state.flush(timeout_seconds)


def pending_span_count(state: TracingState) -> int:
    """Current batch-queue depth for bounded-accumulation assertions.

    Reads the SDK's internal queue (versions are pinned); unknown layouts
    report 0 rather than failing business paths.
    """
    try:
        processor = state.processor
        inner = getattr(processor, "_batch_processor", processor)
        queue = getattr(inner, "_queue", None)
        if queue is None:
            queue = getattr(inner, "queue", None)
        return int(queue.qsize())
    except Exception:  # noqa: BLE001 - introspection is best-effort
        return 0


class _HeaderGetter(Getter[dict[str, str]]):
    def get(self, carrier: dict[str, str], key: str) -> list[str] | None:
        value = carrier.get(key.lower())
        return [value] if value is not None else None

    def keys(self, carrier: dict[str, str]) -> list[str]:
        return list(carrier.keys())


class _DictSetter(Setter[dict[str, str]]):
    def set(self, carrier: dict[str, str], key: str, value: str) -> None:
        carrier[key] = value


def _headers_to_dict(
    headers: Mapping[str, str] | Mapping[bytes, bytes] | list[tuple[bytes, bytes]],
) -> dict[str, str]:
    if isinstance(headers, Mapping):
        items = headers.items()  # type: ignore[union-attr]
        result: dict[str, str] = {}
        for key, value in items:
            name = (
                key.decode("latin-1") if isinstance(key, bytes) else str(key)
            ).lower()
            text = value.decode("latin-1") if isinstance(value, bytes) else str(value)
            result[name] = text
        return result
    result = {}
    for key, value in headers:
        name = (
            key.decode("latin-1") if isinstance(key, bytes) else str(key)
        ).lower()
        text = value.decode("latin-1") if isinstance(value, bytes) else str(value)
        result[name] = text
    return result


def extract_boundary_context(
    headers: Mapping[str, str] | Mapping[bytes, bytes] | list[tuple[bytes, bytes]],
) -> otel_context.Context:
    """Extract W3C trace context from untrusted request headers.

    Uses only the dedicated trace-context propagator (never the global
    composite, never baggage). Malformed headers yield an invalid context,
    which starts a fresh local trace.
    """
    carrier = _headers_to_dict(headers)
    try:
        return _propagator.extract(carrier, getter=_HeaderGetter())
    except Exception:  # noqa: BLE001 - malformed input starts fresh
        return otel_context.get_current()


def inject_traceparent(carrier: dict[str, str]) -> None:
    """Inject the active context as W3C traceparent into a carrier mapping.

    Uses only the dedicated trace-context propagator so baggage is never
    emitted alongside the traceparent.
    """
    _propagator.inject(carrier, setter=_DictSetter())


def extract_stored_context(traceparent: str | None) -> otel_context.Context | None:
    """Validate a persisted W3C traceparent for reuse as a stored parent.

    Returns None for missing, malformed, overlong, or zero-ID values. A
    same-ID replay never changes the stored value; callers reuse it as-is.
    """
    if not traceparent:
        return None
    text = traceparent.strip()
    # Version-00 traceparent maximum is 55 characters; longer values carry
    # untrusted extensions we do not store or forward.
    if len(text) > 55:
        return None
    try:
        context = _propagator.extract({"traceparent": text}, getter=_HeaderGetter())
    except Exception:  # noqa: BLE001 - invalid input means no parent
        return None
    span_context = get_current_span(context).get_span_context()
    if not span_context.is_valid:
        return None
    if span_context.trace_id == 0 or span_context.span_id == 0:
        return None
    return context


@contextmanager
def start_safe_span(
    tracer: Tracer,
    name: str,
    *,
    context: otel_context.Context | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[Span]:
    """Start a span that never records exceptions automatically.

    The SDK's ``start_as_current_span`` attaches the escaped exception as
    an event on exit, which would bypass the attribute allowlist with raw
    messages and tracebacks. This helper manages the span manually:
    failures carry only the bounded outcome set via ``set_span_outcome``
    by the caller (or middleware), never exception text.
    """
    span = tracer.start_span(
        name,
        context=context,
        kind=kind,
        attributes=dict(safe_span_attributes(dict(attributes or {}))),
    )
    with trace.use_span(span, end_on_exit=False):
        try:
            yield span
        finally:
            # End here only if the body did not end it already; ending an
            # ended span is a no-op guard via is_recording().
            if span.is_recording():
                try:
                    span.end()
                except Exception:  # noqa: BLE001, S110 - telemetry never raises
                    pass


@contextmanager
def start_stored_span(
    tracer: Tracer,
    stored_context: otel_context.Context,
    name: str,
    *,
    attributes: Mapping[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Iterator[Span]:
    """Start a span under a validated stored parent, inheriting its decision."""
    token = _TRUSTED_STORED_PARENT.set(True)
    try:
        with start_safe_span(
            tracer, name, context=stored_context, kind=kind, attributes=attributes
        ) as span:
            yield span
    finally:
        _TRUSTED_STORED_PARENT.reset(token)


def safe_span_attributes(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Filter span attributes through the explicit allowlist.

    Unknown keys are dropped; only scalar values pass. Booleans are kept as
    booleans (checked before int since bool subclasses int).
    """
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in ALLOWED_SPAN_ATTRIBUTE_KEYS:
            continue
        if isinstance(value, (bool, int, float, str)):
            safe[key] = value
    return safe


def add_safe_event(span: Span | NonRecordingSpan, name: str, **fields: Any) -> None:
    """Attach a span event with only allowlisted scalar fields."""
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in ALLOWED_EVENT_FIELDS:
            continue
        if isinstance(value, (bool, int, float, str)):
            safe[key] = value
    try:
        span.add_event(name, attributes=safe)
    except Exception:  # noqa: BLE001, S110 - telemetry must never raise
        pass


def set_span_outcome(
    span: Span | NonRecordingSpan,
    outcome: str,
    *,
    error_code: str | None = None,
) -> None:
    """Record a bounded outcome/status without exception text.

    Never calls record_exception: failures carry only a safe category, never
    raw messages or tracebacks.
    """
    bounded = outcome if outcome in OUTCOMES else OUTCOME_SERVER_ERROR
    attributes: dict[str, Any] = {"outcome": bounded}
    if error_code is not None:
        attributes["error_code"] = str(error_code)[:64]
    try:
        span.set_attributes(attributes)
        if bounded in (OUTCOME_SERVER_ERROR, OUTCOME_INTERRUPTED):
            span.set_status(Status(StatusCode.ERROR, bounded))
        else:
            span.set_status(Status(StatusCode.OK))
    except Exception:  # noqa: BLE001, S110 - telemetry must never raise
        pass


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path.startswith("/"):
        return path
    return "unknown"


class TracingMiddleware:
    """Pure ASGI server-span middleware; never consumes bodies or buffers."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        state_provider: Callable[[], TracingState | None],
    ) -> None:
        self.app = app
        self.state_provider = state_provider

    def _record_failed_probe_span(
        self,
        state: TracingState,
        scope: Scope,
        boundary: otel_context.Context,
    ) -> None:
        """Record one post-hoc server span for a failed health probe.

        Successful probes never become spans; failing ones carry only the
        fixed name and allowlisted attributes, never bodies or headers.
        """
        method = str(scope.get("method", ""))[:16]
        route = _route_template(scope)
        status_code = int(scope.get("phase21.response_status", 500))
        outcome = outcome_for_status(status_code)
        if scope.get("phase21.client_disconnected"):
            outcome = OUTCOME_INTERRUPTED
        # Manual lifecycle: start_as_current_span would record an escaped
        # exception as an event on exit, bypassing the attribute allowlist.
        span = state.tracer.start_span(
            f"{method} {route}",
            context=boundary,
            kind=SpanKind.SERVER,
            attributes=safe_span_attributes(
                {
                    "http.method": method,
                    "http.route": route,
                    "http.status_code": status_code,
                    "outcome": outcome,
                }
            ),
        )
        set_span_outcome(span, outcome)
        try:
            span.end()
        except Exception:  # noqa: BLE001, S110 - telemetry never raises
            pass

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = self.state_provider()
        if state is None:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in HEALTH_PATHS:
            # Successful health probes keep log coverage but never become
            # spans. Failing probes are traceable: run the probe under a
            # non-recording span, then record a post-hoc server span when
            # the probe fails so outages stay visible in traces.
            boundary = extract_boundary_context(scope.get("headers", []))
            try:
                with trace.use_span(
                    NonRecordingSpan(SpanContext(0, 0, False)), end_on_exit=True
                ):
                    await self.app(scope, receive, send)
            except BaseException:
                self._record_failed_probe_span(state, scope, boundary)
                await run_in_threadpool(
                    state.flush, REQUEST_FLUSH_TIMEOUT_SECONDS
                )
                raise
            status_code = int(scope.get("phase21.response_status", 500))
            if status_code >= 400:
                self._record_failed_probe_span(state, scope, boundary)
                await run_in_threadpool(
                    state.flush, REQUEST_FLUSH_TIMEOUT_SECONDS
                )
            return

        boundary = extract_boundary_context(scope.get("headers", []))
        span_ended = False

        async def send_with_completion(message: Message) -> None:
            nonlocal span_ended
            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
                and not span_ended
            ):
                span_ended = True
                # End the span and flush before the final chunk completes
                # the response, off the event loop so streaming stays async.
                finish_request_span(scope, message)
                await run_in_threadpool(
                    state.flush, REQUEST_FLUSH_TIMEOUT_SECONDS
                )
            await send(message)

        def receive_with_disconnect() -> Receive:
            inner_receive = receive

            async def receive_once() -> Message:
                message = await inner_receive()
                if message["type"] == "http.disconnect":
                    scope["phase21.client_disconnected"] = True
                return message

            return receive_once

        # Manual span lifecycle: start_as_current_span would record an
        # escaped exception as an event on exit, bypassing the
        # allowlist with raw messages and tracebacks.
        span = state.tracer.start_span(
            REQUEST_SPAN_NAME,
            context=boundary,
            kind=SpanKind.SERVER,
            attributes={"http.method": str(scope.get("method", ""))[:16]},
        )
        with trace.use_span(span, end_on_exit=False):
            try:
                await self.app(
                    scope, receive_with_disconnect(), send_with_completion
                )
                if not span_ended:
                    # Non-streaming short-circuit or empty body.
                    span_ended = True
                    finish_request_span(scope, None)
                    await run_in_threadpool(
                        state.flush, REQUEST_FLUSH_TIMEOUT_SECONDS
                    )
            except BaseException:
                if not span_ended:
                    # Bounded outcome/attributes only; the exception
                    # itself is never recorded. Flush (bounded) so the
                    # error span is not stranded in the batch queue.
                    span_ended = True
                    finish_request_span(scope, None)
                    await run_in_threadpool(
                        state.flush, REQUEST_FLUSH_TIMEOUT_SECONDS
                    )
                raise


def finish_request_span(scope: Scope, final_message: Message | None) -> None:
    """Name, attribute, and end the active server span (span still attached)."""
    del final_message
    span = get_current_span()
    route = _route_template(scope)
    status_code = int(scope.get("phase21.response_status", 500))
    method = str(scope.get("method", ""))[:16]
    outcome = outcome_for_status(status_code)
    if scope.get("phase21.client_disconnected"):
        outcome = OUTCOME_INTERRUPTED
    try:
        span.update_name(f"{method} {route}")
    except Exception:  # noqa: BLE001, S110 - naming is best-effort
        pass
    try:
        span.set_attributes(
            safe_span_attributes(
                {
                    "http.method": method,
                    "http.route": route,
                    "http.status_code": status_code,
                    "outcome": outcome,
                }
            )
        )
    except Exception:  # noqa: BLE001, S110 - telemetry must never raise
        pass
    set_span_outcome(span, outcome)
    try:
        span.end()
    except Exception:  # noqa: BLE001, S110 - telemetry must never raise
        pass


class ResponseStatusMiddleware:
    """Tiny pure-ASGI helper recording the response status on the scope.

    Starlette's router mutates the same scope dict, but the status code only
    exists on the wire; this records it so the tracing/logging middlewares
    can attribute the completed exchange without parsing anything.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_status(message: Message) -> None:
            if message["type"] == "http.response.start":
                scope["phase21.response_status"] = int(message.get("status", 500))
            await send(message)

        await self.app(scope, receive, send_with_status)


async def flush_before_response_complete(
    state: TracingState | None,
) -> bool:
    """Bounded off-event-loop flush helper for terminal SSE/worker paths."""
    if state is None:
        return True
    return await run_in_threadpool(state.flush, REQUEST_FLUSH_TIMEOUT_SECONDS)


async def traced_lifespan_shutdown(state: TracingState | None) -> None:
    """Shutdown cleanup helper used by application lifespans."""
    if state is None:
        return
    await run_in_threadpool(state.shutdown)


__all__ = [
    "BoundarySampler",
    "ResilientExporter",
    "ResponseStatusMiddleware",
    "TracingMiddleware",
    "TracingState",
]
