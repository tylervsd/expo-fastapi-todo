"""Client settings: explicit env mapping, strict bounds, no secret leakage."""

import asyncio
import inspect
import json
import logging
import sys
from datetime import UTC, datetime, timedelta

import pytest

from client import Caller, ClientFlow, ClientSettings, load_client_settings
from telnyx_commands import CommandError, DialIdentity

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
    "Your requested value is one thousand four hundred twenty-five dollars and thirty cents.",
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
    flow.expire(now=now + 5)
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


def test_result_without_hangup_preserves_complete_amount():
    flow = _flow()
    builder = _Builder()
    _drive_happy(flow, builder)
    assert flow.checkpoint_reached is True
    command = flow.expire(now=1000.0 + 180.0)
    assert command is not None
    assert flow.exit_code == 0
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
    assert flow.cleanup_reason == "hangup_unconfirmed"
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
    _drive_happy(flow, builder, texts=HAPPY_TEXTS[:-1])
    assert flow.checkpoint_reached is False
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
    assert flow.cleanup_reason == "hangup_unconfirmed"
    assert flow.exit_code == 1


def test_post_result_conflicting_prompt_is_rejected():
    flow, builder = _flow(), _Builder()
    _drive_happy(flow, builder)
    command = _say(flow, builder, "Your requested value is 17.42.", now=1010, offset=30)
    assert command.action == "hangup"
    assert flow.result == {
        "status": "error",
        "code": "result_unrecognized",
        "stage": "result",
    }


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


# --- Task 4: Caller runtime ownership, early callbacks, bounded cleanup ---


class _Clock:
    def __init__(self, start=2000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _Ids:
    def __init__(self):
        self.count = 0

    def next(self):
        self.count += 1
        return f"caller-evt-{self.count}"


def _cpayload(call="client-call", leg="client-leg", conn="client-app-id", **extra):
    payload = {
        "call_control_id": call,
        "call_leg_id": leg,
        "connection_id": conn,
    }
    payload.update(extra)
    return payload


def _coccurred(offset_seconds=0):
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat()


def _cevent(ids, event_type, payload, *, occurred=None, eid=None):
    return {
        "id": eid or ids.next(),
        "event_type": event_type,
        "occurred_at": occurred if occurred is not None else _coccurred(),
        "payload": payload,
    }


def _cinitiated(
    harness,
    *,
    call="client-call",
    leg="client-leg",
    token=None,
    direction="outgoing",
    occurred=None,
):
    payload = _cpayload(
        call,
        leg,
        harness.settings.connection_id,
        direction=direction,
        client_state=token if token is not None else harness.token(),
        **{"from": harness.settings.from_number, "to": harness.settings.to_number},
    )
    return _cevent(harness.ids, "call.initiated", payload, occurred=occurred)


def _ctranscript(
    harness,
    text,
    *,
    call="client-call",
    leg="client-leg",
    conn=None,
    final=True,
    occurred=None,
):
    payload = _cpayload(
        call,
        leg,
        conn or harness.settings.connection_id,
        transcription_data={"transcript": text, "is_final": final},
    )
    return _cevent(harness.ids, "call.transcription", payload, occurred=occurred)


def _canswered(harness, *, call="client-call", leg="client-leg", conn=None):
    return _cevent(
        harness.ids,
        "call.answered",
        _cpayload(call, leg, conn or harness.settings.connection_id),
    )


def _changup(harness, *, call="client-call", leg="client-leg", conn=None):
    return _cevent(
        harness.ids,
        "call.hangup",
        _cpayload(call, leg, conn or harness.settings.connection_id),
    )


class _CallerHarness:
    def __init__(self, **overrides):
        self.settings = _settings(**overrides)
        self.clock = _Clock()
        self.ids = _Ids()
        self.dial_requests = []
        self.dial_hold = asyncio.Event()
        self.dial_hold.set()
        self.dial_result = DialIdentity("client-call", "client-leg")
        self.dial_error = None
        self.sent = []
        self.send_hold = asyncio.Event()
        self.send_hold.set()
        self.send_errors = {}
        self.caller = Caller(self.settings, self._dial, self._send, clock=self.clock)

    def token(self):
        return self.caller.request.client_state

    async def _dial(self, request):
        self.dial_requests.append(request)
        await self.dial_hold.wait()
        if self.dial_error is not None:
            raise self.dial_error
        return self.dial_result

    async def _send(self, command):
        self.sent.append(command)
        await self.send_hold.wait()
        reason = self.send_errors.get(command.command_id)
        if reason is not None:
            raise CommandError(reason)

    async def drain(self, rounds=30):
        for _ in range(rounds):
            await asyncio.sleep(0)

    async def close(self):
        task = asyncio.create_task(self.caller.close())
        for _ in range(30):
            await asyncio.sleep(0)
        self.clock.advance(20)
        await asyncio.wait_for(task, 5)

    async def start_and_bind(self):
        await self.caller.start()
        await self.drain()
        assert self.caller.identity is not None

    def dtmf_digits(self):
        return [
            json.loads(command.body)["digits"]
            for command in self.sent
            if command.action == "send_dtmf"
        ]


def _run(coro_fn):
    return asyncio.run(coro_fn())


def test_caller_second_start_rejected():
    async def main():
        harness = _CallerHarness()
        await harness.caller.start()
        with pytest.raises(RuntimeError):
            await harness.caller.start()
        await harness.close()

    _run(main)


def test_caller_accept_before_start_ignored():
    async def main():
        harness = _CallerHarness()
        await harness.caller.accept(_canswered(harness))
        assert not harness.caller.done.is_set()
        assert harness.sent == []

    _run(main)


def test_caller_dial_response_identity_drives_navigation():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        assert len(harness.dial_requests) == 1
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        assert harness.dtmf_digits() == ["1"]
        await harness.close()

    _run(main)


def test_caller_early_events_replay_after_dial_response():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        # Non-binding events wait in the pre-identity buffer; nothing sends.
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        assert harness.sent == []
        harness.dial_hold.set()
        await asyncio.wait_for(harness.caller._dial_task, 1)
        await harness.drain()
        assert harness.dtmf_digits() == ["1"]
        assert len(harness.dial_requests) == 1
        await harness.close()

    _run(main)


def test_caller_buffered_hangup_prevents_reopen():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        # Hangup buffered before any binding must win at replay; no reopen.
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_changup(harness))
        harness.dial_hold.set()
        await asyncio.wait_for(harness.caller._dial_task, 1)
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 1
        assert harness.sent == []
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        assert harness.sent == []
        await harness.close()

    _run(main)


