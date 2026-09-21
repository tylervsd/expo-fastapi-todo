"""Client settings: explicit env mapping, strict bounds, no secret leakage."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from client import ClientFlow, ClientSettings, load_client_settings
from telnyx_commands import DialIdentity

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


BASE = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)


def _settings(**overrides):
    values = {
        "api_key": "test-api-key",
        "connection_id": "client-app-id",
        "from_number": "+15550001111",
        "to_number": "+15550002222",
    }
    values.update(overrides)
    return ClientSettings(**values)


def _identity():
    return DialIdentity(call_control_id="client-call", call_leg_id="client-leg")


def _iso(offset_seconds):
    return (BASE + timedelta(seconds=offset_seconds)).isoformat()


class _Builder:
    def __init__(self):
        self.count = 0

    def event(
        self,
        event_type,
        *,
        offset,
        transcript=None,
        is_final=None,
        eid=None,
    ):
        self.count += 1
        data = {
            "id": eid or f"evt-{self.count}",
            "event_type": event_type,
            "occurred_at": _iso(offset),
            "payload": {
                "call_control_id": "client-call",
                "call_leg_id": "client-leg",
            },
        }
        if transcript is not None or is_final is not None:
            data["payload"]["transcription_data"] = {
                "transcript": transcript,
                "is_final": is_final,
            }
        return data


def _flow(**overrides):
    settings = _settings(**overrides)
    flow = ClientFlow(settings, _identity(), started_at=1000.0, now=1000.0)
    return flow


def _answer(flow, builder, *, now=1001.0, offset=1):
    return flow.handle(builder.event("call.answered", offset=offset), now=now)


def _say(flow, builder, text, *, now, offset, final=True):
    return flow.handle(
        builder.event(
            "call.transcription",
            offset=offset,
            transcript=text,
            is_final=final,
        ),
        now=now,
    )


def _digits(command):
    return json.loads(command.body)["digits"]


HAPPY_TEXTS = [
    "Welcome to the test IVR. Press one to continue.",
    "Your verification code is zero seven",
    "four two. Enter the code followed by pound.",
    "Press one for personal. Press two for business.",
    "Enter your nine digit personal ID followed by pound.",
    ("You entered zero zero zero one two three four five six. Press one if correct."),
    "Your requested value is one thousand four hundred twenty-five dollars.",
]


def _drive_happy(flow, builder, texts=HAPPY_TEXTS):
    assert _answer(flow, builder) is None
    assert flow.stage == "welcome"
    commands = []
    now = 1002.0
    offset = 2
    for text in texts:
        command = _say(flow, builder, text, now=now, offset=offset)
        if command is not None:
            commands.append(command)
        now += 1.0
        offset += 1
    return commands, now, offset


def test_happy_path_replay_exact_tones():
    flow = _flow()
    builder = _Builder()
    commands, now, offset = _drive_happy(flow, builder)
    assert [_digits(command) for command in commands] == [
        "1",
        "0742#",
        "1",
        "000123456#",
        "1",
    ]
    assert all(command.action == "send_dtmf" for command in commands)
    # Result marker alone is checkpoint, not success.
    assert flow.stage == "result"
    assert flow.checkpoint_reached is True
    assert flow.exit_code is None
    assert flow.outcome is None
    hangup = flow.handle(builder.event("call.hangup", offset=offset), now=now)
    assert hangup is None
    assert flow.stage == "ended"
    assert flow.exit_code == 0


def test_partial_challenge_produces_no_command():
    flow = _flow()
    builder = _Builder()
    _drive_happy(flow, builder, texts=HAPPY_TEXTS[:2])
    assert flow.stage == "challenge"
    assert flow.pending is not None
    assert _digits(flow.pending) == "1"


def test_repeated_zero_segments_survive():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    assert _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2) is not None
    first = _say(
        flow, builder, "Your verification code is zero zero", now=1003.0, offset=3
    )
    assert first is None
    second = _say(
        flow,
        builder,
        "zero seven. Enter the code followed by pound.",
        now=1004.0,
        offset=4,
    )
    assert second is not None
    assert _digits(second) == "0007#"


def test_duplicate_event_id_ignored():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    command = _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2, final=True)
    assert command is not None
    assert flow.pending is command
    dup = {
        "id": "evt-2",
        "event_type": "call.transcription",
        "occurred_at": _iso(3),
        "payload": {
            "call_control_id": "client-call",
            "call_leg_id": "client-leg",
            "transcription_data": {
                "transcript": "Your verification code is zero seven four two. "
                "Enter the code followed by pound.",
                "is_final": True,
            },
        },
    }
    # Same id as the welcome segment: must not append or send.
    assert flow.handle(dup, now=1003.0) is None
    assert flow.stage == "challenge"
    assert flow.pending is command
    assert _digits(flow.pending) == "1"


def test_stale_prior_stage_text_ignored():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    assert _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=10) is not None
    assert flow.stage == "challenge"
    stale = builder.event(
        "call.transcription",
        offset=1,
        transcript="Welcome. Press one to continue.",
        is_final=True,
    )
    assert flow.handle(stale, now=1003.0) is None
    assert flow.stage == "challenge"
    assert flow.pending is not None
    assert _digits(flow.pending) == "1"


def test_decreasing_timestamp_fails():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    assert _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=10) is not None
    assert (
        _say(
            flow,
            builder,
            "Your verification code is zero seven",
            now=1003.0,
            offset=11,
        )
        is None
    )
    command = _say(
        flow,
        builder,
        "four two. Enter the code followed by pound.",
        now=1004.0,
        offset=5,
    )
    assert command is not None
    assert command.action == "hangup"
    assert flow.outcome == "transcript_order"
    assert flow.stage == "hanging_up"


def test_equal_timestamps_preserve_arrival_order():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    assert _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2) is not None
    assert (
        _say(
            flow, builder, "Your verification code is zero seven", now=1003.0, offset=5
        )
        is None
    )
    command = _say(
        flow,
        builder,
        "four two. Enter the code followed by pound.",
        now=1004.0,
        offset=5,
    )
    assert command is not None
    assert _digits(command) == "0742#"


def test_buffer_segment_limit_fails():
    flow = _flow(stage_timeout_seconds=60, call_timeout_seconds=600)
    builder = _Builder()
    assert _answer(flow, builder) is None
    assert _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2) is not None
    command = None
    for index in range(65):
        command = _say(
            flow,
            builder,
            "waiting for code",
            now=1003.0 + index * 0.1,
            offset=10 + index,
        )
        if flow.stage == "hanging_up":
            break
    assert command is not None
    assert command.action == "hangup"
    assert flow.outcome == "buffer_overflow"


def test_buffer_char_limit_fails():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    assert _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2) is not None
    first = _say(flow, builder, "x" * 4000, now=1003.0, offset=3)
    assert first is None
    second = _say(flow, builder, "y" * 200, now=1004.0, offset=4)
    assert second is not None
    assert second.action == "hangup"
    assert flow.outcome == "buffer_overflow"


def test_wrong_readback_is_id_mismatch_without_command():
    flow = _flow()
    builder = _Builder()
    _drive_happy(flow, builder, texts=HAPPY_TEXTS[:5])
    assert flow.stage == "confirmation"
    command = _say(
        flow,
        builder,
        "You entered zero zero zero one two three four five seven. Press 1 if correct.",
        now=1010.0,
        offset=20,
    )
    assert command is not None
    assert command.action == "hangup"
    assert "digits" not in json.loads(command.body)
    assert flow.outcome == "id_mismatch"
    assert flow.stage == "hanging_up"


def test_fixture_rejection_ends_without_resend():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    assert _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2) is not None
    command = _say(flow, builder, "That entry was not accepted.", now=1003.0, offset=3)
    assert command is not None
    assert command.action == "hangup"
    assert flow.outcome == "fixture_rejection"


def test_early_hangup_is_nonzero():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    assert _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2) is not None
    result = flow.handle(builder.event("call.hangup", offset=3), now=1003.0)
    assert result is None
    assert flow.exit_code == 1
    assert flow.stage == "ended"


def test_hangup_before_result_stays_failed_on_late_final():
    flow = _flow()
    builder = _Builder()
    _drive_happy(flow, builder, texts=HAPPY_TEXTS[:5])
    result = flow.handle(builder.event("call.hangup", offset=30), now=1010.0)
    assert result is None
    assert flow.exit_code == 1
    late = _say(flow, builder, HAPPY_TEXTS[6], now=1011.0, offset=31)
    assert late is None
    assert flow.exit_code == 1
    assert flow.checkpoint_reached is False


def test_stage_deadline_exact_triggers_hangup():
    flow = _flow(stage_timeout_seconds=10, call_timeout_seconds=60)
    builder = _Builder()
    assert _answer(flow, builder) is None
    command = flow.expire(now=1011.0)
    assert command is not None
    assert command.action == "hangup"
    assert flow.outcome == "stage_timeout"


def test_overall_deadline_exact_triggers_hangup():
    flow = _flow(stage_timeout_seconds=60, call_timeout_seconds=60)
    command = flow.expire(now=1060.0)
    assert command is not None
    assert flow.outcome == "overall_timeout"


def test_partials_and_duplicates_never_refresh_deadline():
    flow = _flow(stage_timeout_seconds=10, call_timeout_seconds=60)
    builder = _Builder()
    assert _answer(flow, builder, now=1001.0) is None
    assert (
        _say(
            flow,
            builder,
            "Your verification code is zero",
            now=1005.0,
            offset=3,
            final=False,
        )
        is None
    )
    dup_partial = {
        "id": "evt-2",
        "event_type": "call.transcription",
        "occurred_at": _iso(4),
        "payload": {
            "call_control_id": "client-call",
            "call_leg_id": "client-leg",
            "transcription_data": {
                "transcript": "Your verification code is zero",
                "is_final": False,
            },
        },
    }
    assert flow.handle(dup_partial, now=1008.0) is None
    command = flow.expire(now=1011.0)
    assert command is not None
    assert flow.outcome == "overall_timeout" or flow.outcome == "stage_timeout"


def test_result_timeout_cannot_manufacture_success():
    flow = _flow()
    builder = _Builder()
    _drive_happy(flow, builder)
    assert flow.checkpoint_reached is True
    command = flow.expire(now=1000.0 + 180.0)
    assert command is not None
    assert flow.exit_code is None
    assert flow.stage == "hanging_up"


def test_cleanup_budget_ends_hanging_up():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    command = flow.stop("stage_timeout", now=1002.0)
    assert command is not None
    assert command.action == "hangup"
    assert flow.expire(now=1010.0) is None
    done = flow.expire(now=1017.0)
    assert done is None
    assert flow.stage == "ended"
    assert flow.outcome == "hangup_unconfirmed"
    assert flow.exit_code == 1


def test_hanging_up_ignores_transcripts():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    command = flow.stop("stage_timeout", now=1002.0)
    assert command is not None
    assert flow.stage == "hanging_up"
    pending = flow.pending
    ignored = _say(
        flow, builder, "Your requested value is one dollar.", now=1003.0, offset=5
    )
    assert ignored is None
    assert flow.stage == "hanging_up"
    assert flow.pending is pending
    assert flow.outcome == "stage_timeout"
    hangup = flow.handle(builder.event("call.hangup", offset=6), now=1004.0)
    assert hangup is None
    assert flow.stage == "ended"
    assert flow.exit_code == 1


def test_timeout_then_hangup_stays_failed():
    flow = _flow()
    builder = _Builder()
    _drive_happy(flow, builder)
    assert flow.checkpoint_reached is True
    command = flow.expire(now=1000.0 + 180.0)
    assert command is not None
    assert flow.outcome == "overall_timeout"
    hangup = flow.handle(builder.event("call.hangup", offset=30), now=1000.0 + 181.0)
    assert hangup is None
    assert flow.stage == "ended"
    assert flow.outcome == "overall_timeout"
    assert flow.exit_code == 1


def test_missing_hangup_ack_is_unconfirmed():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    command = _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2)
    assert command is not None
    hangup = flow.command_failed(command.command_id, now=1003.0)
    assert hangup is not None
    assert flow.stage == "hanging_up"
    failed = flow.command_failed(hangup.command_id, now=1004.0)
    assert failed is None
    assert flow.stage == "ended"
    assert flow.outcome == "hangup_unconfirmed"
    assert flow.exit_code == 1


def test_post_result_transcripts_ignored():
    flow = _flow()
    builder = _Builder()
    _drive_happy(flow, builder)
    assert flow.stage == "result"
    assert flow.checkpoint_reached is True
    for index in range(70):
        ignored = _say(
            flow,
            builder,
            "Your verification code is zero seven four two. Enter the code followed by pound.",
            now=1010.0 + index * 0.1,
            offset=30 + index,
        )
        assert ignored is None
    assert flow.stage == "result"
    assert flow.checkpoint_reached is True
    assert flow.outcome is None
    stale = builder.event(
        "call.transcription",
        offset=1,
        transcript="garbage out of order",
        is_final=True,
    )
    assert flow.handle(stale, now=1020.0) is None
    assert flow.outcome is None
    hangup = flow.handle(builder.event("call.hangup", offset=200), now=1021.0)
    assert hangup is None
    assert flow.exit_code == 0


def test_stop_and_hangup_idempotent():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    first = flow.stop("stage_timeout", now=1002.0)
    second = flow.stop("stage_timeout", now=1003.0)
    assert first is not None
    assert second is None
    hangup = flow.handle(builder.event("call.hangup", offset=5), now=1004.0)
    assert hangup is None
    assert flow.stage == "ended"
    assert flow.handle(builder.event("call.hangup", offset=6), now=1005.0) is None


def test_obsolete_command_failure_ignored_after_progress():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    welcome = _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2)
    assert welcome is not None
    assert _say(flow, builder, HAPPY_TEXTS[1], now=1003.0, offset=3) is None
    challenge = _say(flow, builder, HAPPY_TEXTS[2], now=1004.0, offset=4)
    assert challenge is not None
    assert flow.stage == "menu"
    assert flow.command_failed(welcome.command_id, now=1005.0) is None
    assert flow.stage == "menu"
    assert flow.pending is challenge


def test_current_command_failure_stops_and_hangs_up():
    flow = _flow()
    builder = _Builder()
    assert _answer(flow, builder) is None
    command = _say(flow, builder, HAPPY_TEXTS[0], now=1002.0, offset=2)
    assert command is not None
    hangup = flow.command_failed(command.command_id, now=1003.0)
    assert hangup is not None
    assert hangup.action == "hangup"
    assert flow.stage == "hanging_up"
