"""Narrow grammar: ASCII digit runs/words with limited separators only."""

import pytest

from speech import parse_digits, recognize


@pytest.mark.parametrize("text", ["zero seven four two", "0742", "0 7-4,2"])
def test_leading_zero(text):
    assert parse_digits(text, 4) == "0742"


@pytest.mark.parametrize(
    "text",
    [
        "742",
        "07421",
        "0.742",
        "+0742",
        "０７４２",
        "oh seven four two",
        "zero seven four two or one two three four",
        "seventy four two",
    ],
)
def test_no_guessing(text):
    with pytest.raises(ValueError):
        parse_digits(text, 4)


def test_complete_challenge_requires_both_markers():
    assert recognize(
        "challenge", "Your verification code is zero seven", "000123456"
    ) == (
        "pending",
        None,
    )
    assert recognize(
        "challenge",
        "Your verification code is zero seven four two. "
        "Enter the code followed by pound.",
        "000123456",
    ) == ("complete", "0742#")
    assert recognize(
        "confirmation",
        "You entered zero zero zero one two three four five seven. Press 1 if correct.",
        "000123456",
    ) == ("invalid", "id_mismatch")


@pytest.mark.parametrize(
    ("text", "length", "expected"),
    [
        ("ZERO SEVEN FOUR TWO", 4, "0742"),
        ("Zero-Seven-Four-Two", 4, "0742"),
        ("zero, seven, four, two", 4, "0742"),
        ("0 7 4 2", 4, "0742"),
        ("07 42", 4, "0742"),
        ("  0742  ", 4, "0742"),
        ("zero zero zero one two three four five six", 9, "000123456"),
        ("000123456", 9, "000123456"),
    ],
)
def test_parse_digits_variants(text, length, expected):
    assert parse_digits(text, length) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "to seven four two",
        "for seven four two",
        "zero seven",
        "zero seven four two five",
        "-0742",
        "0742!",
        "zero seven. four two",
        "1-800-555",
        "00 7 4 2 ",
        "zero seven four 2x",
    ],
)
def test_parse_digits_rejects(text):
    with pytest.raises(ValueError):
        parse_digits(text, 4)


def test_parse_digits_rejects_non_string():
    with pytest.raises(ValueError):
        parse_digits(None, 4)
    with pytest.raises(ValueError):
        parse_digits(742, 4)


@pytest.mark.parametrize("text", ["zero\tseven four two", "zero\nseven four two"])
def test_parse_digits_rejects_whitespace_control_chars(text):
    with pytest.raises(ValueError):
        parse_digits(text, 4)


def test_welcome_complete_variants():
    assert recognize("welcome", "Welcome. Press 1 to continue.", "000123456") == (
        "complete",
        "1",
    )
    assert recognize("welcome", "welcome press one to continue", "000123456") == (
        "complete",
        "1",
    )
    assert recognize("welcome", "Press ONE to continue!", "000123456") == (
        "complete",
        "1",
    )


def test_welcome_incomplete_is_pending():
    assert recognize("welcome", "Welcome to the test IVR.", "000123456") == (
        "pending",
        None,
    )
    assert recognize("welcome", "Press 1 to", "000123456") == ("pending", None)


def test_welcome_wrong_choice_is_invalid():
    status, _ = recognize("welcome", "Press 2 to continue.", "000123456")
    assert status == "invalid"


def test_welcome_conflicting_choices_are_invalid():
    status, _ = recognize(
        "welcome", "Press 1 to continue. Press 2 to continue.", "000123456"
    )
    assert status == "invalid"


def test_menu_third_choice_is_invalid():
    status, _ = recognize(
        "menu",
        "Press 1 for personal. Press 2 for business. Press 3 for personal.",
        "000123456",
    )
    assert status == "invalid"


def test_identifier_conflicting_count_is_invalid():
    status, _ = recognize(
        "identifier",
        "Enter your nine digit personal ID followed by pound. "
        "Enter your eight digit personal ID followed by pound.",
        "000123456",
    )
    assert status == "invalid"