def test_caller_answer_gates_dtmf():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        assert harness.sent == []
        await harness.caller.accept(_canswered(harness))
        await harness.drain()
        assert harness.dtmf_digits() == ["1"]
        await harness.close()

    _run(main)


def test_caller_foreign_and_incoming_events_ignored():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        await harness.caller.accept(_canswered(harness))
        await harness.drain()
        before = len(harness.sent)
        # Foreign leg, foreign call, foreign connection.
        await harness.caller.accept(
            _ctranscript(harness, HAPPY_TEXTS[0], leg="other-leg")
        )
        await harness.caller.accept(
            _ctranscript(harness, HAPPY_TEXTS[0], call="other-call")
        )
        await harness.caller.accept(
            _ctranscript(harness, HAPPY_TEXTS[0], conn="other-app")
        )
        # Incoming direction is the answering role, never the caller.
        await harness.caller.accept(_cinitiated(harness, direction="incoming"))
        # Shared session IDs are diagnostic grouping only.
        shared = _ctranscript(harness, HAPPY_TEXTS[0], leg="other-leg")
        shared["payload"]["call_session_id"] = "shared-session"
        await harness.caller.accept(shared)
        await harness.drain()
        assert len(harness.sent) == before
        await harness.close()

    _run(main)


def test_caller_dial_uncertain_then_initiated_cleanup_only():
    async def main():
        harness = _CallerHarness()
        harness.dial_error = CommandError("uncertain")
        await harness.caller.start()
        await harness.drain()
        assert harness.caller.identity is None
        assert not harness.caller.done.is_set()
        await harness.caller.accept(_cinitiated(harness))
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        actions = [command.action for command in harness.sent]
        assert actions == ["hangup"]
        assert harness.caller.flow is not None
        await harness.caller.accept(_changup(harness))
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 1
        assert harness.caller.outcome == "dial_uncertain"
        await harness.close()

    _run(main)


