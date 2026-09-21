"""Client settings: explicit env mapping, strict bounds, no secret leakage."""

import pytest

from client import ClientSettings, load_client_settings

VALID = {
    "TELNYX_API_KEY": "test-api-key",
    "IVR_CLIENT_CONNECTION_ID": "client-app-id",
    "IVR_CLIENT_FROM_NUMBER": "+15550001111",
    "IVR_CLIENT_TO_NUMBER": "+15550002222",
}


def test_defaults_and_explicit_values(monkeypatch):
    for key, value in VALID.items():
        monkeypatch.setenv(key, value)
    settings = load_client_settings()
    assert settings.api_key == "test-api-key"
    assert settings.connection_id == "client-app-id"
    assert settings.from_number == "+15550001111"
    assert settings.to_number == "+15550002222"
    assert settings.synthetic_id == "000123456"
    assert settings.stage_timeout_seconds == 30
    assert settings.call_timeout_seconds == 180
    assert settings.dtmf_duration_ms == 250
    assert settings.dtmf_pause_units == 0


def test_fixture_only_vars_are_ignored(monkeypatch):
    for key, value in VALID.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("IVR_CHALLENGE_OVERRIDE", "not-a-code")
    monkeypatch.setenv("IVR_RESULT_AMOUNT", "not-an-amount")
    monkeypatch.setenv("IVR_CONNECTION_ID", "fixture-app-id")
    monkeypatch.setenv("IVR_SYNTHETIC_ID", "999")
    settings = load_client_settings()
    assert settings.connection_id == "client-app-id"
    assert settings.synthetic_id == "000123456"


def test_secret_not_in_repr(monkeypatch):
    for key, value in VALID.items():
        monkeypatch.setenv(key, value)
    settings = load_client_settings()
    assert "test-api-key" not in repr(settings)


@pytest.mark.parametrize(
    "key",
    [
        "TELNYX_API_KEY",
        "IVR_CLIENT_CONNECTION_ID",
        "IVR_CLIENT_FROM_NUMBER",
        "IVR_CLIENT_TO_NUMBER",
    ],
)
def test_missing_required_fails_without_value(monkeypatch, key):
    for name, value in VALID.items():
        if name != key:
            monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match="Invalid client configuration"):
        load_client_settings()


@pytest.mark.parametrize(
    ("updates", "bad_value"),
    [
        ({"TELNYX_API_KEY": ""}, ""),
        ({"TELNYX_API_KEY": "   "}, "   "),
        ({"TELNYX_API_KEY": "key with space é"}, "key with space é"),
        ({"IVR_CLIENT_CONNECTION_ID": ""}, ""),
        ({"IVR_CLIENT_CONNECTION_ID": "   "}, "   "),
        ({"IVR_CLIENT_CONNECTION_ID": "x" * 257}, "x" * 257),
        ({"IVR_CLIENT_FROM_NUMBER": "5550001111"}, "5550001111"),
        ({"IVR_CLIENT_FROM_NUMBER": "+05550001111"}, "+05550001111"),
        ({"IVR_CLIENT_FROM_NUMBER": "+1555001"}, "+1555001"),
        ({"IVR_CLIENT_FROM_NUMBER": "+15550001111111111"}, "+15550001111111111"),
        ({"IVR_CLIENT_FROM_NUMBER": "+15550001111 "}, "+15550001111 "),
        ({"IVR_CLIENT_TO_NUMBER": "not-a-number"}, "not-a-number"),
        (
            {"IVR_CLIENT_TO_NUMBER": "+１５５５０００２２２２"},
            "+１５５５０００２２２２",
        ),
        ({"IVR_CLIENT_SYNTHETIC_ID": "12345678"}, "12345678"),
        ({"IVR_CLIENT_SYNTHETIC_ID": "1234567890"}, "1234567890"),
        ({"IVR_CLIENT_SYNTHETIC_ID": "00012345a"}, "00012345a"),
        ({"IVR_CLIENT_SYNTHETIC_ID": "０００１２３４５６"}, "０００１２３４５６"),
        ({"IVR_CLIENT_SYNTHETIC_ID": " 000123456"}, " 000123456"),
        ({"IVR_CLIENT_STAGE_TIMEOUT_SECONDS": "9"}, "9"),
        ({"IVR_CLIENT_STAGE_TIMEOUT_SECONDS": "61"}, "61"),
        ({"IVR_CLIENT_STAGE_TIMEOUT_SECONDS": "True"}, "True"),
        ({"IVR_CLIENT_STAGE_TIMEOUT_SECONDS": "30 "}, "30 "),
        ({"IVR_CLIENT_STAGE_TIMEOUT_SECONDS": "3.0"}, "3.0"),
        ({"IVR_CLIENT_CALL_TIMEOUT_SECONDS": "59"}, "59"),
        ({"IVR_CLIENT_CALL_TIMEOUT_SECONDS": "601"}, "601"),
        ({"IVR_CLIENT_CALL_TIMEOUT_SECONDS": "False"}, "False"),
        ({"IVR_CLIENT_DTMF_DURATION_MS": "99"}, "99"),
        ({"IVR_CLIENT_DTMF_DURATION_MS": "501"}, "501"),
        ({"IVR_CLIENT_DTMF_PAUSE_UNITS": "-1"}, "-1"),
        ({"IVR_CLIENT_DTMF_PAUSE_UNITS": "3"}, "3"),
        ({"IVR_CLIENT_DTMF_PAUSE_UNITS": "1.0"}, "1.0"),
    ],
)
def test_invalid_values_fail_generically(monkeypatch, updates, bad_value):
    for name, value in VALID.items():
        monkeypatch.setenv(name, value)
    for name, value in updates.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError) as excinfo:
        load_client_settings()
    assert str(excinfo.value) == "Invalid client configuration"
    if bad_value:
        assert bad_value not in str(excinfo.value)


def test_equal_numbers_rejected(monkeypatch):
    for name, value in VALID.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("IVR_CLIENT_TO_NUMBER", "+15550001111")
    with pytest.raises(RuntimeError, match="Invalid client configuration"):
        load_client_settings()


def test_inverted_deadlines_rejected(monkeypatch):
    for name, value in VALID.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("IVR_CLIENT_STAGE_TIMEOUT_SECONDS", "50")
    monkeypatch.setenv("IVR_CLIENT_CALL_TIMEOUT_SECONDS", "40")
    with pytest.raises(RuntimeError, match="Invalid client configuration"):
        load_client_settings()


def test_deadline_edges_accepted(monkeypatch):
    for name, value in VALID.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("IVR_CLIENT_STAGE_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("IVR_CLIENT_CALL_TIMEOUT_SECONDS", "60")
    settings = load_client_settings()
    assert settings.stage_timeout_seconds == 60
    assert settings.call_timeout_seconds == 60


def test_direct_construction_validates(monkeypatch):
    with pytest.raises(RuntimeError, match="Invalid client configuration"):
        ClientSettings(
            api_key="k",
            connection_id="c",
            from_number="+15550001111",
            to_number="+15550001111",
        )
    with pytest.raises(RuntimeError, match="Invalid client configuration"):
        ClientSettings(
            api_key="k",
            connection_id="c",
            from_number="+15550001111",
            to_number="+15550002222",
            dtmf_pause_units=True,
        )