def test_menu_requires_both_options():
    both = "Press 1 for personal. Press 2 for business."
    assert recognize("menu", both, "000123456") == ("complete", "1")
    words = "Press one for personal, press two for business."
    assert recognize("menu", words, "000123456") == ("complete", "1")
    assert recognize("menu", "Press 1 for personal.", "000123456") == (
        "pending",
        None,
    )
    assert recognize("menu", "Press 2 for business.", "000123456") == (
        "pending",
        None,
    )


def test_menu_wrong_digits_invalid():
    status, _ = recognize(
        "menu",
        "Press 2 for personal. Press 1 for business.",
        "000123456",
    )
    assert status == "invalid"


def test_identifier_completes_with_configured_id():
    text = "Enter your nine digit personal ID followed by pound."
    assert recognize("identifier", text, "000123456") == ("complete", "000123456#")
    hyphen = "Enter your nine-digit personal ID followed by pound."
    assert recognize("identifier", hyphen, "987654321") == ("complete", "987654321#")
    numeral = "Enter your 9 digit personal id followed by pound."
    assert recognize("identifier", numeral, "000123456") == ("complete", "000123456#")


def test_identifier_incomplete_is_pending():
    assert recognize("identifier", "Enter your nine digit", "000123456") == (
        "pending",
        None,
    )


def test_confirmation_match_completes():
    text = "You entered zero zero zero one two three four five six. Press 1 if correct."
    assert recognize("confirmation", text, "000123456") == ("complete", "1")
    words = "You entered 0 0 0 1 2 3 4 5 6. Press one if correct."
    assert recognize("confirmation", words, "000123456") == ("complete", "1")


def test_confirmation_wrong_count_invalid():
    text = "You entered zero seven four two. Press 1 if correct."
    status, _ = recognize("confirmation", text, "000123456")
    assert status == "invalid"


def test_challenge_wrong_count_invalid():
    text = (
        "Your verification code is zero seven four. Enter the code followed by pound."
    )
    status, _ = recognize("challenge", text, "000123456")
    assert status == "invalid"


def test_result_completes_without_digits():
    text = "Your requested value is one thousand dollars and zero cents."
    assert recognize("result", text, "000123456") == ("complete", None)
    assert recognize("result", "Please hold.", "000123456") == ("pending", None)


def test_result_requires_your_prefix():
    assert recognize(
        "result",
        "YOUR requested value is one thousand dollars and zero cents.",
        "000123456",
    ) == ("complete", None)
    status, _ = recognize(
        "result",
        "The requested value is one thousand dollars.",
        "000123456",
    )
    assert status != "complete"


@pytest.mark.parametrize(
    "text",
    [
        "That entry was not accepted. Goodbye.",
        "We could not verify your entry. Goodbye.",
        "Test service is unavailable. Goodbye.",
    ],
)
def test_fixture_rejection_is_invalid(text):
    assert recognize("challenge", text, "000123456")[0] == "invalid"
    assert recognize("menu", text, "000123456")[0] == "invalid"


def test_business_unsupported_is_invalid():
    text = "Business requests are not supported. Goodbye."
    assert recognize("menu", text, "000123456")[0] == "invalid"


def test_ambiguous_mixed_prompts_invalid():
    text = (
        "Press 1 to continue. Your verification code is zero seven four two. "
        "Enter the code followed by pound."
    )
    assert recognize("welcome", text, "000123456")[0] == "invalid"
    assert recognize("challenge", text, "000123456")[0] == "invalid"


def test_unknown_stage_is_invalid():
    assert recognize("dialing", "Press 1 to continue.", "000123456")[0] == "invalid"


def test_reasons_are_sanitized():
    evil = "0742"
    for stage in ("welcome", "challenge", "menu", "identifier", "confirmation"):
        status, reason = recognize(stage, "Business requests are not supported.", "x")
        assert status == "invalid"
        assert evil not in (reason or "")