def test_caller_identity_retained_over_late_dial_error():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        harness.send_hold.clear()
        await harness.caller.start()
        await harness.drain()
        await harness.caller.accept(_cinitiated(harness))
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        assert len(harness.sent) == 1  # DTMF in flight, HTTP held
        harness.dial_error = CommandError("uncertain")
        harness.dial_hold.set()
        await asyncio.wait_for(harness.caller._dial_task, 1)
        await harness.drain()
        assert len(harness.dial_requests) == 1
        assert not harness.caller.done.is_set()
        harness.send_hold.set()
        await harness.drain()
        assert harness.dtmf_digits() == ["1"]
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[1]))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[2]))
        await harness.drain()
        assert harness.dtmf_digits() == ["1", "0742#"]
        await harness.close()

    _run(main)


def test_caller_conflicting_dial_response_fails_closed():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        await harness.caller.accept(_cinitiated(harness))
        await harness.drain()
        harness.dial_result = DialIdentity("foreign-call", "foreign-leg")
        harness.dial_hold.set()
        await asyncio.wait_for(harness.caller._dial_task, 1)
        await harness.drain()
        assert harness.caller.outcome == "identity_conflict"
        for command in harness.sent:
            assert (
                json.loads(command.body).get("call_control_id", "client-call")
                is not None
            )
            assert command.call_control_id == "client-call"
        await harness.caller.accept(_changup(harness))
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 1
        await harness.close()

    _run(main)


def test_caller_next_prompt_beats_ack_without_rewind():
    async def main():
        harness = _CallerHarness()
        harness.send_hold.clear()
        await harness.start_and_bind()
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        first = [command for command in harness.sent if command.action == "send_dtmf"]
        assert len(first) == 1
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[1]))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[2]))
        await harness.drain()
        assert harness.dtmf_digits() == ["1", "0742#"]
        harness.send_errors[first[0].command_id] = "uncertain"
        harness.send_hold.set()
        await harness.drain()
        assert harness.caller.flow.stage == "menu"
        assert harness.dtmf_digits() == ["1", "0742#"]
        assert not harness.caller.done.is_set()
        await harness.close()

    _run(main)


def test_caller_current_action_failure_hangs_up():
    async def main():
        harness = _CallerHarness()
        harness.send_hold.clear()
        await harness.start_and_bind()
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        first = harness.sent[0]
        harness.send_errors[first.command_id] = "uncertain"
        harness.send_hold.set()
        await harness.drain()
        actions = [command.action for command in harness.sent]
        assert actions[-1] == "hangup"
        assert harness.caller.flow.stage == "hanging_up"
        await harness.close()

    _run(main)


def test_caller_preidentity_buffer_count_overflow():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        for _ in range(33):
            await harness.caller.accept(
                _ctranscript(harness, "partial chatter", final=False)
            )
        # Overflow holds for late identity instead of finishing immediately.
        assert not harness.caller.done.is_set()
        assert harness.caller.outcome is None
        assert harness.sent == []
        harness.clock.advance(15)
        await harness.caller.tick()
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 1
        assert harness.caller.outcome == "buffer_overflow"
        assert harness.sent == []
        harness.dial_hold.set()
        await harness.drain()
        await harness.close()

    _run(main)


def test_caller_preidentity_buffer_size_overflow():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        for _ in range(17):
            await harness.caller.accept(_ctranscript(harness, "x" * 4000, final=False))
        assert not harness.caller.done.is_set()
        harness.clock.advance(15)
        await harness.caller.tick()
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.outcome == "buffer_overflow"
        harness.dial_hold.set()
        await harness.drain()
        await harness.close()

    _run(main)


def test_caller_event_id_overflow_post_bind():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        await harness.caller.accept(_canswered(harness))
        for _ in range(4097):
            await harness.caller.accept(
                _ctranscript(harness, "partial chatter", final=False)
            )
            if harness.caller.done.is_set():
                break
        assert harness.caller.flow.outcome == "event_overflow"
        await harness.close()

    _run(main)


