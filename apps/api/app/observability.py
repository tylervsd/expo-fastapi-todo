"""Phase 21 Task 1: structured JSON logging with an explicit field allowlist.

One JSON object per line on stdout. Application loggers (``app`` and its
children, e.g. ``app.worker``) emit allowlisted fields with fixed messages;
third-party records (uvicorn, sqlalchemy, httpx, ...) are redacted to a
fixed message with logger name and code location so they can never bypass
the output policy. Exception tracebacks are never serialized.

Uvicorn's duplicate access log is disabled centrally here (both factories
call ``configure_logging``), which survives Terraform command/args
overrides. The Dockerfile still passes ``--no-access-log`` as a second
layer. Cloud Run platform request logs are separate and untouched by this
formatter.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.tracing import current_span_ids, outcome_for_status

APP_LOGGER_NAME = "app"

# Explicit field allowlist shared with traces. IDs are diagnostic fields,
# never metric labels. Anything not listed here is dropped, never emitted.
SAFE_LOG_FIELDS = frozenset(
    {
        "event",
        "severity",
        "message",
        "service",
        "revision",
        "logger",
        "code_location",
        "http_request_id",
        "duration_ms",
        "outcome",
        "error_code",
        "workflow_id",
        "suggestion_request_id",
        "suggestion_id",
        "task_id",
        "operation",
        "attempt_id",
        "model",
        "trace_id",
        "span_id",
        "expired",
        "selected",
        "loaded",
        "pruned",
        "queue_wait_ms",
        "status_code",
        "method",
        "route",
        "logging.googleapis.com/trace",
    }
)

# Fixed messages per event: messages are code constants, never user content.
EVENT_MESSAGES = {
    "profile_name_unavailable": "Encrypted profile name unavailable.",
    "http_request": "HTTP request completed.",
    "unexpected_fault": "Unexpected fault reported.",
    "third_party_log": "Third-party log record redacted.",
    "direct_log": "Direct log record redacted.",
    "suggestion_task": "Suggestion task processed.",
    "suggestion_reserved": "Suggestion reservation committed.",
    "suggestion_enqueue": "Suggestion enqueue attempted.",
    "suggestion_delivery": "Suggestion delivery acknowledged.",
    "suggestion_finished": "Suggestion reached a terminal outcome.",
    "maintenance_finished": "Suggestion maintenance sweep finished.",
    "suggestion_expire": "Suggestion expiry sweep finished.",
    "provider_call": "Provider transport attempt finished.",
    "ai_output_rejected": "Provider output rejected by validation.",
    "agent_finished": "Agent run finished.",
    "analytics_export": "Analytics export finished.",
}

_MAX_STRING_FIELD_LENGTH = 256

_request_id_state: ContextVar[str | None] = ContextVar(
    "phase21_http_request_id", default=None
)


def get_request_id() -> str | None:
    return _request_id_state.get()


def get_service_revision() -> str:
    return (
        os.environ.get("K_REVISION")
        or os.environ.get("APP_REVISION")
        or "local"
    )


def google_trace_name(trace_id_hex: str) -> str | None:
    """Cloud Run log-correlation field; only when the project is known."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
        "GCP_PROJECT"
    )
    if not project or trace_id_hex == "0" * 32:
        return None
    return f"projects/{project}/traces/{trace_id_hex}"


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_STRING_FIELD_LENGTH:
        return value[:_MAX_STRING_FIELD_LENGTH]
    return value


def _normalize_code(value: Any) -> str:
    code = value.value if hasattr(value, "value") else value
    return str(code)[:64]


def _context_fields() -> dict[str, Any]:
    fields: dict[str, Any] = {}
    request_id = _request_id_state.get()
    if request_id is not None:
        fields["http_request_id"] = request_id
    trace_id, span_id = current_span_ids()
    fields["trace_id"] = trace_id
    fields["span_id"] = span_id
    trace_name = google_trace_name(trace_id)
    if trace_name is not None:
        fields["logging.googleapis.com/trace"] = trace_name
    return fields


