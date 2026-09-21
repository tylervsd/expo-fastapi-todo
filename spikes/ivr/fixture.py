"""Single-call, in-memory test IVR. No outbound dialing."""

import os
import re
import secrets
from dataclasses import dataclass, fields
from decimal import Decimal

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
