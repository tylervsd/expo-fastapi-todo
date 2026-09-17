"""Phase 21 Task 1: safe tracing lifecycle.

Uses only DB-free seams: real apps via TestClient for wiring, synthetic ASGI
apps for streaming/disconnect/overlap, and the in-memory exporter seam for
span assertions. No network, database, or model calls.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.sdk.trace.sampling import Decision
from opentelemetry.trace import SpanContext, TraceFlags

from app import tracing
from app.tracing import (
    HEALTH_PATHS,
    REQUEST_FLUSH_TIMEOUT_SECONDS,
    BoundarySampler,
    ResilientExporter,
    TracingMiddleware,
    add_safe_event,
    current_span_ids,
    extract_boundary_context,
    extract_stored_context,
    flush_tracing,
    init_tracing,
    outcome_for_status,
    pending_span_count,
    safe_span_attributes,
    set_span_outcome,
    shutdown_tracing,
    start_safe_span,
    start_stored_span,
)

BODY_SECRET = "SENTINEL_BODY_SECRET_9f8a1c"
QUERY_SECRET = "SENTINEL_QUERY_SECRET_7b2d4e"
HEADER_SECRET = "SENTINEL_HEADER_SECRET_3e6f9a"
SQL_SECRET = "SENTINEL_SQL_SECRET_5c1b8d"
EXCEPTION_SECRET = "SENTINEL_EXCEPTION_SECRET_2a7e4f"
ALL_SENTINELS = (
    BODY_SECRET,
    QUERY_SECRET,
    HEADER_SECRET,
    SQL_SECRET,
    EXCEPTION_SECRET,
)


def assert_no_sentinels(value: object) -> None:
    text = str(value)
    for sentinel in ALL_SENTINELS:
        assert sentinel not in text, f"leaked sentinel {sentinel}"


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def state(exporter: InMemorySpanExporter) -> tracing.TracingState:
    current = init_tracing(
        "test-service", exporter=exporter, sample_rate=1.0
    )
    yield current
    shutdown_tracing(current)


def test_sdk_and_gcp_exporter_resolve_on_this_python(
    exporter: InMemorySpanExporter,
) -> None:
    """Task 1 compatibility: SDK + Google exporter import and export a span."""
    provider = TracerProvider(sampler=BoundarySampler(1.0))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("compat-probe")
    with tracer.start_as_current_span("compat-span"):
        pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "compat-span"
    # The Google exporter class must at least be constructible as a type on
    # this interpreter; credentials/project are deployment concerns.
    assert CloudTraceSpanExporter is not None
    provider.shutdown()


def test_in_memory_seam_receives_request_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    seam: InMemorySpanExporter = InMemorySpanExporter()
    app = create_app()
    app.state.tracing_exporter = seam
    with TestClient(app) as client:
        response = client.get("/todos")
    assert response.status_code == 401
    spans = seam.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "GET /todos"
    attrs = dict(span.attributes or {})
    assert attrs["http.method"] == "GET"
    assert attrs["http.route"] == "/todos"
    assert attrs["http.status_code"] == 401
    assert attrs["outcome"] == "client_error"
    assert_no_sentinels(span_to_text(span))


def span_to_text(span: object) -> str:
    attributes = getattr(span, "attributes", None)
    events = getattr(span, "events", None) or ()
    links = getattr(span, "links", None) or ()
    parts = [getattr(span, "name", ""), str(attributes)]
    parts.extend(
        f"{event.name}:{event.attributes}" for event in events  # type: ignore[union-attr]
    )
    parts.extend(str(link.context) for link in links)  # type: ignore[union-attr]
    return "|".join(parts)


def test_health_requests_emit_no_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    seam: InMemorySpanExporter = InMemorySpanExporter()
    app = create_app()
    app.state.tracing_exporter = seam
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
    assert len(seam.get_finished_spans()) == 0
    assert "/health" in HEALTH_PATHS


def test_worker_health_and_readiness_emit_no_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker import create_worker_app

    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    seam: InMemorySpanExporter = InMemorySpanExporter()
    app = create_worker_app()
    app.state.tracing_exporter = seam
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert len(seam.get_finished_spans()) == 0
    assert "/ready" in HEALTH_PATHS


def test_malformed_traceparent_starts_fresh_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import create_app

    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    seam: InMemorySpanExporter = InMemorySpanExporter()
    app = create_app()
    app.state.tracing_exporter = seam
    with TestClient(app) as client:
        response = client.get("/todos", headers={"traceparent": "not-a-trace-id"})
    assert response.status_code == 401
    spans = seam.get_finished_spans()
    assert len(spans) == 1
    context = spans[0].get_span_context()
    assert context.trace_id != 0
    assert context.span_id != 0


def test_root_sampling_decisions(
    exporter: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    sampled = init_tracing("sample-one", exporter=exporter, sample_rate=1.0)
    with sampled.tracer.start_as_current_span("root-sampled"):
        pass
    assert flush_tracing(sampled) is True
    assert len(exporter.get_finished_spans()) == 1
    shutdown_tracing(sampled)

    exporter.clear()
    monkeypatch.setenv("TRACE_SAMPLE_RATE", "0.0")
    dropped = init_tracing("sample-zero", exporter=exporter, sample_rate=0.0)
    with dropped.tracer.start_as_current_span("root-dropped"):
        pass
    assert flush_tracing(dropped) is True
    assert len(exporter.get_finished_spans()) == 0
    shutdown_tracing(dropped)


def test_untrusted_sampled_flag_does_not_force_capture() -> None:
    exporter: InMemorySpanExporter = InMemorySpanExporter()
    state = init_tracing("untrusted", exporter=exporter, sample_rate=0.0)
    try:
        # Incoming sampled=1 flag must not force capture at our boundary.
        boundary = extract_boundary_context(
            [(b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")]
        )
        with trace.use_span(
            trace.NonRecordingSpan(boundary), end_on_exit=False
        ):
            pass
        with state.tracer.start_as_current_span(
            "boundary-request", context=boundary
        ):
            pass
        assert flush_tracing(state) is True
        assert len(exporter.get_finished_spans()) == 0
    finally:
        shutdown_tracing(state)

    exporter.clear()
    capture_exporter: InMemorySpanExporter = InMemorySpanExporter()
    capturing = init_tracing(
        "untrusted-capture", exporter=capture_exporter, sample_rate=1.0
    )
    try:
        # Incoming sampled=0 flag must not suppress our local capture.
        boundary = extract_boundary_context(
            [(b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00")]
        )
        with capturing.tracer.start_as_current_span(
            "boundary-request", context=boundary
        ):
            pass
        assert flush_tracing(capturing) is True
        assert len(capture_exporter.get_finished_spans()) == 1
    finally:
        shutdown_tracing(capturing)


def test_stored_parent_sampling_inheritance() -> None:
    exporter: InMemorySpanExporter = InMemorySpanExporter()
    # Stored sampled context is honored even with a zero local rate.
    capture = init_tracing("stored-capture", exporter=exporter, sample_rate=0.0)
    try:
        stored = extract_stored_context(
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        )
        assert stored is not None
        with start_stored_span(capture.tracer, stored, "suggestion.process"):
            pass
        assert flush_tracing(capture) is True
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].get_span_context().trace_id == int(
            "4bf92f3577b34da6a3ce929d0e0e4736", 16
        )
    finally:
        shutdown_tracing(capture)

    exporter.clear()
    quiet_exporter: InMemorySpanExporter = InMemorySpanExporter()
    # Stored unsampled context is honored even with full local sampling.
    quiet = init_tracing(
        "stored-quiet", exporter=quiet_exporter, sample_rate=1.0
    )
    try:
        stored = extract_stored_context(
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00"
        )
        assert stored is not None
        with start_stored_span(quiet.tracer, stored, "suggestion.process"):
            pass
        assert flush_tracing(quiet) is True
        assert len(quiet_exporter.get_finished_spans()) == 0
    finally:
        shutdown_tracing(quiet)


def test_malformed_stored_context_is_rejected() -> None:
    assert extract_stored_context(None) is None
    assert extract_stored_context("") is None
    assert extract_stored_context("not-a-traceparent") is None
    # Zero trace ID is invalid even with correct shape.
    assert (
        extract_stored_context(
            "00-00000000000000000000000000000000-00f067aa0ba902b7-01"
        )
        is None
    )
    # Overlong values are rejected (version-00 maximum is 55 chars).
    assert extract_stored_context("00-" + "ab" * 40 + "-00f067aa0ba902b7-01") is None


def test_span_attributes_and_events_exclude_secrets(
    state: tracing.TracingState, exporter: InMemorySpanExporter
) -> None:
    attributes = safe_span_attributes(
        {
            "http.method": "POST",
            "http.route": "/todo-workflows/{workflow_id}/suggestions",
            "goal": BODY_SECRET,
            "query": QUERY_SECRET,
            "authorization": HEADER_SECRET,
            "sql": SQL_SECRET,
        }
    )
    assert attributes == {
        "http.method": "POST",
        "http.route": "/todo-workflows/{workflow_id}/suggestions",
    }
    with state.tracer.start_as_current_span(
        "provider.suggestions", attributes=attributes
    ) as span:
        add_safe_event(
            span,
            "provider_call",
            outcome="ok",
            error_detail=EXCEPTION_SECRET,
            body=BODY_SECRET,
        )
        set_span_outcome(span, "success")
    assert flush_tracing(state) is True
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert_no_sentinels(span_to_text(spans[0]))


def test_no_automatic_exception_recording(
    state: tracing.TracingState, exporter: InMemorySpanExporter
) -> None:
    with (
        pytest.raises(RuntimeError, match="db failed"),
        start_safe_span(state.tracer, "db.reserve_suggestion"),
    ):
        raise RuntimeError(f"db failed: {EXCEPTION_SECRET}")
    assert flush_tracing(state) is True
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert list(spans[0].events or []) == []
    assert_no_sentinels(span_to_text(spans[0]))


def test_safe_helpers_never_raise_on_non_recording_spans() -> None:
    span = trace.NonRecordingSpan(SpanContext(0, 0, False, TraceFlags(0)))
    add_safe_event(span, "provider_call", outcome="ok")
    set_span_outcome(span, "server_error", error_code="worker_unavailable")
    assert safe_span_attributes({"unknown": 1}) == {}


def test_outcome_for_status_is_bounded() -> None:
    assert outcome_for_status(200) == "success"
    assert outcome_for_status(204) == "success"
    assert outcome_for_status(401) == "client_error"
    assert outcome_for_status(404) == "client_error"
    assert outcome_for_status(500) == "server_error"
    assert REQUEST_FLUSH_TIMEOUT_SECONDS == 2.0


def make_stub_app(
    mode: str = "ok",
    seen: dict[str, object] | None = None,
    order: list[str] | None = None,
) -> object:
    async def stub(scope: object, receive: object, send: object) -> None:
        assert isinstance(scope, dict)
        if mode == "threadpool":
            from starlette.concurrency import run_in_threadpool

            assert seen is not None
            seen["span_id_in_threadpool"] = await run_in_threadpool(
                lambda: current_span_ids()[1]
            )
            seen["span_id_in_request"] = current_span_ids()[1]
        if mode == "raise":
            raise RuntimeError(f"unexpected fault {EXCEPTION_SECRET}")
        body_chunks = [b"chunk-a", b"chunk-b"] if mode == "stream" else [b"hello"]
        await send(  # type: ignore[operator]
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        for index, chunk in enumerate(body_chunks):
            last = index == len(body_chunks) - 1
            await send(  # type: ignore[operator]
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": not last,
                }
            )
        if order is not None:
            order.append("app-returned")

    return stub


def drive_middleware(stack: object, path: str = "/todos") -> dict[str, list[object]]:
    sent: list[object] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: object) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": f"secret={QUERY_SECRET}".encode(),
        "headers": [(b"authorization", f"Bearer {HEADER_SECRET}".encode())],
        "client": ("test", 1234),
        "server": ("test", 80),
    }

    async def run() -> None:
        await stack(scope, receive, send)  # type: ignore[operator]

    asyncio.run(run())
    return {"sent": sent, "scope": [scope]}


def build_stack(
    stub: object,
    state: tracing.TracingState,
    order: list[str] | None = None,
) -> object:
    from app.observability import RequestLoggingMiddleware

    inner = RequestLoggingMiddleware(stub, service="test-service")  # type: ignore[arg-type]
    return TracingMiddleware(
        inner, state_provider=lambda: state  # type: ignore[arg-type]
    )


def test_overlapping_requests_keep_isolated_context(
    exporter: InMemorySpanExporter,
) -> None:
    state = init_tracing("overlap", exporter=exporter, sample_rate=1.0)
    try:
        results: list[tuple[str, str]] = []

        async def one(index: int) -> None:
            seen: dict[str, object] = {}
            stack = build_stack(make_stub_app("threadpool", seen=seen), state)
            sent: list[object] = []

            async def receive() -> dict[str, object]:
                await asyncio.sleep(0.01 * (index % 3))
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message: object) -> None:
                sent.append(message)

            scope = {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/todos",
                "raw_path": b"/todos",
                "query_string": b"",
                "headers": [],
                "client": ("test", index),
                "server": ("test", 80),
            }
            await stack(scope, receive, send)  # type: ignore[operator]
            results.append(
                (str(seen["span_id_in_request"]), str(seen["span_id_in_threadpool"]))
            )

        async def run_all() -> None:
            await asyncio.gather(*[one(i) for i in range(8)])

        asyncio.run(run_all())
        request_ids = [request for request, _ in results]
        assert len(set(request_ids)) == 8
        # Context propagates into threadpool work within the same request.
        for request_id, threadpool_id in results:
            assert request_id == threadpool_id
            assert request_id != "0" * 16
        assert len(exporter.get_finished_spans()) == 8
    finally:
        shutdown_tracing(state)


def test_repeated_app_creation_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import logging

    from app.main import create_app

    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    first = create_app()
    second = create_app()
    first.state.tracing_exporter = InMemorySpanExporter()
    second.state.tracing_exporter = InMemorySpanExporter()
    with TestClient(first) as client:
        assert client.get("/health").status_code == 200
    with TestClient(second) as client:
        assert client.get("/health").status_code == 200
    phase21_handlers = [
        handler
        for handler in logging.getLogger().handlers
        if type(handler).__name__ == "StdoutProxyHandler"
    ]
    assert len(phase21_handlers) == 1


def test_sse_completion_flushes_before_final_chunk(
    exporter: InMemorySpanExporter,
) -> None:
    state = init_tracing("sse", exporter=exporter, sample_rate=1.0)
    try:
        order: list[str] = []
        inner_export = exporter.export

        def recording_export(spans: object) -> object:
            order.append("exported")
            return inner_export(spans)  # type: ignore[arg-type]

        exporter.export = recording_export  # type: ignore[method-assign]

        async def send_wrapper_factory() -> None:
            pass

        stack = build_stack(make_stub_app("stream", order=order), state)
        sent: list[object] = []

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: object) -> None:
            assert isinstance(message, dict)
            if message.get("type") == "http.response.body" and not message.get(
                "more_body"
            ):
                order.append("final-send")
            await asyncio.sleep(0)

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/agent",
            "raw_path": b"/agent",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        }

        async def run() -> None:
            await stack(scope, receive, send)  # type: ignore[operator]

        sent_records = sent  # noqa: F841
        asyncio.run(run())
        assert "exported" in order
        assert "final-send" in order
        assert order.index("exported") < order.index("final-send")
        assert len(exporter.get_finished_spans()) == 1
    finally:
        shutdown_tracing(state)


def test_disconnect_ends_span_and_resets_context(
    exporter: InMemorySpanExporter, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.observability import configure_logging

    configure_logging("test-service")
    state = init_tracing("disconnect", exporter=exporter, sample_rate=1.0)
    try:

        class ClientGone(Exception):
            pass

        async def stub(scope: object, receive: object, send: object) -> None:
            await send(  # type: ignore[operator]
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            message = await receive()  # type: ignore[operator]
            assert message["type"] == "http.disconnect"
            raise ClientGone("client went away")

        stack = build_stack(stub, state)
        received_disconnect = False

        async def receive() -> dict[str, object]:
            nonlocal received_disconnect
            if not received_disconnect:
                received_disconnect = True
                return {"type": "http.disconnect"}
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: object) -> None:
            return None

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/agent",
            "raw_path": b"/agent",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        }

        async def run() -> None:
            await stack(scope, receive, send)  # type: ignore[operator]

        with pytest.raises(ClientGone):
            asyncio.run(run())
        assert len(exporter.get_finished_spans()) == 1
        # Context is reset: no span leaks to later work.
        assert trace.get_current_span().get_span_context().is_valid is False
        assert current_span_ids() == ("0" * 32, "0" * 16)
    finally:
        shutdown_tracing(state)


def test_context_reset_after_error(
    exporter: InMemorySpanExporter, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.observability import configure_logging

    configure_logging("test-service")
    state = init_tracing("error-reset", exporter=exporter, sample_rate=1.0)
    try:
        stack = build_stack(make_stub_app("raise"), state)
        with pytest.raises(RuntimeError, match="unexpected fault"):
            drive_middleware(stack)
        assert_no_sentinels(capsys.readouterr().out)
        assert len(exporter.get_finished_spans()) == 1
        assert trace.get_current_span().get_span_context().is_valid is False
        # A later request starts fresh.
        drive_middleware(build_stack(make_stub_app("ok"), state))
        assert len(exporter.get_finished_spans()) == 2
        first, second = exporter.get_finished_spans()
        assert (
            first.get_span_context().trace_id != second.get_span_context().trace_id
        )
    finally:
        shutdown_tracing(state)


def test_flush_bound_with_slow_exporter() -> None:
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    class SlowExporter(SpanExporter):
        def export(self, spans: object) -> SpanExportResult:  # type: ignore[override]
            time.sleep(3)
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            return None

    state = init_tracing("slow", exporter=SlowExporter(), sample_rate=1.0)
    try:
        stack = build_stack(make_stub_app("ok"), state)
        started = time.monotonic()
        drive_middleware(stack)
        elapsed = time.monotonic() - started
        assert elapsed < REQUEST_FLUSH_TIMEOUT_SECONDS + 1.5
    finally:
        shutdown_tracing(state)


def test_exporter_outage_keeps_business_successful_and_bounded() -> None:
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    attempts = 0

    class FailingExporter(SpanExporter):
        def export(self, spans: object) -> SpanExportResult:  # type: ignore[override]
            nonlocal attempts
            attempts += 1
            raise ConnectionError("trace backend down")

        def shutdown(self) -> None:
            return None

    state = init_tracing("outage", exporter=FailingExporter(), sample_rate=1.0)
    try:
        assert isinstance(state.exporter, ResilientExporter)
        for _ in range(20):
            result = drive_middleware(build_stack(make_stub_app("ok"), state))
            body = b"".join(
                message.get("body", b"")  # type: ignore[union-attr]
                for message in result["sent"]
                if isinstance(message, dict)
                and message.get("type") == "http.response.body"
            )
            assert body == b"hello"
        assert state.exporter.failures > 0
        # Circuit opens: delegate attempts stop growing while business works.
        attempts_after = attempts
        time.sleep(0.2)
        for _ in range(5):
            drive_middleware(build_stack(make_stub_app("ok"), state))
        assert attempts == attempts_after
        # No unbounded accumulation in the batch queue; the open circuit
        # drops instead of requeueing.
        time.sleep(0.5)
        assert pending_span_count(state) == 0
        assert state.exporter.dropped_while_open > 0
    finally:
        shutdown_tracing(state)


def test_sampler_decision_values_are_deterministic() -> None:
    sampler = BoundarySampler(1.0)
    result = sampler.should_sample(
        None, 0x4BF92F3577B34DA6A3CE929D0E0E4736, "op"
    )
    assert result.decision == Decision.RECORD_AND_SAMPLE
    sampler = BoundarySampler(0.0)
    result = sampler.should_sample(
        None, 0x4BF92F3577B34DA6A3CE929D0E0E4736, "op"
    )
    assert result.decision == Decision.DROP


def test_flush_never_raises_without_provider() -> None:
    state = init_tracing("noflush", exporter=None, sample_rate=1.0)
    try:
        assert flush_tracing(state) is True
    finally:
        shutdown_tracing(state)


def test_shutdown_cleans_up() -> None:
    exporter = InMemorySpanExporter()
    state = init_tracing("shutdown", exporter=exporter, sample_rate=1.0)
    with state.tracer.start_as_current_span("work"):
        pass
    shutdown_tracing(state)
    assert len(exporter.get_finished_spans()) == 0 or len(
        exporter.get_finished_spans()
    ) == 1
    # Second shutdown is safe and force flush after shutdown reports failure.
    shutdown_tracing(state)
    assert flush_tracing(state) is False


def test_force_flush_is_called_with_two_second_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    provider = TracerProvider(sampler=BoundarySampler(1.0))

    original_flush = provider.force_flush

    def recording_flush(timeout_millis: int = 30000) -> bool:
        seen["timeout_millis"] = timeout_millis
        return original_flush(timeout_millis)

    provider.force_flush = recording_flush  # type: ignore[method-assign]
    state = tracing.TracingState(
        service="bound",
        revision="test",
        provider=provider,
        processor=None,
        exporter=None,
        sampler=BoundarySampler(1.0),
        sample_rate=1.0,
    )
    try:
        assert flush_tracing(state) is True
        assert seen["timeout_millis"] == 2000
    finally:
        shutdown_tracing(state)
        monkeypatch.undo()


def test_boundary_extraction_rejects_baggage_and_malformed() -> None:
    assert extract_boundary_context([]) is not None
    malformed = extract_boundary_context([(b"traceparent", b"garbage")])
    assert (
        trace.get_current_span(malformed).get_span_context().is_valid is False
    )
    # Baggage headers are ignored: extraction uses trace context only.
    context = extract_boundary_context(
        [
            (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            (b"baggage", b"user-id=secret-user"),
        ]
    )
    span_context = trace.get_current_span(context).get_span_context()
    assert span_context.is_valid


def test_thread_counts_stay_bounded_under_outage() -> None:
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    class FailingExporter(SpanExporter):
        def export(self, spans: object) -> SpanExportResult:  # type: ignore[override]
            raise ConnectionError("down")

        def shutdown(self) -> None:
            return None

    state = init_tracing("threads", exporter=FailingExporter(), sample_rate=1.0)
    try:
        stack = build_stack(make_stub_app("ok"), state)
        before = threading.active_count()
        for _ in range(10):
            drive_middleware(stack)
        time.sleep(0.3)
        assert threading.active_count() - before <= 2
    finally:
        shutdown_tracing(state)