def test_caller_malformed_accept_raises_without_mutation():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        with pytest.raises(ValueError):
            await harness.caller.accept({"no": "envelope"})
        with pytest.raises(ValueError):
            await harness.caller.accept(
                _cevent(harness.ids, "call.answered", {"bad": "payload"})
            )
        with pytest.raises(ValueError):
            await harness.caller.accept("not-a-dict")
        assert harness.sent == []
        assert not harness.caller.done.is_set()
        await harness.close()

    _run(main)


def test_caller_naive_timestamp_rejected():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        naive = _cevent(
            harness.ids, "call.answered", _cpayload(), occurred="2026-09-21T12:00:00"
        )
        with pytest.raises(ValueError):
            await harness.caller.accept(naive)
        assert not harness.caller.done.is_set()
        await harness.close()

    _run(main)


def test_caller_unknown_event_type_ignored():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        await harness.caller.accept(
            _cevent(harness.ids, "call.frobnicate", _cpayload())
        )
        assert harness.sent == []
        assert not harness.caller.done.is_set()
        await harness.close()

    _run(main)


def test_caller_close_during_dial_is_unconfirmed():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        task = asyncio.create_task(harness.caller.close())
        await harness.drain()
        harness.clock.advance(20)
        await asyncio.wait_for(task, 2)
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 1
        assert harness.caller.outcome == "hangup_unconfirmed"
        harness.dial_hold.set()
        await harness.drain()
        assert harness.sent == []

    _run(main)


def test_caller_close_after_rejection_keeps_outcome():
    async def main():
        harness = _CallerHarness()
        harness.dial_error = CommandError("rejected")
        await harness.caller.start()
        await harness.drain()
        assert harness.caller.outcome == "dial_rejected"
        await harness.close()
        assert harness.caller.outcome == "dial_rejected"
        assert harness.caller.exit_code == 1
        assert harness.sent == []

    _run(main)


def test_caller_close_keeps_handling_initiated():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        task = asyncio.create_task(harness.caller.close())
        await harness.drain()
        await harness.caller.accept(_cinitiated(harness))
        await harness.drain()
        actions = [command.action for command in harness.sent]
        assert actions == ["hangup"]
        await harness.caller.accept(_changup(harness))
        await asyncio.wait_for(task, 2)
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 1

    _run(main)


def test_caller_has_no_answering_role_reference():
    assert "fixture" not in inspect.getsource(Caller).lower()
    assert not hasattr(sys.modules["client"], "fixture")


def test_caller_logs_are_sanitized(caplog):
    async def main():
        harness = _CallerHarness(
            connection_id="conn-sentinel-9z9z",
            from_number="+19998887777",
            to_number="+19998886666",
            synthetic_id="987654321",
        )
        harness.dial_result = DialIdentity("call-sentinel-aa", "leg-sentinel-bb")
        with caplog.at_level(logging.INFO, logger="ivr.client"):
            await harness.start_and_bind()
            await harness.caller.accept(
                _canswered(
                    harness,
                    call="call-sentinel-aa",
                    leg="leg-sentinel-bb",
                    conn="conn-sentinel-9z9z",
                )
            )
            readback = (
                "You entered nine eight seven six five four three two one. "
                "Press one if correct."
            )
            await harness.caller.accept(
                _ctranscript(
                    harness,
                    readback,
                    call="call-sentinel-aa",
                    leg="leg-sentinel-bb",
                    conn="conn-sentinel-9z9z",
                )
            )
            await harness.drain()
            await harness.close()

    _run(main)
    for sentinel in (
        "conn-sentinel-9z9z",
        "+19998887777",
        "+19998886666",
        "call-sentinel-aa",
        "leg-sentinel-bb",
        "987654321",
        "test-api-key",
    ):
        assert sentinel not in caplog.text


def test_caller_overall_deadline_without_flow():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        harness.clock.advance(180)
        await harness.caller.tick()
        # Dial still in flight: hold for late identity, do not finish yet.
        assert not harness.caller.done.is_set()
        harness.clock.advance(15)
        await harness.caller.tick()
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.outcome == "overall_timeout"
        assert harness.caller.exit_code == 1
        harness.dial_hold.set()
        await harness.drain()
        await harness.close()

    _run(main)


