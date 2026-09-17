"""Phase 21 Task 1: structured logging lifecycle.

Asserts on serialized stdout/stderr output (not just caplog): sentinel
body/query/header/SQL/exception values must never appear in application log
lines, third-party records are redacted, and request logs carry safe fields
plus active trace correlation. No database calls.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.observability import (
    APP_LOGGER_NAME,
    configure_logging,
    disable_uvicorn_access_logs,
    get_request_id,
    log_event,
    log_unexpected_fault,
)
from app.tracing import current_span_ids as current_trace_ids
from app.tracing import init_tracing, shutdown_tracing

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


@pytest.fixture(autouse=True)
def configured() -> logging.Logger:
    return configure_logging("test-service")


def read_json_lines(output: str) -> list[dict[str, object]]:
    lines = [line for line in output.splitlines() if line.strip()]
    assert lines, "expected serialized log output"
    return [json.loads(line) for line in lines]


def assert_no_sentinels(records: list[dict[str, object]]) -> None:
    text = json.dumps(records)
    for sentinel in ALL_SENTINELS:
        assert sentinel not in text, f"leaked sentinel {sentinel}"


def test_log_event_redacts_hostile_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_event(
        "provider_call",
        outcome="transport_error",
        suggestion_id=42,
        attempt_id="attempt-1",
        goal=BODY_SECRET,
        query=QUERY_SECRET,
        authorization=HEADER_SECRET,
        sql=SQL_SECRET,
        exc_text=EXCEPTION_SECRET,
    )
    records = read_json_lines(capsys.readouterr().out)
    assert_no_sentinels(records)
    assert records[-1]["event"] == "provider_call"
    assert records[-1]["outcome"] == "transport_error"
    assert records[-1]["suggestion_id"] == 42
    assert records[-1]["attempt_id"] == "attempt-1"
    assert records[-1]["severity"] == "INFO"
    assert "service" in records[-1]
    assert "revision" in records[-1]


def test_exception_records_exclude_traceback_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = logging.getLogger(APP_LOGGER_NAME)
    try:
        raise ValueError(f"query failed: {SQL_SECRET} {EXCEPTION_SECRET}")
    except ValueError:
        logger.exception("database operation failed")
    records = read_json_lines(capsys.readouterr().out)
    assert_no_sentinels(records)
    assert "Traceback" not in json.dumps(records)
    # Direct logger calls lack a validated event: the caller-controlled
    # message is never serialized, only a fixed redaction notice.
    assert records[-1]["event"] == "direct_log"
    assert records[-1]["message"] == "Direct log record redacted."


def test_direct_app_logger_calls_are_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.info("user said %s", BODY_SECRET)
    logger.info(f"query {QUERY_SECRET} header {HEADER_SECRET}")
    logger.warning("worker state %s", SQL_SECRET)
    try:
        raise ValueError(EXCEPTION_SECRET)
    except ValueError:
        logger.exception("direct exception with traceback")
    records = read_json_lines(capsys.readouterr().out)
    assert_no_sentinels(records)
    assert "Traceback" not in json.dumps(records)
    assert records
    for record in records:
        assert record["event"] == "direct_log"
        assert record["message"] == "Direct log record redacted."


def test_direct_app_calls_keep_allowlisted_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Worker-style direct calls keep their allowlisted extra fields; only
    # the caller-controlled message is replaced with fixed safe output.
    logging.getLogger("app.worker").info(
        "suggestion_task",
        extra={
            "suggestion_id": 7,
            "outcome": "ready",
            "goal": BODY_SECRET,
        },
    )
    records = read_json_lines(capsys.readouterr().out)
    assert_no_sentinels(records)
    assert records[-1]["event"] == "direct_log"
    assert records[-1]["message"] == "Direct log record redacted."
    assert records[-1]["suggestion_id"] == 7
    assert records[-1]["outcome"] == "ready"


def test_production_uvicorn_handlers_cannot_bypass_formatter(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Production uvicorn installs its own plain-text handlers on
    # uvicorn.error with propagation disabled; those must be cleared so
    # startup/exception output can only flow through the safe formatter.
    error_logger = logging.getLogger("uvicorn.error")
    raw = io.StringIO()
    production_style = logging.StreamHandler(raw)
    production_style.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    error_logger.addHandler(production_style)
    error_logger.propagate = False
    try:
        configure_logging("test-service")
        assert error_logger.handlers == []
        assert error_logger.propagate is True
        error_logger.info("GET /todos?secret=%s", QUERY_SECRET)
        try:
            raise ValueError(EXCEPTION_SECRET)
        except ValueError:
            error_logger.exception("uvicorn worker crashed")
    finally:
        error_logger.handlers = []
        error_logger.propagate = True
    assert QUERY_SECRET not in raw.getvalue()
    assert EXCEPTION_SECRET not in raw.getvalue()
    records = read_json_lines(capsys.readouterr().out)
    assert_no_sentinels(records)
    assert "Traceback" not in json.dumps(records)
    assert records
    for record in records:
        assert record["event"] == "third_party_log"
        assert record["message"] == "Third-party log record redacted."


def test_generic_third_party_handlers_cannot_bypass_formatter(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Generic third-party loggers with their own plain handler and
    # propagate=False must also route through the safe root handler.
    vendor_logger = logging.getLogger("some.vendor.lib")
    raw = io.StringIO()
    plain = logging.StreamHandler(raw)
    plain.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    vendor_logger.addHandler(plain)
    vendor_logger.propagate = False
    try:
        configure_logging("test-service")
        assert vendor_logger.handlers == []
        assert vendor_logger.propagate is True
        # Routing generics must not re-enable duplicate access logs.
        access_logger = logging.getLogger("uvicorn.access")
        assert access_logger.disabled or not access_logger.isEnabledFor(
            logging.INFO
        )
        vendor_logger.info("query %s", QUERY_SECRET)
        try:
            raise ValueError(EXCEPTION_SECRET)
        except ValueError:
            vendor_logger.exception("vendor boom")
    finally:
        vendor_logger.handlers = []
        vendor_logger.propagate = True
    assert QUERY_SECRET not in raw.getvalue()
    assert EXCEPTION_SECRET not in raw.getvalue()
    records = read_json_lines(capsys.readouterr().out)
    assert_no_sentinels(records)
    assert "Traceback" not in json.dumps(records)
    assert records
    for record in records:
        assert record["event"] == "third_party_log"
        assert record["message"] == "Third-party log record redacted."


def test_third_party_records_are_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # uvicorn.error still flows (startup/exception output) and must be
    # sanitized; sqlalchemy stands in for other third-party libraries.
    logging.getLogger("uvicorn.error").info(
        'GET /todos?secret=%s "Bearer %s"', QUERY_SECRET, HEADER_SECRET
    )
    logging.getLogger("sqlalchemy.engine.Engine").info(
        "SELECT * FROM todos WHERE title = '%s'", SQL_SECRET
    )
    records = read_json_lines(capsys.readouterr().out)
    assert_no_sentinels(records)
    assert records[-1]["event"] == "third_party_log"
    assert records[-1]["logger"] in (
        "uvicorn.error",
        "sqlalchemy.engine.Engine",
    )
    assert (
        records[-1]["message"] == "Third-party log record redacted."
    )
    assert "code_location" in records[-1]


def test_uvicorn_access_logging_disabled_centrally(
    capsys: pytest.CaptureFixture[str],
) -> None:
    disable_uvicorn_access_logs()
    access_logger = logging.getLogger("uvicorn.access")
    assert access_logger.disabled or not access_logger.isEnabledFor(logging.INFO)
    # Disabled access output emits nothing: no duplicate, no leak.
    access_logger.info("GET /todos?secret=%s", QUERY_SECRET)
    assert QUERY_SECRET not in capsys.readouterr().out


def test_http_request_event_end_to_end(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.main import create_app

    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    configure_logging("todo-api")
    app = create_app()
    with TestClient(app) as client:
        # No credentials: 401 before any database work, keeping this test
        # DB-free. Header/query redaction is covered at the unit level.
        response = client.get(f"/todos?secret={QUERY_SECRET}")
    assert response.status_code == 401
    records = read_json_lines(capsys.readouterr().out)
    assert_no_sentinels(records)
    requests = [r for r in records if r.get("event") == "http_request"]
    assert requests, "expected an http_request event"
    entry = requests[-1]
    assert entry["method"] == "GET"
    assert entry["route"] == "/todos"
    assert entry["status_code"] == 401
    assert entry["outcome"] == "client_error"
    assert isinstance(entry["duration_ms"], int)
    assert len(entry["http_request_id"]) == 32
    assert len(entry["trace_id"]) == 32
    assert len(entry["span_id"]) == 16
    assert entry["trace_id"] != "0" * 32


def test_health_request_logged_without_span_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.main import create_app

    configure_logging("todo-api")
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    records = read_json_lines(capsys.readouterr().out)
    requests = [r for r in records if r.get("event") == "http_request"]
    assert requests
    assert requests[-1]["route"] == "/health"
    assert requests[-1]["trace_id"] == "0" * 32


def test_overlapping_requests_have_distinct_ids() -> None:
    from app.observability import RequestLoggingMiddleware
    from app.tracing import TracingMiddleware

    seen: list[tuple[str, str, str]] = []

    async def stub(scope: object, receive: object, send: object) -> None:
        from starlette.concurrency import run_in_threadpool

        assert isinstance(scope, dict)
        request_id = get_request_id()
        in_threadpool = await run_in_threadpool(get_request_id)
        seen.append((str(request_id), str(in_threadpool), str(scope["path"])))
        await send(  # type: ignore[operator]
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        await send(  # type: ignore[operator]
            {"type": "http.response.body", "body": b"ok", "more_body": False}
        )

    async def one(index: int) -> None:
        stack = TracingMiddleware(
            RequestLoggingMiddleware(stub, service="test-service"),  # type: ignore[arg-type]
            state_provider=lambda: None,
        )
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

        async def receive() -> dict[str, object]:
            await asyncio.sleep(0.01 * (index % 3))
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: object) -> None:
            return None

        await stack(scope, receive, send)  # type: ignore[operator]

    async def run_all() -> None:
        await asyncio.gather(*[one(i) for i in range(8)])

    asyncio.run(run_all())
    assert len(seen) == 8
    request_ids = [request for request, _, _ in seen]
    assert len(set(request_ids)) == 8
    for request_id, threadpool_id, _ in seen:
        assert request_id == threadpool_id
    # Context is reset after each request.
    assert get_request_id() is None


def test_repeated_configuration_adds_no_handlers() -> None:
    configure_logging("test-service")
    configure_logging("todo-api")
    count = sum(
        1
        for handler in logging.getLogger().handlers
        if type(handler).__name__ == "StdoutProxyHandler"
    )
    assert count == 1


def test_unexpected_fault_is_sanitized(
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        raise RuntimeError(f"raw failure: {EXCEPTION_SECRET}")
    except RuntimeError:
        # The exception instance is never attached: only a safe code travels.
        log_unexpected_fault("provider_timeout", location="test:1")
    records = read_json_lines(capsys.readouterr().out)
    assert_no_sentinels(records)
    assert "Traceback" not in json.dumps(records)
    assert records[-1]["event"] == "unexpected_fault"
    assert records[-1]["error_code"] == "provider_timeout"
    assert records[-1]["message"] == "Unexpected fault reported."


def test_trace_correlation_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    exporter = InMemorySpanExporter()
    state = init_tracing("correlation", exporter=exporter, sample_rate=1.0)
    try:
        with state.tracer.start_as_current_span("op"):
            trace_id, span_id = current_trace_ids()
            assert len(trace_id) == 32 and trace_id != "0" * 32
            log_event("provider_call", outcome="ok")
        records = read_json_lines(capsys.readouterr().out)
        entry = records[-1]
        assert entry["trace_id"] == trace_id
        assert entry["span_id"] == span_id
        assert entry["logging.googleapis.com/trace"] == (
            f"projects/test-project/traces/{trace_id}"
        )
    finally:
        shutdown_tracing(state)
        exporter.clear()


def test_worker_http_request_logged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.worker import create_worker_app

    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    configure_logging("todo-worker")
    app = create_worker_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    records = read_json_lines(capsys.readouterr().out)
    requests = [r for r in records if r.get("event") == "http_request"]
    assert requests
    assert requests[-1]["route"] == "/health"
    assert requests[-1]["outcome"] == "success"