class Phase21JSONFormatter(logging.Formatter):
    """Serialize records to one JSON object; never leaks raw exceptions."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def formatException(self, exc_info: Any) -> str:
        return ""

    def format(self, record: logging.LogRecord) -> str:
        document: dict[str, Any] = {
            "severity": record.levelname,
            "service": self.service,
            "revision": get_service_revision(),
        }
        if record.name == APP_LOGGER_NAME or record.name.startswith("app."):
            document.update(self._format_app_record(record))
        else:
            document.update(self._format_third_party_record(record))
        return json.dumps(document, separators=(",", ":"), default=str)

    def _format_app_record(self, record: logging.LogRecord) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        for key, value in vars(record).items():
            if key in SAFE_LOG_FIELDS and key != "message":
                fields[key] = _truncate(value)
        event_name = str(fields.get("event", "log"))
        fields["event"] = event_name
        if "event" in vars(record):
            # Helper path: fixed message per event, never caller content.
            fields["message"] = EVENT_MESSAGES.get(event_name, event_name)
        else:
            # Direct logger calls lack a validated event, so the message is
            # caller-controlled and never serialized. Allowlisted extra
            # fields still travel; new code must use log_event instead.
            fields["message"] = EVENT_MESSAGES["direct_log"]
            fields["event"] = "direct_log"
            event_name = "direct_log"
        merged = _context_fields()
        for key, value in merged.items():
            fields.setdefault(key, value)
        ordered = {"event": fields.pop("event"), "message": fields.pop("message")}
        ordered.update(sorted(fields.items()))
        return ordered

    def _format_third_party_record(
        self, record: logging.LogRecord
    ) -> dict[str, Any]:
        # Fixed message plus logger identity and code location only. The
        # third-party message, args, and traceback are never serialized.
        fields = _context_fields()
        fields.update(
            {
                "event": "third_party_log",
                "message": EVENT_MESSAGES["third_party_log"],
                "logger": record.name[:128],
                "code_location": f"{record.module}:{record.funcName}:{record.lineno}",
            }
        )
        return fields


class StdoutProxyHandler(logging.Handler):
    """StreamHandler that resolves sys.stdout at emit time (capsys-safe)."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.setFormatter(Phase21JSONFormatter(service))
        self._service = service

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = sys.stdout
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)


def disable_uvicorn_access_logs() -> None:
    """Disable duplicate uvicorn access output in code.

    Central switch so both deployed entrypoints stay quiet even when
    Terraform overrides the container command/args. Uvicorn startup/error
    records still flow through the root formatter, which redacts them.
    """
    for name in ("uvicorn.access",):
        logger = logging.getLogger(name)
        logger.disabled = True
        logger.propagate = False
        logger.handlers = []


def route_uvicorn_through_safe_formatter() -> None:
    """Force uvicorn loggers through the root sanitizing formatter.

    Production uvicorn installs its own plain-text handlers on ``uvicorn``
    and ``uvicorn.error`` with propagation disabled, which would bypass the
    output policy. Clearing those handlers and re-enabling propagation
    routes every record through the root JSON formatter instead.
    """
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.disabled = False


def route_third_party_loggers_through_safe_formatter() -> None:
    """Route existing third-party loggers through the root formatter.

    Any library may install its own plain-text handler with
    ``propagate=False`` (uvicorn does in production), which would bypass
    the sanitizing JSON formatter on the root logger. Clear handlers and
    re-enable propagation on every existing non-application logger so
    records can only flow through the root policy. ``uvicorn.access`` is
    skipped here: duplicate access output stays disabled via
    ``disable_uvicorn_access_logs`` (called after this routing).
    """
    for name, existing in list(logging.root.manager.loggerDict.items()):
        if not isinstance(existing, logging.Logger):
            continue
        if name == APP_LOGGER_NAME or name.startswith("app."):
            continue
        if name in ("uvicorn.access",):
            continue
        existing.handlers = []
        existing.propagate = True
        existing.disabled = False


_original_call_handlers: Any = None


def _enforce_safe_handler_policy() -> None:
    """Enforce the safe logging policy for handlers installed later.

    ``configure_logging`` clears pre-existing third-party handlers, but a
    library imported or configured afterwards can still attach its own
    plain-text handler with ``propagate=False``, which would bypass the
    sanitizing root formatter. This installs (once) a
    ``logging.Logger.callHandlers`` policy\u2014a standard-library dispatch
    hook, so it covers ``addHandler``, ``dictConfig``/``fileConfig``, and
    direct ``handlers`` mutation alike\u2014under which:

    - handlers on non-root loggers that are not ``StdoutProxyHandler``
      are never invoked, so no raw record text escapes there;
    - a logger that skips such an unsafe handler still propagates to the
      root, so the record is emitted once through the safe formatter
      even when the logger sets ``propagate=False``;
    - root handlers are invoked normally, preserving operator tooling
      such as pytest's ``caplog`` capture handler;
    - ``uvicorn.access`` records stay silent (duplicate access output
      remains disabled via ``disable_uvicorn_access_logs``);
    - the stdlib ``lastResort`` raw-stderr fallback is never used, so a
      handler-less state cannot leak raw text either.
    """
    global _original_call_handlers
    if _original_call_handlers is not None:
        return
    _original_call_handlers = logging.Logger.callHandlers

    def _phase21_call_handlers(
        logger_self: logging.Logger, record: logging.LogRecord
    ) -> None:
        if record.name == "uvicorn.access" or record.name.startswith(
            "uvicorn.access."
        ):
            return
        current: logging.Logger | None = logger_self
        found = 0
        while current is not None:
            skipped_unsafe = False
            if current is logging.root:
                for handler in current.handlers:
                    found += 1
                    if record.levelno >= handler.level:
                        handler.handle(record)
            else:
                for handler in current.handlers:
                    if isinstance(handler, StdoutProxyHandler):
                        found += 1
                        if record.levelno >= handler.level:
                            handler.handle(record)
                    else:
                        skipped_unsafe = True
            if not current.propagate and not skipped_unsafe:
                current = None
            else:
                current = current.parent
        if found == 0:
            return

    logging.Logger.callHandlers = _phase21_call_handlers  # type: ignore[method-assign]


