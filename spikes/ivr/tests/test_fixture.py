import pytest

from fixture import (
    Settings,
    digit_words,
    integer_words,
    load_settings,
    new_challenge,
    result_prompt,
)


def settings(**changes):
    return Settings(**({"api_key": "test-only", "connection_id": "app"} | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"api_key": ""},
        {"api_key": " "},
        {"api_key": "bad\nkey"},
        {"connection_id": ""},
        {"connection_id": "x" * 257},
        {"synthetic_id": "123"},
        {"synthetic_id": "０００123456"},
        {"challenge_override": "123"},
        {"challenge_override": "１２３４"},
        {"gather_timeout_ms": 999},
        {"gather_timeout_ms": 60001},
        {"gather_timeout_ms": True},
        {"inter_digit_timeout_ms": 999},
        {"inter_digit_timeout_ms": 20001},
        {"max_attempts": 0},
        {"max_attempts": 4},
        {"speech_grace_seconds": 9},
        {"speech_grace_seconds": 61},
        {"call_timeout_seconds": 59},
        {"call_timeout_seconds": 601},
        {"voice": "invalid"},
    ],
)
def test_settings_fail_closed(changes):
    with pytest.raises(RuntimeError, match="^Invalid fixture configuration$"):
        settings(**changes)


@pytest.mark.parametrize(
    "amount",
    [
        "-1.00",
        "NaN",
        "Infinity",
        "1e2",
        "1,000.00",
        " 1.00",
        "1.001",
        "10000.00",
        "01.00",
        "١.00",
        "1",
    ],
)
def test_amount_rejected_without_rounding(amount):
    with pytest.raises(RuntimeError, match="^Invalid fixture configuration$"):
        settings(result_amount=amount)


def test_environment(monkeypatch):
    for name in ("TELNYX_API_KEY", "IVR_CONNECTION_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError):
        load_settings()
    monkeypatch.setenv("TELNYX_API_KEY", "test-only")
    monkeypatch.setenv("IVR_CONNECTION_ID", "app")
    monkeypatch.setenv("IVR_MAX_ATTEMPTS", "3")
    assert load_settings().max_attempts == 3
    monkeypatch.setenv("IVR_MAX_ATTEMPTS", "no")
    with pytest.raises(RuntimeError, match="^Invalid fixture configuration$"):
        load_settings()


def test_spoken_values(monkeypatch):
    monkeypatch.setattr("fixture.secrets.randbelow", lambda limit: 742)
    assert new_challenge() == "0742"
    monkeypatch.setattr("fixture.secrets.randbelow", lambda limit: 0)
    assert new_challenge() == "0000"
    assert digit_words("0742") == "zero seven four two"
    assert digit_words("000123456").startswith("zero zero zero one")
    assert integer_words(9999) == "nine thousand nine hundred ninety-nine"


@pytest.mark.parametrize(
    "amount,words",
    [
        ("1425.30", "one thousand four hundred twenty-five dollars and thirty cents"),
        ("27.05", "twenty-seven dollars and five cents"),
        ("1.01", "one dollar and one cent"),
        ("0.00", "zero dollars and zero cents"),
        ("10.10", "ten dollars and ten cents"),
        ("1000.00", "one thousand dollars and zero cents"),
        (
            "9999.99",
            "nine thousand nine hundred ninety-nine dollars and ninety-nine cents",
        ),
    ],
)
def test_result_prompt(amount, words):
    assert result_prompt(amount) == f"Your requested value is {words}."


def test_validation_survives_optimized_python():
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [
            sys.executable,
            "-O",
            "-c",
            "from fixture import Settings; Settings(api_key='', connection_id='app')",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Invalid fixture configuration" in result.stderr
