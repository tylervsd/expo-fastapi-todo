"""Narrow prompt grammar for the automated IVR caller.

Only ASCII digit runs and zero-nine words with space/comma/hyphen separators.
No fixture imports; identifiers stay strings; unknown text is never guessed.
"""

import re

WORDS = dict(
    zip(
        [
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
        ],
        "0123456789",
        strict=True,
    )
)

_SEP = r"[\s,.:;!?\-]+"


def _phrase(*words: str) -> str:
    return (
        r"(?<![a-z0-9])"
        + _SEP.join(re.escape(word) for word in words)
        + r"(?![a-z0-9])"
    )


def parse_digits(text: str, length: int) -> str:
    """Return the exact digit string, else raise ValueError."""
    if not isinstance(text, str):
        raise ValueError("unrecognized_digits")  # noqa: TRY004 — plan contract is ValueError
    if "." in text or "+" in text:
        raise ValueError("unrecognized_digits")
    if re.search(r"[\t\n\r\f\v]", text):
        raise ValueError("unrecognized_digits")
    if text.strip().startswith("-"):
        raise ValueError("unrecognized_digits")
    tokens = [token for token in re.split(r"[ ,\-]+", text.strip().lower()) if token]
    if not tokens:
        raise ValueError("unrecognized_digits")
    digits = "".join(WORDS.get(token, token) for token in tokens)
    if not re.fullmatch(r"[0-9]{%d}" % length, digits):  # noqa: UP031 — dynamic count
        raise ValueError("unrecognized_digits")
    return digits


_REJECTION = (
    (
        re.compile(_phrase("that", "entry", "was", "not", "accepted")),
        "fixture_rejection",
    ),
    (
        re.compile(_phrase("we", "could", "not", "verify", "your", "entry")),
        "fixture_rejection",
    ),
    (
        re.compile(_phrase("business", "requests", "are", "not", "supported")),
        "unexpected_menu",
    ),
    (
        re.compile(_phrase("test", "service", "is", "unavailable")),
        "fixture_rejection",
    ),
)


def _compiled(*phrases: tuple) -> list:
    return [re.compile(_phrase(*words)) for words in phrases]


_STAGE_SIGNS = {
    "welcome": _compiled(("to", "continue")),
    "challenge": _compiled(
        ("verification", "code", "is"),
        ("enter", "the", "code", "followed", "by", "pound"),
    ),
    "menu": _compiled(("for", "personal"), ("for", "business")),
    "identifier": _compiled(("personal", "id")),
    "confirmation": _compiled(("you", "entered")),
    "result": _compiled(("requested", "value", "is")),
}

_WELCOME_OK = re.compile(
    _phrase("press", "one", "to", "continue")
    + r"|"
    + _phrase("press", "1", "to", "continue")
)
_WELCOME_ANY = re.compile(
    r"(?<![a-z0-9])press"
    + _SEP
    + r"([a-z0-9]+)"
    + _SEP
    + r"to"
    + _SEP
    + r"continue(?![a-z0-9])"
)
_CHALLENGE_START = re.compile(_phrase("your", "verification", "code", "is"))
_CHALLENGE_END = re.compile(_phrase("enter", "the", "code", "followed", "by", "pound"))
_MENU_PERSONAL = re.compile(
    r"(?<![a-z0-9])press"
    + _SEP
    + r"(one|1)"
    + _SEP
    + r"for"
    + _SEP
    + r"personal(?![a-z0-9])"
)
_MENU_BUSINESS = re.compile(
    r"(?<![a-z0-9])press"
    + _SEP
    + r"(two|2)"
    + _SEP
    + r"for"
    + _SEP
    + r"business(?![a-z0-9])"
)
_MENU_PERSONAL_ANY = re.compile(
    r"(?<![a-z0-9])press"
    + _SEP
    + r"([a-z0-9]+)"
    + _SEP
    + r"for"
    + _SEP
    + r"personal(?![a-z0-9])"
)
_MENU_BUSINESS_ANY = re.compile(
    r"(?<![a-z0-9])press"
    + _SEP
    + r"([a-z0-9]+)"
    + _SEP
    + r"for"
    + _SEP
    + r"business(?![a-z0-9])"
)
_IDENTIFIER_OK = re.compile(
    r"(?<![a-z0-9])enter"
    + _SEP
    + r"your"
    + _SEP
    + r"(?:nine|9)"
    + _SEP
    + r"digit"
    + _SEP
    + r"personal"
    + _SEP
    + r"id"
    + _SEP
    + r"followed"
    + _SEP
    + r"by"
    + _SEP
    + r"pound(?![a-z0-9])"
)
_IDENTIFIER_ANY = re.compile(
    r"(?<![a-z0-9])enter"
    + _SEP
    + r"your"
    + _SEP
    + r"([a-z0-9]+)"
    + _SEP
    + r"digit(?![a-z0-9])"
)
_CONFIRM_START = re.compile(_phrase("you", "entered"))
_CONFIRM_END_OK = re.compile(
    _phrase("press", "one", "if", "correct")
    + r"|"
    + _phrase("press", "1", "if", "correct")
)
_CONFIRM_END_ANY = re.compile(
    r"(?<![a-z0-9])press"
    + _SEP
    + r"([a-z0-9]+)"
    + _SEP
    + r"if"
    + _SEP
    + r"correct(?![a-z0-9])"
)
_RESULT = re.compile(_phrase("requested", "value", "is"))