def test_caller_hangup_before_result_is_nonzero():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        count = len(harness.sent)
        assert count == 1
        await harness.caller.accept(_changup(harness))
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 1
        assert harness.caller.outcome == "early_hangup"
        assert len(harness.sent) == count
        await harness.close()

    _run(main)


def test_caller_full_happy_path_checkpoint_then_hangup():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        await harness.caller.accept(_canswered(harness))
        for text in HAPPY_TEXTS:
            await harness.caller.accept(_ctranscript(harness, text))
        await harness.drain()
        assert harness.dtmf_digits() == ["1", "0742#", "1", "000123456#", "1"]
        assert harness.caller.flow.checkpoint_reached
        assert not harness.caller.done.is_set()
        await harness.caller.accept(_changup(harness))
        harness.clock.advance(5)
        await harness.caller.tick()
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 0
        assert harness.caller.outcome == "completed"
        await harness.close()

    _run(main)


def test_caller_completed_cannot_restart():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_changup(harness))
        await harness.drain()
        assert harness.caller.done.is_set()
        with pytest.raises(RuntimeError):
            await harness.caller.start()
        await harness.close()

    _run(main)


def test_caller_malformed_transcription_raises_without_dedup():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        conn = harness.settings.connection_id

        def bad_event(transcription_data, *, eid=None):
            payload = _cpayload(
                "client-call",
                "client-leg",
                conn,
                transcription_data=transcription_data,
            )
            return _cevent(harness.ids, "call.transcription", payload, eid=eid)

        cases = [
            "not-a-dict",
            {"transcript": 742, "is_final": True},
            {"transcript": "hello", "is_final": 0},
            {"transcript": "hello", "is_final": 1},
            {"transcript": "x" * 4097, "is_final": True},
            {"transcript": "hello"},
        ]
        for data in cases:
            event = bad_event(data)
            with pytest.raises(ValueError):
                await harness.caller.accept(event)
            # Identical repeat still raises: malformed events are never deduped.
            with pytest.raises(ValueError):
                await harness.caller.accept(event)
            assert event["id"] not in harness.caller._seen
            assert event["id"] not in harness.caller.flow._seen
        assert harness.sent == []
        assert not harness.caller.done.is_set()
        # A valid follow-up still navigates: nothing was poisoned.
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        assert harness.dtmf_digits() == ["1"]
        await harness.close()

    _run(main)


def test_caller_preidentity_malformed_transcription_raises():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        payload = _cpayload(
            "client-call",
            "client-leg",
            harness.settings.connection_id,
            transcription_data={"transcript": "hi", "is_final": 0},
        )
        with pytest.raises(ValueError):
            await harness.caller.accept(
                _cevent(harness.ids, "call.transcription", payload)
            )
        assert not harness.caller.done.is_set()
        # Late identity still binds after the malformed event.
        await harness.caller.accept(_cinitiated(harness))
        assert harness.caller.identity is not None
        await harness.close()

    _run(main)


def test_caller_preidentity_timeout_still_binds_late_initiated():
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        token = harness.token()
        harness.clock.advance(30)
        await harness.caller.tick()
        assert not harness.caller.done.is_set()
        await harness.caller.accept(_cinitiated(harness, token=token))
        await harness.drain()
        assert [command.action for command in harness.sent] == ["hangup"]
        await harness.caller.accept(_changup(harness))
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 1
        assert harness.caller.outcome == "stage_timeout"
        harness.dial_hold.set()
        await harness.drain()
        await harness.close()

    _run(main)


def test_caller_uncertain_budget_expiry_finalizes():
    async def main():
        harness = _CallerHarness()
        harness.dial_error = CommandError("uncertain")
        await harness.caller.start()
        await harness.drain()
        assert harness.caller.identity is None
        assert not harness.caller.done.is_set()
        harness.clock.advance(15)
        await harness.caller.tick()
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.outcome == "dial_uncertain"
        assert harness.caller.exit_code == 1
        await harness.close()

    _run(main)


