"""Automated IVR caller settings (Task 1: settings only)."""

import os
import re
from dataclasses import dataclass, field, fields

_ERROR = "Invalid client configuration"
_E164 = re.compile(r"\+[1-9][0-9]{7,14}")


def _fail() -> None:
    raise RuntimeError(_ERROR)


def _api_key(value: object) -> str:
    if not (
        isinstance(value, str)
        and value.strip()
        and value.isascii()
        and all(33 <= ord(char) <= 126 for char in value)
    ):
        _fail()
    return value


def _connection_id(value: object) -> str:
    if not (isinstance(value, str) and value.strip() and len(value) <= 256):
        _fail()
    return value


def _number(value: object) -> str:
    if not (isinstance(value, str) and _E164.fullmatch(value)):
        _fail()
    return value


def _synthetic_id(value: object) -> str:
    if not (isinstance(value, str) and re.fullmatch(r"[0-9]{9}", value)):
        _fail()
    return value


def _checked_int(value: object, low: int, high: int) -> int:
    if not (type(value) is int and low <= value <= high):
        _fail()
    return value


@dataclass(frozen=True, repr=False)
class ClientSettings:
    api_key: str = field(metadata={"env": "TELNYX_API_KEY"})
    connection_id: str = field(metadata={"env": "IVR_CLIENT_CONNECTION_ID"})
    from_number: str = field(metadata={"env": "IVR_CLIENT_FROM_NUMBER"})
    to_number: str = field(metadata={"env": "IVR_CLIENT_TO_NUMBER"})
    synthetic_id: str = field(
        default="000123456", metadata={"env": "IVR_CLIENT_SYNTHETIC_ID"}
    )
    stage_timeout_seconds: int = field(
        default=30, metadata={"env": "IVR_CLIENT_STAGE_TIMEOUT_SECONDS"}
    )
    call_timeout_seconds: int = field(
        default=180, metadata={"env": "IVR_CLIENT_CALL_TIMEOUT_SECONDS"}
    )
    dtmf_duration_ms: int = field(
        default=250, metadata={"env": "IVR_CLIENT_DTMF_DURATION_MS"}
    )
    dtmf_pause_units: int = field(
        default=0, metadata={"env": "IVR_CLIENT_DTMF_PAUSE_UNITS"}
    )

    transcription_track: str = field(
        default="outbound", metadata={"env": "IVR_CLIENT_TRANSCRIPTION_TRACK"}
    )

    def __post_init__(self):
        try:
            object.__setattr__(self, "api_key", _api_key(self.api_key))
            object.__setattr__(
                self, "connection_id", _connection_id(self.connection_id)
            )
            object.__setattr__(self, "from_number", _number(self.from_number))
            object.__setattr__(self, "to_number", _number(self.to_number))
            if self.transcription_track not in ("inbound", "outbound"):
                raise ValueError
            if self.from_number == self.to_number:
                raise ValueError
            object.__setattr__(self, "synthetic_id", _synthetic_id(self.synthetic_id))
            object.__setattr__(
                self,
                "stage_timeout_seconds",
                _checked_int(self.stage_timeout_seconds, 10, 60),
            )
            object.__setattr__(
                self,
                "call_timeout_seconds",
                _checked_int(self.call_timeout_seconds, 60, 600),
            )
            if self.call_timeout_seconds < self.stage_timeout_seconds:
                raise ValueError
            object.__setattr__(
                self, "dtmf_duration_ms", _checked_int(self.dtmf_duration_ms, 100, 500)
            )
            object.__setattr__(
                self, "dtmf_pause_units", _checked_int(self.dtmf_pause_units, 0, 2)
            )
        except ValueError, TypeError:
            raise RuntimeError(_ERROR) from None


_INT_FIELDS = frozenset(
    {
        "stage_timeout_seconds",
        "call_timeout_seconds",
        "dtmf_duration_ms",
        "dtmf_pause_units",
    }
)