def configure_logging(service: str) -> logging.Logger:
    """Configure application JSON logging; idempotent across factories.

    Attaches a single stdout handler to the root logger (so third-party
    records cannot bypass the policy), enables INFO, disables duplicate
    uvicorn access logging, and re-enables loggers that in-process
    migration setup may have disabled. Repeated factory construction adds
    no handlers. The first-configured service name wins per process.
    """
    root = logging.getLogger()
    proxies = [
        handler for handler in root.handlers if isinstance(handler, StdoutProxyHandler)
    ]
    for duplicate in proxies[1:]:
        root.removeHandler(duplicate)
    if not proxies:
        root.addHandler(StdoutProxyHandler(service))
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    # In-process migration runs must never silence application logging:
    # re-enable every existing logger; uvicorn access output is then
    # disabled deliberately below as the single intentional exception.
    for existing in logging.root.manager.loggerDict.values():
        if isinstance(existing, logging.Logger):
            existing.disabled = False
    route_uvicorn_through_safe_formatter()
    route_third_party_loggers_through_safe_formatter()
    _enforce_safe_handler_policy()
    disable_uvicorn_access_logs()
    return logging.getLogger(APP_LOGGER_NAME)


def log_event(
    event: str,
    *,
    outcome: str | None = None,
    error_code: Any | None = None,
    **fields: Any,
) -> None:
    """Emit one structured event with only allowlisted fields.

    Unknown keyword arguments are dropped. The message is fixed per event;
    callers never pass user content.
    """
    logger = logging.getLogger(APP_LOGGER_NAME)
    record_fields: dict[str, Any] = {"event": event}
    if outcome is not None:
        record_fields["outcome"] = str(outcome)[:64]
    if error_code is not None:
        record_fields["error_code"] = _normalize_code(error_code)
    for key, value in fields.items():
        if key not in SAFE_LOG_FIELDS or key == "message":
            # "message" is reserved: the message is always fixed per event.
            continue
        if isinstance(value, (bool, int, float, str)):
            record_fields[key] = value
    logger.info("", extra=record_fields)


def log_unexpected_fault(error_code: Any, *, location: str | None = None) -> None:
    """Sanitized unexpected-fault event: fixed message, code, location.

    The exception instance itself is never attached: no raw exception text
    or traceback reaches the output. Expected provider outages remain
    categorized operational events, not faults.
    """
    fields: dict[str, Any] = {
        "event": "unexpected_fault",
        "error_code": _normalize_code(error_code),
    }
    if location is not None:
        fields["code_location"] = str(location)[:128]
    logging.getLogger(APP_LOGGER_NAME).info("", extra=fields)


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path.startswith("/"):
        return path
    return "unknown"


class RequestLoggingMiddleware:
    """Pure ASGI request logging; never consumes bodies or buffers streams."""

    def __init__(self, app: ASGIApp, *, service: str) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        token = _request_id_state.set(request_id)
        started = time.monotonic()
        logged = False

        async def send_with_completion(message: Message) -> None:
            nonlocal logged
            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
                and not logged
            ):
                logged = True
                # Log before forwarding the final chunk so the record exists
                # even if the client disconnects mid-flush.
                self._log_completed(scope, started)
            await send(message)

        async def receive_with_disconnect() -> Message:
            message = await receive()
            if message["type"] == "http.disconnect":
                scope["phase21.client_disconnected"] = True
            return message

        try:
            await self.app(scope, receive_with_disconnect, send_with_completion)
            if not logged:
                logged = True
                self._log_completed(scope, started)
        except BaseException:
            if not logged:
                logged = True
                self._log_completed(scope, started)
            raise
        finally:
            _request_id_state.reset(token)

    def _log_completed(self, scope: Scope, started: float) -> None:
        status_code = int(scope.get("phase21.response_status", 500))
        outcome = outcome_for_status(status_code)
        if scope.get("phase21.client_disconnected"):
            outcome = "interrupted"
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        # method/route template only: never the raw URL or query string.
        log_event(
            "http_request",
            outcome=outcome,
            method=str(scope.get("method", ""))[:16],
            route=_route_template(scope),
            status_code=status_code,
            duration_ms=duration_ms,
        )


__all__ = [
    "APP_LOGGER_NAME",
    "EVENT_MESSAGES",
    "SAFE_LOG_FIELDS",
    "RequestLoggingMiddleware",
    "StdoutProxyHandler",
    "configure_logging",
    "disable_uvicorn_access_logs",
    "get_request_id",
    "get_service_revision",
    "google_trace_name",
    "log_event",
    "log_unexpected_fault",
    "route_third_party_loggers_through_safe_formatter",
    "route_uvicorn_through_safe_formatter",
]
