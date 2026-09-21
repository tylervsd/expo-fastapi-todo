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