def load_client_settings() -> ClientSettings:
    """Build settings from the explicit IVR_CLIENT_*/TELNYX_* mapping only."""
    try:
        values: dict = {}
        for item in fields(ClientSettings):
            name = item.metadata["env"]
            if name in os.environ:
                raw = os.environ[name]
                if item.name in _INT_FIELDS:
                    if not re.fullmatch(r"[0-9]+", raw):
                        raise ValueError
                    values[item.name] = int(raw)
                else:
                    values[item.name] = raw
        return ClientSettings(**values)
    except TypeError, ValueError:
        raise RuntimeError(_ERROR) from None


"""Prompt-driven navigation over final speech segments (Task 3: sync flow)."""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from speech import recognize
from telnyx_commands import CommandError, DialIdentity, make_command, make_dial

_CLEANUP_SECONDS = 15
_MAX_SEGMENTS = 64
_MAX_CHARS = 4096
_MAX_EVENT_IDS = 4096

_NEXT = {
    "welcome": "challenge",
    "challenge": "menu",
    "menu": "identifier",
    "identifier": "confirmation",
    "confirmation": "result",
}


class ClientFlow:
    """Synchronous stage machine; no I/O, no stdout, no fixture imports."""

    def __init__(self, settings, identity, *, started_at, now):
        self.settings = settings
        self.identity = identity
        self.started_at = started_at
        self.stage = "dialing"
        self.stage_started_at = now
        self.pending = None
        self.checkpoint_reached = False
        self.outcome = None
        self.exit_code = None
        self.answered = False
        self._segments = []
        self._chars = 0
        self._seen = set()
        self._last_time = None
        self._consumed_at = None
        self._hangup_started_at = None

    def _hangup(self, reason, *, now):
        self.outcome = self.outcome or reason
        command = make_command(self.identity.call_control_id, "hangup", {})
        self.pending = command
        self.stage = "hanging_up"
        self._hangup_started_at = now
        self._segments = []
        self._chars = 0
        return command

    def _fail(self, reason, *, now):
        if self.stage == "ended":
            return None
        return self._hangup(reason, now=now)

    def _expired(self, now):
        if now - self.started_at >= self.settings.call_timeout_seconds:
            return "overall_timeout"
        if now - self.stage_started_at >= self.settings.stage_timeout_seconds:
            return "stage_timeout"
        return None

    @staticmethod
    def _occurred(data):
        try:
            occurred = datetime.fromisoformat(data["occurred_at"])
        except KeyError, TypeError, ValueError:
            return None
        if occurred.tzinfo is None:
            return None
        return occurred

    def _reserve_dtmf(self, logical, *, now, occurred):
        wire = ("w" * self.settings.dtmf_pause_units).join(logical)
        command = make_command(
            self.identity.call_control_id,
            "send_dtmf",
            {
                "digits": wire,
                "duration_millis": self.settings.dtmf_duration_ms,
            },
        )
        self.pending = command
        self._segments = []
        self._chars = 0
        self._last_time = None
        self._consumed_at = occurred
        self.stage = _NEXT[self.stage]
        self.stage_started_at = now
        return command

    def _evaluate(self, *, now, occurred):
        joined = " ".join(self._segments)
        status, value = recognize(self.stage, joined, self.settings.synthetic_id)
        logger.info(json.dumps({"stage": self.stage, "parser": status}))
        if status == "pending":
            return None
        if status == "invalid":
            return self._fail(value, now=now)
        if self.stage == "result":
            self.checkpoint_reached = True
            self._segments = []
            self._chars = 0
            self._last_time = None
            self._consumed_at = occurred
            return None
        return self._reserve_dtmf(value, now=now, occurred=occurred)

    def _on_transcript(self, data, *, now):
        if self.stage == "result" and self.checkpoint_reached:
            return None
        try:
            payload = data["payload"]
            speech = payload["transcription_data"]
            transcript = speech["transcript"]
            is_final = speech["is_final"]
        except KeyError, TypeError:
            return None
        if type(is_final) is not bool or not is_final:
            return None
        if (
            not isinstance(transcript, str)
            or not transcript
            or len(transcript) > _MAX_CHARS
        ):
            return None
        occurred = self._occurred(data)
        if occurred is None:
            return None
        if self._last_time is not None and occurred < self._last_time:
            return self._fail("transcript_order", now=now)
        if self._consumed_at is not None and occurred < self._consumed_at:
            return None
        if (
            len(self._segments) >= _MAX_SEGMENTS
            or self._chars + len(transcript) > _MAX_CHARS
        ):
            return self._fail("buffer_overflow", now=now)
        self._segments.append(transcript)
        self._chars += len(transcript)
        self._last_time = occurred
        if self.stage == "dialing":
            return None
        return self._evaluate(now=now, occurred=occurred)

    def handle(self, data, *, now):
        if self.stage == "ended":
            return None
        if not isinstance(data, dict):
            return None
        if self.stage == "hanging_up":
            if data.get("event_type") != "call.hangup":
                return None
        else:
            expired = self._expired(now)
            if expired is not None:
                return self._fail(expired, now=now)
        event_id = data.get("id")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
            return None
        if event_id in self._seen:
            return None
        if len(self._seen) >= _MAX_EVENT_IDS:
            return self._fail("event_overflow", now=now)
        event_type = data.get("event_type")
        if not isinstance(event_type, str):
            return None
        self._seen.add(event_id)
        if event_type == "call.answered":
            if self.stage != "dialing" or self.answered:
                return None
            self.answered = True
            self.stage = "welcome"
            self.stage_started_at = now
            if self._segments:
                return self._evaluate(now=now, occurred=self._last_time)
            return None
        if event_type == "call.transcription":
            return self._on_transcript(data, now=now)
        if event_type == "call.hangup":
            self._segments = []
            self._chars = 0
            self.pending = None
            self.stage = "ended"
            if self.checkpoint_reached and self.outcome is None:
                self.outcome = "completed"
                self.exit_code = 0
            else:
                self.outcome = self.outcome or "early_hangup"
                self.exit_code = 1
            return None
        return None

    def expire(self, *, now):
        if self.stage == "ended":
            return None
        if self.stage == "hanging_up":
            if (
                self._hangup_started_at is not None
                and now - self._hangup_started_at >= _CLEANUP_SECONDS
            ):
                self.outcome = "hangup_unconfirmed"
                self.exit_code = 1
                self.stage = "ended"
                self.pending = None
            return None
        expired = self._expired(now)
        if expired is not None:
            return self._fail(expired, now=now)
        return None

    def command_failed(self, command_id, *, now):
        if self.stage == "ended":
            return None
        pending = self.pending
        if pending is None or pending.command_id != command_id:
            return None
        if pending.action == "hangup":
            self.outcome = "hangup_unconfirmed"
            self.exit_code = 1
            self.stage = "ended"
            self.pending = None
            return None
        return self._fail("provider_failure", now=now)

    def stop(self, reason, *, now):
        if self.stage == "ended" or self.stage == "hanging_up":
            return None
        return self._hangup(reason, now=now)