def test_caller_done_clears_sensitive_state_and_drains():
    async def main():
        harness = _CallerHarness()
        harness.send_hold.clear()
        await harness.start_and_bind()
        token = harness.token()
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[0]))
        await harness.drain()
        assert len(harness.sent) == 1  # DTMF in flight, HTTP held.
        await harness.caller.accept(_changup(harness))
        await harness.drain()
        assert harness.caller.done.is_set()
        assert harness.caller.exit_code == 1
        assert harness.caller.outcome == "early_hangup"
        assert harness.caller.request is None
        assert harness.caller.identity is None
        assert harness.caller._run_token is None
        assert harness.caller._seen == set()
        assert harness.caller._buffer == []
        flow = harness.caller.flow
        assert flow.stage == "ended"
        assert flow._seen == set()
        assert flow._segments == []
        assert flow.pending is None
        assert flow.identity is None
        assert harness.caller.tasks == {}
        assert token not in (harness.caller.outcome or "")
        harness.send_hold.set()
        await harness.drain()
        await harness.close()
        assert harness.caller.done.is_set()
        assert harness.caller.outcome == "early_hangup"

    _run(main)


def test_caller_close_stalled_clock_wall_fallback(monkeypatch):
    async def main():
        harness = _CallerHarness()
        harness.dial_hold.clear()
        await harness.caller.start()
        await harness.drain()
        real_sleep = asyncio.sleep
        calls = []

        async def fast_sleep(delay=0):
            calls.append(delay)
            await real_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)
        await asyncio.wait_for(harness.caller.close(), 10)
        assert harness.caller.done.is_set()
        assert harness.caller.outcome == "hangup_unconfirmed"
        # The stalled clock never trips the deadline; the iteration cap ends it.
        assert sum(1 for delay in calls if delay == 0.01) >= 1500
        harness.dial_hold.set()
        await harness.drain()

    _run(main)


def test_caller_finish_drains_canceled_dial_before_done():
    async def main():
        harness = _CallerHarness()
        exited = asyncio.Event()

        async def slow_dial(request):
            harness.dial_requests.append(request)
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                await asyncio.sleep(0.05)
                exited.set()
                raise
            return harness.dial_result

        harness.caller.dial = slow_dial
        await harness.caller.start()
        await asyncio.sleep(0)
        assert harness.caller._dial_task is not None
        harness.caller._finish("shutdown", 1)
        assert not harness.caller.done.is_set()
        await asyncio.wait_for(exited.wait(), 5)
        await asyncio.wait_for(harness.caller.done.wait(), 5)
        assert harness.caller.done.is_set()

    _run(main)


def test_transcription_track_setting(monkeypatch):
    from dataclasses import replace

    from client import _dial_fields

    settings = _settings()
    assert (
        _dial_fields(settings)["transcription_config"]["transcription_tracks"]
        == "inbound"
    )
    assert (
        _dial_fields(replace(settings, transcription_track="inbound"))[
            "transcription_config"
        ]["transcription_tracks"]
        == "inbound"
    )
    with pytest.raises(RuntimeError):
        replace(settings, transcription_track="both")


def test_parser_diagnostics_do_not_log_speech(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="ivr.client")
    flow, builder = _flow(), _Builder()
    _answer(flow, builder)
    flow.handle(
        builder.event(
            "call.transcription", offset=2, transcript="SECRET_SENTINEL", is_final=True
        ),
        now=1002,
    )
    assert flow.parser_status == "pending"
    assert not caplog.records
    assert "SECRET_SENTINEL" not in caplog.text


def test_dial_uses_telnyx_inbound_without_google_options():
    from client import ClientSettings, _dial_fields

    config = _dial_fields(ClientSettings("key", "app", "+12025550101", "+12025550102"))[
        "transcription_config"
    ]
    assert config == {
        "transcription_engine": "Telnyx",
        "transcription_engine_config": {
            "transcription_engine": "Telnyx",
            "language": "en",
        },
        "transcription_tracks": "inbound",
    }


