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

    def __post_init__(self):
        try:
            object.__setattr__(self, "api_key", _api_key(self.api_key))
            object.__setattr__(
                self, "connection_id", _connection_id(self.connection_id)
            )
            object.__setattr__(self, "from_number", _number(self.from_number))
            object.__setattr__(self, "to_number", _number(self.to_number))
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

from datetime import datetime

from speech import recognize
from telnyx_commands import make_command

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