"""Runtime ownership: one outbound call, early callbacks, bounded cleanup."""

logger = logging.getLogger("ivr.client")
logger.setLevel(logging.INFO)
logger.parent = logging.getLogger("uvicorn.error")

_KNOWN_EVENTS = frozenset(
    {"call.initiated", "call.answered", "call.transcription", "call.hangup"}
)
_MAX_BUFFER_EVENTS = 32
_MAX_BUFFER_BYTES = 65536
_CLEANUP_BUDGET = 15


def _dial_fields(settings):
    return {
        "connection_id": settings.connection_id,
        "from": settings.from_number,
        "to": settings.to_number,
        "timeout_secs": 30,
        "time_limit_secs": settings.call_timeout_seconds,
        "transcription": True,
        "transcription_config": {
            "transcription_engine": "Google",
            "transcription_engine_config": {
                "transcription_engine": "Google",
                "language": "en",
                "interim_results": True,
            },
            "transcription_tracks": settings.transcription_track,
        },
    }


class Caller:
    """Owns one outbound run: dial reservation, identity binding, cleanup."""

    def __init__(self, settings, dial, send, *, clock=time.monotonic):
        self.settings = settings
        self.dial = dial
        self.send = send
        self.clock = clock
        self.done = asyncio.Event()
        self.exit_code = None
        self.outcome = None
        self.request = None
        self.identity = None
        self.flow = None
        self.tasks = {}
        # ponytail: one call per process and a short-held lock; durable per-call workers if scale is needed.
        self.lock = asyncio.Lock()
        self.run_id = str(uuid4())
        self._started = False
        self._started_at = 0.0
        self._wall_started = None
        self._run_token = None
        self._dial_task = None
        self._dial_uncertain = False
        self._closing = False
        self._seen = set()
        self._buffer = []
        self._buffer_bytes = 0
        self._finishing = False
        self._cleared = False
        self._pending_failure = None
        self._cleanup_deadline = None

    def _log(self, reason):
        flow = self.flow
        logger.info(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "reason": reason,
                    "stage": flow.stage if flow else "idle",
                    "elapsed": round(self.clock() - self._started_at, 3)
                    if self._started
                    else 0,
                }
            )
        )

    async def start(self):
        if self._started:
            raise RuntimeError("already_started")
        self._started = True
        self._started_at = self.clock()
        self._wall_started = datetime.now(UTC)
        self.request = make_dial(_dial_fields(self.settings))
        self._run_token = self.request.client_state
        self._log("dial_reserved")
        self._dial_task = asyncio.create_task(self._run_dial())

    async def _run_dial(self):
        try:
            identity = await self.dial(self.request)
        except asyncio.CancelledError:
            raise
        except CommandError as error:
            async with self.lock:
                self._on_dial_error(error.reason)
        except Exception:  # noqa: BLE001 — contain task errors; tokens stay out of logs
            async with self.lock:
                self._on_dial_error("internal_error")
        else:
            async with self.lock:
                self._on_dial_identity(identity)

    def _on_dial_identity(self, identity):
        if self.done.is_set() or self._finishing:
            return
        try:
            call, leg = identity.call_control_id, identity.call_leg_id
            if not (
                isinstance(call, str)
                and isinstance(leg, str)
                and 1 <= len(call) <= 1024
                and 1 <= len(leg) <= 256
            ):
                raise ValueError
        except AttributeError, ValueError:
            self._on_dial_error("invalid_response")
            return
        if self.flow is not None:
            if (
                call != self.identity.call_control_id
                or leg != self.identity.call_leg_id
            ):
                self.outcome = "identity_conflict"
                hangup = self.flow.stop("identity_conflict", now=self.clock())
                if hangup is not None:
                    self._schedule(hangup)
                elif self.flow.stage == "ended":
                    self._finalize()
                else:
                    self._log("identity_conflict")
            return
        self._bind(identity)
        if self._dial_uncertain or self._cleanup_deadline is not None:
            hangup = self.flow.stop(
                self._pending_failure or "dial_uncertain", now=self.clock()
            )
            if hangup is not None:
                self._schedule(hangup)

    def _on_dial_error(self, reason):
        if self.done.is_set() or self._finishing:
            return
        if self.flow is not None:
            self._log("dial_error_retained")
            return
        if reason == "rejected":
            self._finish("dial_rejected", 1)
        else:
            # Uncertain dial: keep the run open for identifying callbacks until
            # the cleanup budget expires; a late bind still hangs up (see accept).
            self._dial_uncertain = True
            if self._cleanup_deadline is None:
                self._cleanup_deadline = self.clock() + _CLEANUP_BUDGET
            self._log("dial_uncertain")

    def _bind(self, identity):
        self.identity = identity
        self.flow = ClientFlow(
            self.settings, identity, started_at=self._started_at, now=self.clock()
        )
        self._log("identity_bound")
        self._replay()

    def _replay(self):
        matching = [
            data
            for data in self._buffer
            if data["payload"]["call_control_id"] == self.identity.call_control_id
            and data["payload"]["call_leg_id"] == self.identity.call_leg_id
        ]
        self._buffer = []
        self._buffer_bytes = 0
        hangups = [data for data in matching if data["event_type"] == "call.hangup"]
        rest = [data for data in matching if data["event_type"] != "call.hangup"]
        for data in hangups + rest:
            command = self.flow.handle(data, now=self.clock())
            if command is not None:
                self._schedule(command)
            if self.flow.stage == "ended":
                break
        if self.flow.stage == "ended":
            self._finalize()

    @staticmethod
    def _validate(data):
        if not isinstance(data, dict):
            raise ValueError("Invalid call event")  # noqa: TRY004 — webhook maps ValueError to 400
        event_type = data.get("event_type")
        if not isinstance(event_type, str):
            raise ValueError("Invalid call event")  # noqa: TRY004 — webhook maps ValueError to 400
        if event_type not in _KNOWN_EVENTS:
            return None
        event_id = data.get("id")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
            raise ValueError("Invalid call event")
        try:
            occurred = datetime.fromisoformat(data["occurred_at"])
        except KeyError, TypeError, ValueError:
            raise ValueError("Invalid call event") from None
        if occurred.tzinfo is None:
            raise ValueError("Invalid call event")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Invalid call event")  # noqa: TRY004 — webhook maps ValueError to 400
        for name, limit in (
            ("call_control_id", 1024),
            ("call_leg_id", 256),
            ("connection_id", 256),
        ):
            value = payload.get(name)
            if not isinstance(value, str) or not 1 <= len(value) <= limit:
                raise ValueError("Invalid call event")
        if event_type == "call.transcription":
            # Shape gate before any lock/dedup mutation: malformed speech is a
            # 400 via ValueError, never buffered or deduped. Partials (False)
            # stay valid; only non-bool flags fail.
            speech = payload.get("transcription_data")
            if not isinstance(speech, dict):
                raise ValueError("Invalid call event")
            if (
                not isinstance(speech.get("transcript"), str)
                or len(speech["transcript"]) > _MAX_CHARS
            ):
                raise ValueError("Invalid call event")
            if type(speech.get("is_final")) is not bool:
                raise ValueError("Invalid call event")
        if event_type == "call.initiated" and not isinstance(
            payload.get("direction"), str
        ):
            raise ValueError("Invalid call event")
        return occurred

    def _correlates(self, data, occurred):
        payload = data["payload"]
        if payload.get("direction") != "outgoing":
            return False
        if payload.get("client_state") != self._run_token:
            return False
        # Spec-literal "from"/"to" keys only; if live Telnyx payloads use
        # different names, Task 5/6 acceptance must confirm and adjust openly.
        if payload.get("from") != self.settings.from_number:
            return False
        if payload.get("to") != self.settings.to_number:
            return False
        if occurred < self._wall_started:
            return False
        return occurred <= datetime.now(UTC) + timedelta(seconds=300)

    async def accept(self, data):
        if not self._started:
            return
        occurred = self._validate(data)
        if occurred is None:
            return
        if data["event_type"] == "call.transcription":
            payload = data["payload"]
            logger.info(
                json.dumps(
                    {
                        "stage": self.flow.stage if self.flow else "idle",
                        "final": payload["transcription_data"]["is_final"],
                        "connection_match": payload["connection_id"]
                        == self.settings.connection_id,
                        "call_match": bool(
                            self.identity
                            and payload["call_control_id"]
                            == self.identity.call_control_id
                        ),
                        "leg_match": bool(
                            self.identity
                            and payload["call_leg_id"] == self.identity.call_leg_id
                        ),
                    }
                )
            )
        if data["payload"]["connection_id"] != self.settings.connection_id:
            return
        async with self.lock:
            if self.done.is_set() or self._finishing:
                return
            now = self.clock()
            if self.flow is None:
                if self._cleanup_expired(now):
                    self._finish(
                        self._pending_failure
                        or (
                            "dial_uncertain"
                            if self._dial_uncertain
                            else "overall_timeout"
                        ),
                        1,
                    )
                    return
                if self._cleanup_deadline is None:
                    if now - self._started_at >= self.settings.call_timeout_seconds:
                        self._enter_uncertain(
                            "dial_uncertain"
                            if self._dial_uncertain
                            else "overall_timeout"
                        )
                        return
                    if now - self._started_at >= self.settings.stage_timeout_seconds:
                        self._enter_uncertain(
                            "dial_uncertain"
                            if self._dial_uncertain
                            else "stage_timeout"
                        )
                        return
                self._accept_preface(data, occurred)
            else:
                self._accept_bound(data, now=now)

    def _enter_uncertain(self, reason):
        """Hold for late identity instead of finishing: first failure wins."""
        if self._pending_failure is None:
            self._pending_failure = reason
        self._dial_uncertain = True
        if self._cleanup_deadline is None:
            self._cleanup_deadline = self.clock() + _CLEANUP_BUDGET
        self._log(reason)

    def _cleanup_expired(self, now):
        return self._cleanup_deadline is not None and now >= self._cleanup_deadline

    def _accept_preface(self, data, occurred):
        event_id = data["id"]
        if event_id in self._seen:
            return
        if data["event_type"] == "call.initiated" and self._correlates(data, occurred):
            if len(self._seen) < 4096:
                self._seen.add(event_id)
            payload = data["payload"]
            self._bind(
                DialIdentity(
                    call_control_id=payload["call_control_id"],
                    call_leg_id=payload["call_leg_id"],
                )
            )
            if self._dial_uncertain:
                hangup = self.flow.stop(
                    self._pending_failure or "dial_uncertain", now=self.clock()
                )
                if hangup is not None:
                    self._schedule(hangup)
            return
        size = len(json.dumps(data).encode())
        if len(self._buffer) >= _MAX_BUFFER_EVENTS:
            # Retain the buffer for a late bind; drop only the newest event.
            self._enter_uncertain("buffer_overflow")
            return
        if self._buffer_bytes + size > _MAX_BUFFER_BYTES:
            self._enter_uncertain("buffer_overflow")
            return
        if len(self._seen) >= 4096:
            self._enter_uncertain("event_overflow")
            return
        self._seen.add(event_id)
        self._buffer.append(data)
        self._buffer_bytes += size

    def _accept_bound(self, data, *, now):
        payload = data["payload"]
        if self.identity is None:
            return
        if (
            payload["call_control_id"] != self.identity.call_control_id
            or payload["call_leg_id"] != self.identity.call_leg_id
        ):
            return
        command = self.flow.handle(data, now=now)
        if command is not None:
            self._schedule(command)
        if self.flow.stage == "ended":
            self._finalize()

    def _schedule(self, command):
        task = asyncio.create_task(self._run_command(command))
        self.tasks[task] = command
        task.add_done_callback(lambda finished: self.tasks.pop(finished, None))

    async def _run_command(self, command):
        try:
            await self.send(command)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 — obsolete completions stay silent
            async with self.lock:
                if self.done.is_set() or self._finishing:
                    return
                if self.flow is None or self.flow.pending is not command:
                    return
                reason = (
                    error.reason
                    if isinstance(error, CommandError)
                    else "internal_error"
                )
                self._log(reason)
                nxt = self.flow.command_failed(command.command_id, now=self.clock())
                if nxt is not None:
                    self._schedule(nxt)
                if self.flow.stage == "ended":
                    self._finalize()
        else:
            async with self.lock:
                if not self.done.is_set() and not self._finishing:
                    self._log("command_accepted")

    async def tick(self):
        async with self.lock:
            if not self._started or self.done.is_set() or self._finishing:
                return
            now = self.clock()
            if self.flow is None:
                if self._cleanup_expired(now):
                    self._finish(
                        self._pending_failure
                        or (
                            "dial_uncertain"
                            if self._dial_uncertain
                            else "overall_timeout"
                        ),
                        1,
                    )
                elif self._cleanup_deadline is None:
                    if now - self._started_at >= self.settings.call_timeout_seconds:
                        self._enter_uncertain(
                            "dial_uncertain"
                            if self._dial_uncertain
                            else "overall_timeout"
                        )
                    elif now - self._started_at >= self.settings.stage_timeout_seconds:
                        self._enter_uncertain(
                            "dial_uncertain"
                            if self._dial_uncertain
                            else "stage_timeout"
                        )
                return
            command = self.flow.expire(now=now)
            if command is not None:
                self._schedule(command)
            if self.flow.stage == "ended":
                self._finalize()

    def _finish(self, outcome, exit_code):
        if self.done.is_set() or self._finishing:
            return
        self._finishing = True
        self.outcome = outcome
        self.exit_code = exit_code
        self._log(outcome)
        current = asyncio.current_task()
        dial = self._dial_task
        self._dial_task = None
        pending = [task for task in list(self.tasks) if task is not current]
        if dial is not None and dial is not current:
            dial.cancel()
            pending.append(dial)
        for task in pending:
            task.cancel()
        self._clear_sensitive()
        if pending:
            asyncio.create_task(self._join(pending))
        else:
            self.done.set()

    def _finalize(self):
        if self.done.is_set() or self._finishing:
            return
        flow = self.flow
        if flow is None or flow.stage != "ended":
            return
        self._finishing = True
        self.outcome = flow.outcome or "unknown"
        self.exit_code = flow.exit_code if flow.exit_code is not None else 1
        self._log(self.outcome)
        current = asyncio.current_task()
        dial = self._dial_task
        self._dial_task = None
        pending = [task for task in list(self.tasks) if task is not current]
        if dial is not None and dial is not current:
            dial.cancel()
            pending.append(dial)
        for task in pending:
            task.cancel()
        self._clear_sensitive()
        if pending:
            asyncio.create_task(self._join(pending))
        else:
            self.done.set()

    async def _join(self, pending):
        await asyncio.gather(*pending, return_exceptions=True)
        self.done.set()

    def _clear_sensitive(self):
        """Drop transcripts, IDs, tokens and bodies; keep outcome/exit/stage."""
        if self._cleared:
            return
        self._cleared = True
        self._seen.clear()
        self._buffer = []
        self._buffer_bytes = 0
        self.request = None
        self.identity = None
        self._run_token = None
        flow = self.flow
        if flow is not None:
            flow._seen.clear()
            flow._segments = []
            flow._chars = 0
            flow._last_time = None
            flow._consumed_at = None
            flow.pending = None
            flow.identity = None

    async def close(self):
        dial_task = None
        async with self.lock:
            if self._started and not self.done.is_set() and not self._finishing:
                self._closing = True
                if self.flow is not None:
                    if self.flow.stage != "ended":
                        hangup = self.flow.stop(
                            self.flow.outcome or "shutdown", now=self.clock()
                        )
                        if hangup is not None:
                            self._schedule(hangup)
                else:
                    dial_task = self._dial_task
                    self._dial_task = None
                    self._dial_uncertain = True
        if dial_task is not None:
            dial_task.cancel()
            await asyncio.gather(dial_task, return_exceptions=True)
        # Dual budget: the injected clock bounds cleanup, and the
        # 1500-iteration cap ends the wait on wall time if the clock stalls.
        deadline = self.clock() + _CLEANUP_BUDGET
        for _ in range(1500):
            if self.done.is_set() or self.clock() >= deadline:
                break
            await asyncio.sleep(0.01)
        async with self.lock:
            if self._started and not self.done.is_set() and not self._finishing:
                if self.flow is not None and self.flow.stage != "ended":
                    self.flow.outcome = "hangup_unconfirmed"
                    self.flow.exit_code = 1
                    self.flow.stage = "ended"
                    self.flow.pending = None
                    self._finalize()
                elif self.flow is not None:
                    self._finalize()
                else:
                    self._finish("hangup_unconfirmed", 1)
        await self._settle()

    async def _settle(self):
        """Drain canceled tasks and clear sensitive state; idempotent."""
        if not self._started:
            return
        for _ in range(1500):
            if self.done.is_set():
                break
            await asyncio.sleep(0)
        pending = list(self.tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with self.lock:
            self._clear_sensitive()