def test_result_final_can_follow_hangup_with_bounded_wait():
    from client import ClientFlow, ClientSettings
    from telnyx_commands import DialIdentity

    def flow():
        f = ClientFlow(
            ClientSettings("key", "app", "+12025550101", "+12025550102"),
            DialIdentity("call", "leg"),
            started_at=0,
            now=0,
        )
        f.stage = "result"
        return f

    f = flow()
    assert f.handle({"id": "hang", "event_type": "call.hangup"}, now=1) is None
    assert f.stage == "result"
    assert (
        f.handle(
            {
                "id": "final",
                "event_type": "call.transcription",
                "occurred_at": "2026-09-22T02:00:00+00:00",
                "payload": {
                    "transcription_data": {
                        "is_final": True,
                        "transcript": "Your requested value is 17.42.",
                    }
                },
            },
            now=2,
        )
        is None
    )
    assert f.result is None
    f.expire(now=6)
    assert (f.stage, f.outcome, f.exit_code) == ("ended", "completed", 0)
    f = flow()
    f.handle({"id": "hang", "event_type": "call.hangup"}, now=1)
    f.handle({"id": "duplicate-hang", "event_type": "call.hangup"}, now=4)
    assert f.expire(now=6) is None
    assert (f.stage, f.outcome, f.exit_code) == ("ended", "result_unrecognized", 1)


def test_caller_late_result_preserves_ownership_until_final():
    async def main():
        harness = _CallerHarness()
        await harness.start_and_bind()
        await harness.caller.accept(_canswered(harness))
        for text in HAPPY_TEXTS[:-1]:
            await harness.caller.accept(_ctranscript(harness, text))
        await harness.drain()
        await harness.caller.accept(_changup(harness))
        assert not harness.caller.done.is_set()
        await harness.caller.accept(
            _ctranscript(harness, HAPPY_TEXTS[-1], call="other-call")
        )
        assert not harness.caller.done.is_set()
        await harness.caller.accept(_ctranscript(harness, HAPPY_TEXTS[-1]))
        assert not harness.caller.done.is_set()
        harness.clock.advance(5)
        await harness.caller.tick()
        await harness.drain()
        assert harness.caller.outcome == "completed"
        assert harness.caller.exit_code == 0
        assert harness.caller.result["value"] == "1425.30"
        assert harness.caller.identity is None
        await harness.close()

    _run(main)


def test_value_finalization_window_and_snapshot():
    flow, events = _flow(), _Builder()
    _, now, offset = _drive_happy(flow, events)
    assert flow.result is None
    flow.handle(events.event("call.hangup", offset=offset), now=now)
    flow.expire(now=now + 4.999)
    assert flow.result is None
    flow.expire(now=now + 5)
    assert flow.result == {"status": "success", "value": "1425.30", "currency": "USD"}
    saved = flow.result.copy()
    flow.handle(events.event("call.hangup", offset=offset + 1), now=now + 6)
    assert flow.result == saved


@pytest.mark.parametrize("arrival", [1179.999, 1180.0])
def test_result_window_capped_by_overall_deadline(arrival):
    flow, events = _flow(), _Builder()
    flow.stage = "result"
    flow.stage_started_at = 1170
    flow.handle(events.event("call.hangup", offset=178), now=1178)
    _say(flow, events, "Your requested value is 0.00.", now=arrival, offset=179)
    flow.expire(now=1180)
    assert flow.stage == "ended"
    if arrival < 1180:
        assert flow.result == {"status": "success", "value": "0.00", "currency": "USD"}
    else:
        assert flow.result == {
            "status": "error",
            "code": "result_unrecognized",
            "stage": "result",
        }


def test_result_conflict_after_hangup_rejects_candidate():
    flow, events = _flow(), _Builder()
    _, now, offset = _drive_happy(flow, events)
    flow.handle(events.event("call.hangup", offset=offset), now=now)
    _say(flow, events, "Your requested value is 17.42.", now=now + 1, offset=offset + 1)
    flow.expire(now=now + 5)
    assert flow.result == {
        "status": "error",
        "code": "result_unrecognized",
        "stage": "result",
    }


def test_cleanup_failure_preserves_original_decision():
    flow, events = _flow(), _Builder()
    _drive_happy(flow, events)
    hangup = flow.expire(now=1180)
    flow.command_failed(hangup.command_id, now=1181)
    assert flow.result == {"status": "success", "value": "1425.30", "currency": "USD"}
    assert flow.exit_code == 0
    flow = _flow()
    flow.stage = "challenge"
    hangup = flow.stop("challenge_unrecognized", now=1001)
    flow.expire(now=1016)
    assert flow.result == {
        "status": "error",
        "code": "challenge_unrecognized",
        "stage": "challenge",
    }


