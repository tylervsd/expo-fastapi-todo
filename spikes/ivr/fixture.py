"""Single-call, in-memory test IVR. No outbound dialing."""

import asyncio
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from telnyx_commands import CommandError, make_command

DIGIT_WORDS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
]
SMALL = DIGIT_WORDS + [
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = [
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]


@dataclass(frozen=True, repr=False)
class Settings:
    api_key: str
    connection_id: str
    synthetic_id: str = "000123456"
    result_amount: str = "1425.30"
    gather_timeout_ms: int = 20000
    inter_digit_timeout_ms: int = 5000
    max_attempts: int = 2
    speech_grace_seconds: int = 30
    call_timeout_seconds: int = 300
    voice: str = "female"
    challenge_override: str = ""
    scenario: str = "normal"

    def __post_init__(self):
        try:
            if not (isinstance(self.api_key, str) and self.api_key.strip()):
                raise ValueError()
            if not (
                self.api_key.isascii()
                and all(33 <= ord(c) <= 126 for c in self.api_key)
            ):
                raise ValueError()
            if not (isinstance(self.connection_id, str) and self.connection_id.strip()):
                raise ValueError()
            if not len(self.connection_id) <= 256:
                raise ValueError()
            if not re.fullmatch("[0-9]{9}", self.synthetic_id):
                raise ValueError()
            if not re.fullmatch("(?:0|[1-9][0-9]{0,3})\\.[0-9]{2}", self.result_amount):
                raise ValueError()
            if not (
                not self.challenge_override
                or re.fullmatch("[0-9]{4}", self.challenge_override)
            ):
                raise ValueError()
            if self.scenario not in (
                "normal",
                "leading_zero",
                "rejected_id",
                "silent_stage",
                "unsupported_result",
                "early_hangup",
            ):
                raise ValueError()
            if self.scenario == "leading_zero" and self.challenge_override not in (
                "",
                "0742",
            ):
                raise ValueError()
            if not self.voice in ("female", "male"):
                raise ValueError()
            for value, low, high in (
                (self.gather_timeout_ms, 1000, 60000),
                (self.inter_digit_timeout_ms, 1000, self.gather_timeout_ms),
                (self.max_attempts, 1, 3),
                (self.speech_grace_seconds, 10, 60),
                (self.call_timeout_seconds, 60, 600),
            ):
                if not (type(value) is int and low <= value <= high):
                    raise ValueError()
        except ValueError, TypeError:
            raise RuntimeError("Invalid fixture configuration") from None


def load_settings() -> Settings:
    try:
        values = {}
        for field in fields(Settings):
            name = (
                "TELNYX_API_KEY"
                if field.name == "api_key"
                else "IVR_" + field.name.upper()
            )
            if name in os.environ:
                value = os.environ[name]
                values[field.name] = int(value) if field.type is int else value
        return Settings(**values)
    except TypeError, ValueError:
        raise RuntimeError("Invalid fixture configuration") from None


def new_challenge() -> str:
    return f"{secrets.randbelow(10000):04d}"


def digit_words(value: str) -> str:
    return " ".join(DIGIT_WORDS[ord(char) - ord("0")] for char in value)


def integer_words(value: int) -> str:
    if value < 20:
        return SMALL[value]
    if value < 100:
        tens, rest = divmod(value, 10)
        return TENS[tens] + ("-" + SMALL[rest] if rest else "")
    divisor, label = (100, "hundred") if value < 1000 else (1000, "thousand")
    head, rest = divmod(value, divisor)
    return (
        integer_words(head) + " " + label + (" " + integer_words(rest) if rest else "")
    )


def result_prompt(amount: str) -> str:
    dollars, cents = divmod(int(Decimal(amount) * 100), 100)
    return f"Your requested value is {integer_words(dollars)} {('dollar' if dollars == 1 else 'dollars')} and {integer_words(cents)} {('cent' if cents == 1 else 'cents')}."


class Flow:
    """One call's transitions; commands are reserved before any network I/O."""

    def __init__(self, settings, call_control_id, call_leg_id, *, now, challenge=None):
        self.settings = settings
        self.call_control_id = call_control_id
        self.call_leg_id = call_leg_id
        self.challenge = (
            challenge
            if challenge is not None
            else (
                "0742"
                if settings.scenario == "leading_zero"
                else settings.challenge_override or new_challenge()
            )
        )
        if not re.fullmatch(r"[0-9]{4}", self.challenge):
            raise ValueError("Invalid challenge")
        self.started_at = now
        self.call_deadline = now + settings.call_timeout_seconds
        self.attempt = 1
        self.outcome = None
        self.answered = False
        self._reserve("answering", "answer", {}, now, 20)

    def _reserve(self, stage, action, fields, now, duration):
        self.stage = stage
        self.deadline = now + duration
        self.pending = make_command(self.call_control_id, action, fields)
        return self.pending

    def _speech_fields(self, prompt):
        return {
            "payload": prompt,
            "voice": self.settings.voice,
            "payload_type": "text",
            "service_level": "basic",
            "language": "en-US",
        }

    def _gather(self, stage, now, *, retry=False):
        self.attempt = self.attempt + 1 if retry else 1
        prompts = {
            "welcome": "Welcome to the test IVR. Press 1 to continue.",
            "challenge": f"Your verification code is {digit_words(self.challenge)}. Enter the code followed by pound.",
            "menu": "Press 1 for personal. Press 2 for business.",
            "identifier": "Enter your nine-digit personal ID followed by pound.",
            "confirmation": f"You entered {digit_words(self.settings.synthetic_id)}. Press 1 if correct.",
        }
        prompt = prompts[stage]
        if retry:
            prompt = "That entry was not accepted. Please try again. " + prompt
        length = {"challenge": 5, "identifier": 10}.get(stage, 1)
        fields = self._speech_fields(prompt) | {
            "minimum_digits": length,
            "maximum_digits": length,
            "valid_digits": "0123456789#" if length > 1 else "0123456789*#",
            "terminating_digit": "",
            "maximum_tries": 1,
            "timeout_millis": self.settings.gather_timeout_ms,
            "inter_digit_timeout_millis": self.settings.inter_digit_timeout_ms,
        }
        duration = (
            self.settings.gather_timeout_ms / 1000 + self.settings.speech_grace_seconds
        )
        return self._reserve(stage, "gather_using_speak", fields, now, duration)

    def fail(self, reason, *, now, prompt="The test service is unavailable. Goodbye."):
        if self.stage in ("ended", "hanging_up"):
            return None
        self.outcome = reason
        if not self.answered or self.stage == "failure":
            return self.hangup(now=now)
        return self._reserve(
            "failure",
            "speak",
            self._speech_fields(prompt),
            now,
            self.settings.speech_grace_seconds,
        )

    def hangup(self, *, now):
        if self.stage in ("hanging_up", "ended"):
            return None
        return self._reserve("hanging_up", "hangup", {}, now, 15)

    def end(self, reason):
        self.outcome = reason
        self.stage = "ended"
        self.pending = None
        self.challenge = ""
        self.settings = None

    def handle(self, event_type, payload, *, now):
        if self.stage == "ended":
            return None
        if event_type == "call.hangup":
            self.end(self.outcome or "remote_hangup")
            return None
        if self.pending is None:
            return self.expire(now=now)
        if payload.get("client_state") != self.pending.client_state:
            return None
        status = payload.get("status")
        if (
            event_type in ("call.gather.ended", "call.speak.ended")
            and status == "call_hangup"
        ):
            self.end(self.outcome or "remote_hangup")
            return None
        expired = self.expire(now=now)
        if expired is not None or self.stage == "ended":
            return expired
        if self.stage == "answering" and event_type == "call.answered":
            self.answered = True
            return self._gather("welcome", now)
        if (
            self.pending.action == "gather_using_speak"
            and event_type == "call.gather.ended"
        ):
            if status not in ("valid", "invalid", "timeout"):
                return self.fail("provider_failure", now=now)
            digits = payload.get("digits", "")
            if self.stage == "menu" and status == "valid" and digits == "2":
                return self.fail(
                    "unsupported_business",
                    now=now,
                    prompt="Business requests are not supported by this test IVR. Goodbye.",
                )
            expected = {
                "challenge": self.challenge + "#",
                "identifier": self.settings.synthetic_id + "#",
            }.get(self.stage, "1")
            if status != "valid" or not isinstance(digits, str) or digits != expected:
                if self.attempt < self.settings.max_attempts:
                    return self._gather(self.stage, now, retry=True)
                return self.fail(
                    "input_rejected",
                    now=now,
                    prompt="We could not verify your entry. Goodbye.",
                )
            next_stage = {
                "welcome": "challenge",
                "challenge": "menu",
                "menu": "identifier",
                "identifier": "confirmation",
                "confirmation": "result",
            }[self.stage]
            scenario = self.settings.scenario
            if next_stage == "challenge":
                if scenario == "early_hangup":
                    return self.hangup(now=now)
                if scenario == "silent_stage":
                    self.stage = "silent"
                    self.pending = None
                    self.deadline = self.call_deadline
                    return None
            if next_stage == "confirmation" and scenario == "rejected_id":
                return self.fail(
                    "input_rejected",
                    now=now,
                    prompt="We could not verify your entry. Goodbye.",
                )
            if next_stage == "result":
                self.attempt = 1
                return self._reserve(
                    "result",
                    "speak",
                    self._speech_fields(
                        "Your requested value is unavailable."
                        if scenario == "unsupported_result"
                        else result_prompt(self.settings.result_amount)
                    ),
                    now,
                    self.settings.speech_grace_seconds,
                )
            return self._gather(next_stage, now)
        if self.stage in ("result", "failure") and event_type == "call.speak.ended":
            if self.stage == "result":
                self.outcome = (
                    "result_spoken" if status == "completed" else "speech_failed"
                )
            return self.hangup(now=now)
        return None

    def command_failed(self, command_id, *, now):
        if self.pending is None or self.pending.command_id != command_id:
            return None
        return self.fail("command_failed", now=now)

    def expire(self, *, now):
        if self.stage == "ended":
            return None
        if self.stage == "hanging_up":
            if now >= self.deadline:
                self.end("hangup_unconfirmed")
            return None
        if now >= self.call_deadline:
            self.outcome = "call_timeout"
            return self.hangup(now=now)
        if now < self.deadline:
            return None
        if self.stage in ("result", "failure"):
            self.outcome = "speech_timeout"
            return self.hangup(now=now)
        return self.fail("completion_timeout", now=now)


logger = logging.getLogger("ivr.fixture")
logger.setLevel(logging.INFO)
logger.parent = logging.getLogger("uvicorn.error")
EVENTS = frozenset(
    {
        "call.initiated",
        "call.answered",
        "call.gather.ended",
        "call.speak.ended",
        "call.hangup",
    }
)


class Fixture:
    def __init__(self, settings, send, *, started_at, clock=time.monotonic):
        self.settings, self.send = settings, send
        self.started_at, self.clock = started_at, clock
        self.active = None
        self.seen = set()
        # ponytail: process-local retention, max 1000 calls; durable storage for restarts/scale.
        self.tombstones = set()
        self.busy = {}
        self.tasks = {}
        self.closed = False
        # ponytail: one worker and one short-held lock; per-call locks if concurrency grows.
        self.lock = asyncio.Lock()
        self.run_id = str(uuid4())

    def _log(self, reason, command=None):
        flow = self.active
        logger.info(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "reason": reason,
                    "stage": flow.stage if flow else "idle",
                    "attempt": flow.attempt if flow else 0,
                    "action": command.action if command else None,
                    "elapsed": round(self.clock() - flow.started_at, 3) if flow else 0,
                }
            )
        )

    def _owned(self, command):
        if self.active and self.active.pending is command:
            return True
        busy = self.busy.get(command.call_control_id)
        return busy is not None and busy[0] is command

    def _sync(self, command=None):
        if self.active and self.active.stage == "ended":
            self._log(self.active.outcome)
            self.tombstones.add(self.active.call_control_id)
            self.active = None
            self.seen.clear()
        for task, pending in list(self.tasks.items()):
            if (
                not self._owned(pending)
                and task is not asyncio.current_task()
                and not task.cancelling()
            ):
                task.cancel()
        if command is not None:
            self._log("command_reserved", command)
            task = asyncio.create_task(self._run(command))
            self.tasks[task] = command
            task.add_done_callback(lambda done: self.tasks.pop(done, None))

    async def _run(self, command):
        try:
            if not self._owned(command):
                return
            await self.send(command)
        except Exception as error:  # noqa: BLE001 — contain task errors without leaking call tokens
            # Exceptions never escape to asyncio's raw exception/URL logger.
            async with self.lock:
                if not self._owned(command):
                    return
                self._log(
                    error.reason
                    if isinstance(error, CommandError)
                    else "internal_error",
                    command,
                )
                if self.active and self.active.pending is command:
                    self._sync(
                        self.active.command_failed(command.command_id, now=self.clock())
                    )
                else:
                    self._log("hangup_unconfirmed", command)
        else:
            if self._owned(command):
                self._log("command_accepted", command)

    @staticmethod
    def _validate(data):
        payload = data["payload"]
        for name, limit in (
            ("call_control_id", 1024),
            ("call_leg_id", 256),
            ("connection_id", 256),
        ):
            value = payload.get(name)
            if not isinstance(value, str) or not 1 <= len(value) <= limit:
                raise ValueError("Invalid call event")
        kind = data["event_type"]
        if kind == "call.initiated":
            try:
                occurred = datetime.fromisoformat(data["occurred_at"])
                if occurred.tzinfo is None:
                    raise ValueError
                if payload.get("direction") not in ("incoming", "outgoing"):
                    raise ValueError
            except KeyError, TypeError, ValueError:
                raise ValueError("Invalid call event") from None
            return occurred
        if kind in ("call.gather.ended", "call.speak.ended"):
            status = payload.get("status")
            if not isinstance(status, str) or not 1 <= len(status) <= 128:
                raise ValueError("Invalid call event")
            if kind == "call.gather.ended":
                digits = payload.get("digits", "" if status != "valid" else None)
                if not isinstance(digits, str) or len(digits) > 128:
                    raise ValueError("Invalid call event")
        # Malformed/missing correlation cannot advance; let the watchdog end the wait.
        return None

    async def accept(self, data):
        kind = data["event_type"]
        if kind not in EVENTS:
            return
        occurred = self._validate(data)
        payload = data["payload"]
        call = payload["call_control_id"]
        if payload["connection_id"] != self.settings.connection_id:
            return
        async with self.lock:
            if self.closed:
                return
            now = self.clock()
            if kind == "call.hangup":
                if self.active and call == self.active.call_control_id:
                    if payload["call_leg_id"] != self.active.call_leg_id:
                        return
                    self.active.handle(kind, payload, now=now)
                    self._sync()
                elif call in self.busy:
                    if payload["call_leg_id"] == self.busy[call][1]:
                        del self.busy[call]
                        self._sync()
                elif len(self.tombstones) + bool(self.active) < 1000:
                    self.tombstones.add(call)
                return
            if call in self.tombstones:
                return
            if kind == "call.initiated":
                if self.active and call == self.active.call_control_id:
                    return
                if (
                    payload["direction"] != "incoming"
                    or occurred < self.started_at
                    or occurred > datetime.now(UTC) + timedelta(seconds=300)
                ):
                    return
                if len(self.tombstones) + bool(self.active) >= 1000:
                    self._log("capacity_reached")
                    return
                if self.active:
                    command = make_command(call, "hangup", {})
                    self.tombstones.add(call)
                    self.busy[call] = (command, payload["call_leg_id"], now + 15)
                else:
                    self.active = Flow(
                        self.settings, call, payload["call_leg_id"], now=now
                    )
                    self.seen = {data["id"]}
                    command = self.active.pending
                self._sync(command)
                return
            if not self.active or call != self.active.call_control_id:
                return
            if (
                payload["call_leg_id"] != self.active.call_leg_id
                or data["id"] in self.seen
            ):
                return
            token = payload.get("client_state")
            if not isinstance(token, str) or not 1 <= len(token) <= 256:
                return
            if len(self.seen) >= 4096 and self.active.stage not in (
                "failure",
                "hanging_up",
            ):
                self._sync(self.active.fail("event_capacity_reached", now=now))
                return
            if len(self.seen) < 4096:
                self.seen.add(data["id"])
            self._sync(self.active.handle(kind, payload, now=now))

    async def tick(self):
        async with self.lock:
            now = self.clock()
            for call, (command, leg, deadline) in list(self.busy.items()):
                if now >= deadline:
                    self._log("hangup_unconfirmed", command)
                    del self.busy[call]
            command = self.active.expire(now=now) if self.active else None
            self._sync(command)

    async def drain(self):
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)

    async def close(self):
        async with self.lock:
            self.closed = True
            command = self.active.hangup(now=self.clock()) if self.active else None
            self._sync(command)
        try:
            async with asyncio.timeout(15):
                await self.drain()
        except TimeoutError:
            pass
        finally:
            for task in list(self.tasks):
                task.cancel()
            await self.drain()
            async with self.lock:
                self.busy.clear()
                if self.active:
                    self.active.end("hangup_unconfirmed")
                self._sync()