def _clean_span(span: str) -> str:
    return span.strip().strip(".,;:!?").strip()


def _stages_present(low: str) -> set:
    found = set()
    for stage, patterns in _STAGE_SIGNS.items():
        if any(pattern.search(low) for pattern in patterns):
            found.add(stage)
    return found


def recognize(stage: str, text: str, synthetic_id: str) -> tuple[str, str | None]:
    """Return (pending|complete|invalid, digits-or-reason)."""
    if stage not in _STAGE_SIGNS:
        return ("invalid", "unknown_stage")
    if not isinstance(text, str):
        return ("invalid", "unrecognized")
    low = text.lower()
    for pattern, reason in _REJECTION:
        if pattern.search(low):
            return ("invalid", reason)
    if len(_stages_present(low)) > 1:
        return ("invalid", "ambiguous")

    if stage == "welcome":
        if _WELCOME_OK.search(low):
            choices = {m.group(1).lower() for m in _WELCOME_ANY.finditer(low)}
            if len(choices) > 1 or choices - {"one", "1"}:
                return ("invalid", "unexpected_menu")
            return ("complete", "1")
        if _WELCOME_ANY.search(low):
            return ("invalid", "unexpected_menu")
        return ("pending", None)

    if stage == "challenge":
        start = _CHALLENGE_START.search(low)
        end = _CHALLENGE_END.search(low)
        if start and not end:
            return ("pending", None)
        if end and not start:
            return ("invalid", "challenge_unrecognized")
        if not (start and end):
            return ("pending", None)
        if end.start() < start.end():
            return ("invalid", "ambiguous")
        try:
            digits = parse_digits(_clean_span(low[start.end() : end.start()]), 4)
        except ValueError:
            return ("invalid", "challenge_unrecognized")
        return ("complete", digits + "#")

    if stage == "menu":
        personal_choices = [
            m.group(1).lower() for m in _MENU_PERSONAL_ANY.finditer(low)
        ]
        business_choices = [
            m.group(1).lower() for m in _MENU_BUSINESS_ANY.finditer(low)
        ]
        if any(c not in ("one", "1") for c in personal_choices):
            return ("invalid", "unexpected_menu")
        if any(c not in ("two", "2") for c in business_choices):
            return ("invalid", "unexpected_menu")
        if len({c.replace("one", "1") for c in personal_choices}) > 1:
            return ("invalid", "unexpected_menu")
        if len({c.replace("two", "2") for c in business_choices}) > 1:
            return ("invalid", "unexpected_menu")
        personal = _MENU_PERSONAL.search(low)
        business = _MENU_BUSINESS.search(low)
        if personal and business:
            return ("complete", "1")
        return ("pending", None)

    if stage == "identifier":
        if _IDENTIFIER_OK.search(low):
            counts = {m.group(1).lower() for m in _IDENTIFIER_ANY.finditer(low)}
            if len(counts) > 1 or counts - {"nine", "9"}:
                return ("invalid", "unexpected_menu")
            return ("complete", synthetic_id + "#")
        match = _IDENTIFIER_ANY.search(low)
        if match and match.group(1) not in ("nine", "9"):
            return ("invalid", "unexpected_menu")
        return ("pending", None)

    if stage == "confirmation":
        start = _CONFIRM_START.search(low)
        end = _CONFIRM_END_OK.search(low)
        if end and not start:
            return ("invalid", "confirmation_unrecognized")
        if start and not end:
            wrong = _CONFIRM_END_ANY.search(low)
            if wrong:
                return ("invalid", "unexpected_menu")
            return ("pending", None)
        if not (start and end):
            return ("pending", None)
        if end.start() < start.end():
            return ("invalid", "ambiguous")
        try:
            digits = parse_digits(_clean_span(low[start.end() : end.start()]), 9)
        except ValueError:
            return ("invalid", "confirmation_unrecognized")
        if digits != synthetic_id:
            return ("invalid", "id_mismatch")
        return ("complete", "1")

    if _RESULT.search(low):
        return ("complete", None)
    return ("pending", None)