def test_public_error_mapping():
    from client import error_result

    assert error_result("dial_rejected", "dialing")["code"] == "provider_failure"
    assert error_result("transcript_order", "result")["code"] == "protocol_error"
    assert error_result("unexpected-secret", "ended") == {
        "status": "error",
        "code": "internal_error",
        "stage": "startup",
    }


@pytest.mark.parametrize(
    ("raw", "expected"), [(None, False), ("0", False), ("1", True)]
)
def test_debug_setting(monkeypatch, raw, expected):
    monkeypatch.setenv("TELNYX_API_KEY", "key")
    monkeypatch.setenv("IVR_CLIENT_CONNECTION_ID", "app")
    monkeypatch.setenv("IVR_CLIENT_FROM_NUMBER", "+12025550101")
    monkeypatch.setenv("IVR_CLIENT_TO_NUMBER", "+12025550102")
    monkeypatch.delenv("IVR_CLIENT_DEBUG_TRANSCRIPTS", raising=False)
    if raw is not None:
        monkeypatch.setenv("IVR_CLIENT_DEBUG_TRANSCRIPTS", raw)
    assert load_client_settings().debug_transcripts is expected


@pytest.mark.parametrize("raw", ["", "true", "2"])
def test_invalid_debug_setting(monkeypatch, raw):
    for key, value in VALID.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("IVR_CLIENT_DEBUG_TRANSCRIPTS", raw)
    with pytest.raises(RuntimeError, match="Invalid client configuration"):
        load_client_settings()


@pytest.mark.parametrize("debug", [False, True])
def test_correlated_trace_and_debug_privacy(caplog, debug):
    async def exercise():
        harness = _CallerHarness(debug_transcripts=debug)
        await harness.start_and_bind()
        await harness.caller.accept(_canswered(harness))
        await harness.caller.accept(
            _ctranscript(harness, "SECRET_SENTINEL zero seven four two 000123456")
        )
        await harness.caller.accept(_changup(harness))
        await harness.drain()
        records = [
            json.loads(r.getMessage()) for r in caplog.records if r.name == "ivr.client"
        ]
        assert all("run_id" in r and "elapsed" in r for r in records)
        transitions = [r for r in records if "previous_stage" in r]
        assert any(r["stage"] == "welcome" for r in transitions)
        bound = [r for r in records if r.get("call_ref")]
        assert bound and all(
            len(r["call_ref"]) == 12 and len(r["leg_ref"]) == 12 for r in bound
        )
        assert any("final" in r for r in records) is debug
        assert any(r.get("parser") == "pending" for r in records) is debug
        for secret in (
            "SECRET_SENTINEL",
            "zero seven four two",
            "000123456",
            "client-call",
            "client-leg",
            "test-api-key",
        ):
            assert secret not in caplog.text
        await harness.close()

    _run(exercise)


def test_internal_dial_failure_remains_distinct_from_provider_failure():
    async def exercise():
        harness = _CallerHarness()

        async def broken(request):
            raise RuntimeError("private-message")

        harness.caller.dial = broken
        await harness.caller.start()
        await harness.drain()
        harness.clock.advance(15)
        await harness.caller.tick()
        await harness.drain()
        assert harness.caller.result == {
            "status": "error",
            "code": "internal_error",
            "stage": "dialing",
        }

    _run(exercise)


@pytest.mark.parametrize("partial", [False, True])
def test_split_result_cents_after_hangup(partial):
    flow, events = _flow(), _Builder()
    flow.stage = "result"
    _say(flow, events, "Your requested value is one dollar", now=1001, offset=1)
    flow.handle(events.event("call.hangup", offset=2), now=1002)
    _say(flow, events, "and five cents.", now=1003, offset=3, final=not partial)
    flow.expire(now=1007)
    assert flow.result == (
        {"status": "error", "code": "result_unrecognized", "stage": "result"}
        if partial
        else {"status": "success", "value": "1.05", "currency": "USD"}
    )
