import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from fixture import (
    Fixture,
    Flow,
    Settings,
    digit_words,
    integer_words,
    load_settings,
    new_challenge,
    result_prompt,
)
from telnyx_commands import CommandError


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


def complete(flow, kind="call.gather.ended", **fields):
    return flow.handle(
        kind, {"client_state": flow.pending.client_state, **fields}, now=1
    )


def flow_at(stage, **changes):
    flow = Flow(settings(**changes), "call", "leg", now=0, challenge="0742")
    if stage == "answering":
        return flow
    complete(flow, "call.answered")
    for digits in ("1", "0742#", "1", "000123456#", "1"):
        if flow.stage == stage:
            return flow
        complete(flow, status="valid", digits=digits)
    return flow


def test_manual_protocol_and_final_completion():
    flow = flow_at("result")
    assert flow.pending.action == "speak"
    assert flow.outcome is None
    assert complete(flow, "call.speak.started") is None
    assert (
        flow.handle(
            "call.speak.ended", {"client_state": "old", "status": "completed"}, now=2
        )
        is None
    )
    complete(flow, "call.speak.ended", status="completed")
    assert flow.stage == "hanging_up"
    assert flow.pending.action == "hangup"
    assert flow.outcome == "result_spoken"
    flow.handle("call.hangup", {}, now=2)
    assert flow.stage == "ended"
    assert flow.pending is None and flow.challenge == ""
    assert flow.settings is None
    assert flow.handle("call.answered", {}, now=3) is None


@pytest.mark.parametrize(
    "stage,length,valid",
    [
        ("welcome", 1, "0123456789*#"),
        ("challenge", 5, "0123456789#"),
        ("identifier", 10, "0123456789#"),
    ],
)
def test_gather_contract(stage, length, valid):
    flow = flow_at(stage)
    body = json.loads(flow.pending.body)
    assert {
        k: body[k]
        for k in (
            "minimum_digits",
            "maximum_digits",
            "valid_digits",
            "terminating_digit",
            "maximum_tries",
            "timeout_millis",
            "inter_digit_timeout_millis",
        )
    } == {
        "minimum_digits": length,
        "maximum_digits": length,
        "valid_digits": valid,
        "terminating_digit": "",
        "maximum_tries": 1,
        "timeout_millis": 20000,
        "inter_digit_timeout_millis": 5000,
    }
    assert body["service_level"] == "basic" and body["language"] == "en-US"
    if stage == "challenge":
        assert "zero seven four two" in body["payload"]


@pytest.mark.parametrize(
    "digits", ["742#", "0742", "#0742", "074##", "07420", "０７４２#", 742, ""]
)
def test_challenge_cannot_be_normalized(digits):
    flow = flow_at("challenge")
    old = flow.pending
    complete(flow, status="valid", digits=digits)
    assert flow.stage == "challenge" and flow.attempt == 2
    assert flow.challenge == "0742"
    assert flow.pending.command_id != old.command_id
    assert "try again" in json.loads(flow.pending.body)["payload"]
    assert (
        flow.handle(
            "call.gather.ended",
            {"client_state": old.client_state, "digits": "0742#", "status": "valid"},
            now=2,
        )
        is None
    )
    complete(flow, status="valid", digits="0742#")
    assert flow.stage == "menu" and flow.attempt == 1


@pytest.mark.parametrize(
    "stage,digits",
    [
        ("welcome", "2"),
        ("challenge", "9999#"),
        ("identifier", "999999999#"),
        ("confirmation", "2"),
    ],
)
def test_two_attempts_then_spoken_failure(stage, digits):
    flow = flow_at(stage)
    for _ in range(2):
        complete(flow, status="valid", digits=digits)
    assert flow.stage == "failure"
    assert "could not verify" in json.loads(flow.pending.body)["payload"]
    complete(flow, "call.speak.ended", status="completed")
    assert flow.stage == "hanging_up" and flow.outcome != "result_spoken"


@pytest.mark.parametrize("status", ["invalid", "timeout"])
def test_status_is_not_ignored(status):
    flow = flow_at("challenge")
    complete(flow, status=status, digits="0742#")
    assert flow.stage == "challenge" and flow.attempt == 2


@pytest.mark.parametrize("status", ["cancelled", "cancelled_amd", "unexpected"])
def test_cancelled_gather_is_service_failure(status):
    flow = flow_at("challenge")
    complete(flow, status=status)
    assert flow.stage == "failure"


@pytest.mark.parametrize(
    "stage",
    [
        "answering",
        "welcome",
        "challenge",
        "menu",
        "identifier",
        "confirmation",
        "result",
        "failure",
        "hanging_up",
    ],
)
def test_remote_hangup_everywhere(stage):
    flow = flow_at("result" if stage in ("failure", "hanging_up") else stage)
    if stage == "failure":
        flow.command_failed(flow.pending.command_id, now=2)
    if stage == "hanging_up":
        complete(flow, "call.speak.ended", status="completed")
    flow.handle("call.hangup", {}, now=3)
    assert flow.stage == "ended" and flow.pending is None and flow.challenge == ""


def test_business_and_individual_digits():
    flow = flow_at("menu")
    pending = flow.pending
    assert complete(flow, "call.dtmf.received", digit="1") is None
    assert flow.pending is pending
    complete(flow, status="valid", digits="2")
    assert flow.stage == "failure"
    assert (
        "Business requests are not supported"
        in json.loads(flow.pending.body)["payload"]
    )


@pytest.mark.parametrize("status", ["call_hangup", "cancelled_amd", "unknown"])
def test_interrupted_result_is_not_success(status):
    flow = flow_at("result")
    complete(flow, "call.speak.ended", status=status)
    assert flow.stage in ("ended", "hanging_up")
    assert flow.outcome != "result_spoken"


@pytest.mark.parametrize(
    "stage,deadline,next_stage",
    [
        ("answering", 20, "hanging_up"),
        ("challenge", 51, "failure"),
        ("result", 31, "hanging_up"),
    ],
)
def test_deadlines(stage, deadline, next_stage):
    flow = flow_at(stage)
    assert flow.expire(now=deadline - 0.01) is None
    flow.expire(now=deadline)
    assert flow.stage == next_stage and flow.outcome != "result_spoken"


def test_overall_deadline_and_cleanup_bound():
    flow = flow_at("result")
    flow.expire(now=300)
    assert flow.stage == "hanging_up"
    command = flow.pending
    assert flow.expire(now=301) is None
    assert flow.pending is command
    flow.expire(now=315)
    assert flow.stage == "ended" and flow.outcome == "hangup_unconfirmed"


def test_failure_speech_does_not_recurse():
    flow = flow_at("challenge")
    old = flow.pending.command_id
    flow.command_failed(old, now=2)
    assert flow.stage == "failure"
    assert flow.command_failed(old, now=3) is None
    flow.command_failed(flow.pending.command_id, now=3)
    assert flow.stage == "hanging_up"
    flow.command_failed(flow.pending.command_id, now=4)
    assert flow.stage == "hanging_up"


def test_zero_challenge_and_attempt_setting():
    flow = Flow(settings(max_attempts=1), "call", "leg", now=0, challenge="0000")
    complete(flow, "call.answered")
    complete(flow, status="valid", digits="1")
    complete(flow, status="valid", digits="0000#")
    assert flow.stage == "menu"
    complete(flow, status="valid", digits="3")
    assert flow.stage == "failure"


def event(kind="call.initiated", *, call="call", leg="leg", **payload):
    return {
        "id": str(uuid4()),
        "event_type": kind,
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": {
            "call_control_id": call,
            "call_leg_id": leg,
            "connection_id": "app",
            "direction": "incoming",
            "state": "parked",
            **payload,
        },
    }


def runtime(send, clock=lambda: 0):
    return Fixture(
        settings(),
        send,
        started_at=datetime.now(UTC) - timedelta(seconds=1),
        clock=clock,
    )


async def runtime_complete(ivr, kind="call.gather.ended", **payload):
    data = event(kind, client_state=ivr.active.pending.client_state, **payload)
    await asyncio.gather(ivr.accept(data), ivr.accept(data))
    await ivr.drain()


def test_runtime_duplicate_full_flow_and_tombstone():
    async def exercise():
        sent = []

        async def send(command):
            sent.append(command)

        ivr = runtime(send)
        data = event()
        await asyncio.gather(ivr.accept(data), ivr.accept(data))
        await ivr.drain()
        assert [c.action for c in sent] == ["answer"]
        await runtime_complete(ivr, "call.answered")
        code = ivr.active.challenge
        for digits in ("1", code + "#", "1", "000123456#", "1"):
            await runtime_complete(ivr, status="valid", digits=digits)
        await runtime_complete(ivr, "call.speak.ended", status="completed")
        assert [c.action for c in sent] == ["answer"] + ["gather_using_speak"] * 5 + [
            "speak",
            "hangup",
        ]
        await ivr.accept(event("call.hangup"))
        await ivr.accept(event())
        await ivr.drain()
        assert ivr.active is None and "call" in ivr.tombstones
        assert len(sent) == 8
        await ivr.close()

    asyncio.run(exercise())


def test_reordered_and_old_admission():
    async def exercise():
        async def forbidden(command):
            pytest.fail("Must not control this call")

        ivr = runtime(forbidden)
        await ivr.accept(event("call.hangup"))
        await ivr.accept(event())
        old = event(call="old")
        old["occurred_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        await ivr.accept(old)
        await ivr.accept(event(call="other-app", connection_id="other"))
        await ivr.accept(event(call="out", direction="outgoing"))
        future = event(call="future")
        future["occurred_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        await ivr.accept(future)
        await ivr.accept(event("call.answered", call="unknown"))
        await ivr.drain()
        assert ivr.active is None
        await ivr.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "kind,changes",
    [
        ("call.initiated", {"call_control_id": ""}),
        ("call.initiated", {"call_leg_id": 1}),
        ("call.initiated", {"connection_id": "x" * 257}),
        ("call.gather.ended", {"status": "valid", "digits": 742}),
        ("call.gather.ended", {"status": "valid", "digits": "1" * 129}),
        ("call.gather.ended", {"status": "valid"}),
    ],
)
def test_runtime_malformed_payload(kind, changes):
    async def exercise():
        async def send(command):
            pytest.fail("Malformed event sent a command")

        ivr = runtime(send)
        with pytest.raises(ValueError, match="^Invalid call event$"):
            await ivr.accept(event(kind, **changes))
        await ivr.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("finish", ["answer", "hangup"])
@pytest.mark.parametrize("late_error", [True, False])
def test_completion_wins_over_late_http_response(finish, late_error):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        sent = []

        async def send(command):
            sent.append(command)
            if command.action == "answer":
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()  # model a response already on the wire
                if late_error:
                    raise CommandError("uncertain")

        ivr = runtime(send)
        await ivr.accept(event())
        await entered.wait()
        if finish == "answer":
            await ivr.accept(
                event("call.answered", client_state=ivr.active.pending.client_state)
            )
        else:
            await ivr.accept(event("call.hangup"))
        release.set()
        await ivr.drain()
        assert not any(c.action == "speak" for c in sent)
        assert (ivr.active.stage if ivr.active else None) == (
            "welcome" if finish == "answer" else None
        )
        await ivr.accept(event("call.hangup"))
        await ivr.close()

    asyncio.run(exercise())


def test_busy_deadlines_and_next_call():
    async def exercise():
        now, sent = [0], []

        async def send(command):
            sent.append(command)

        ivr = runtime(send, lambda: now[0])
        await ivr.accept(event())
        await ivr.drain()
        await runtime_complete(ivr, "call.answered")
        first = ivr.active
        busy = event(call="busy", leg="busy-leg")
        await asyncio.gather(ivr.accept(busy), ivr.accept(busy))
        await ivr.drain()
        assert ivr.active is first
        assert [(c.call_control_id, c.action) for c in sent][-1] == ("busy", "hangup")
        now[0] = 50
        await ivr.tick()
        await ivr.drain()
        assert ivr.active.stage == "failure"
        now[0] = 80
        await ivr.tick()
        await ivr.drain()
        assert ivr.active.stage == "hanging_up"
        now[0] = 95
        await ivr.tick()
        assert ivr.active is None
        assert first.outcome == "hangup_unconfirmed"
        await ivr.accept(event(call="fresh", leg="fresh-leg"))
        await ivr.drain()
        assert ivr.active.call_control_id == "fresh"
        await ivr.accept(event("call.hangup", call="fresh", leg="fresh-leg"))
        await ivr.close()
        assert not ivr.tasks

    asyncio.run(exercise())


def test_runtime_caps_and_wrong_leg():
    async def exercise():
        sent = []

        async def send(command):
            sent.append(command)

        ivr = runtime(send)
        await ivr.accept(event())
        await ivr.drain()
        await runtime_complete(ivr, "call.answered")
        await ivr.accept(event("call.hangup", leg="wrong"))
        assert ivr.active.stage == "welcome"
        ivr.seen = {str(n) for n in range(4096)}
        await ivr.accept(
            event(
                "call.gather.ended",
                client_state=ivr.active.pending.client_state,
                status="valid",
                digits="1",
            )
        )
        await ivr.drain()
        assert ivr.active.stage == "failure"
        await runtime_complete(ivr, "call.speak.ended", status="completed")
        await ivr.accept(event("call.hangup"))
        ivr.tombstones.update(str(n) for n in range(1000))
        count = len(sent)
        await ivr.accept(event(call="capacity"))
        await ivr.drain()
        assert len(sent) == count and ivr.active is None
        await ivr.close()

    asyncio.run(exercise())


def test_shutdown_cancels_blocked_send_and_attempts_hangup():
    async def exercise():
        entered = asyncio.Event()
        sent = []

        async def send(command):
            sent.append(command)
            if command.action == "answer":
                entered.set()
                await asyncio.Event().wait()

        ivr = runtime(send)
        await ivr.accept(event())
        await entered.wait()
        await asyncio.wait_for(ivr.close(), 1)
        assert [c.action for c in sent] == ["answer", "hangup"]
        assert not ivr.tasks and ivr.active is None
        await ivr.accept(event(call="after-close"))
        assert len(sent) == 2

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "stage,kind,now,payload",
    [
        ("result", "call.speak.ended", 300, {"status": "completed"}),
        ("challenge", "call.gather.ended", 51, {"status": "valid", "digits": "0742#"}),
    ],
)
def test_completion_cannot_beat_an_expired_deadline(stage, kind, now, payload):
    flow = flow_at(stage)
    flow.handle(kind, {"client_state": flow.pending.client_state, **payload}, now=now)
    assert flow.outcome in ("call_timeout", "completion_timeout")
    assert flow.stage in ("hanging_up", "failure")


def test_flow_speaks_configured_amount():
    flow = flow_at("result", result_amount="27.05")
    assert json.loads(flow.pending.body)["payload"] == (
        "Your requested value is twenty-seven dollars and five cents."
    )


@pytest.mark.parametrize("answered", [False, True])
def test_runtime_sender_failure_is_bounded_and_private(answered, caplog):
    async def exercise():
        sent = []
        now = [0]

        async def send(command):
            sent.append(command)
            if not answered or command.action != "answer":
                raise RuntimeError("SECRET_PROVIDER_BODY")

        ivr = runtime(send, lambda: now[0])
        await ivr.accept(event())
        await ivr.drain()
        if answered:
            await runtime_complete(ivr, "call.answered")
        assert [c.action for c in sent] == (
            ["answer", "gather_using_speak", "speak", "hangup"]
            if answered
            else ["answer", "hangup"]
        )
        assert ivr.active.stage == "hanging_up"
        now[0] = 15
        await ivr.tick()
        assert ivr.active is None
        await ivr.close()
        assert not ivr.tasks
        assert "SECRET_PROVIDER_BODY" not in caplog.text

    asyncio.run(exercise())


@pytest.mark.parametrize("scenario", ["", "NORMAL", "unknown", None, []])
def test_invalid_scenario(scenario):
    with pytest.raises(RuntimeError, match="^Invalid fixture configuration$"):
        settings(scenario=scenario)


@pytest.mark.parametrize("override", ["", "0742"])
def test_leading_zero_scenario(override):
    flow = Flow(
        settings(scenario="leading_zero", challenge_override=override),
        "call",
        "leg",
        now=0,
    )
    assert flow.challenge == "0742"
    with pytest.raises(RuntimeError, match="Invalid fixture configuration"):
        settings(scenario="leading_zero", challenge_override="1234")


@pytest.mark.parametrize(
    "scenario",
    [
        "normal",
        "leading_zero",
        "rejected_id",
        "silent_stage",
        "unsupported_result",
        "early_hangup",
    ],
)
def test_scenario_environment(monkeypatch, scenario):
    monkeypatch.setenv("TELNYX_API_KEY", "test-only")
    monkeypatch.setenv("IVR_CONNECTION_ID", "app")
    monkeypatch.setenv("IVR_SCENARIO", scenario)
    monkeypatch.delenv("IVR_CHALLENGE_OVERRIDE", raising=False)
    assert load_settings().scenario == scenario


def test_rejected_id_scenario():
    flow = flow_at("identifier", scenario="rejected_id")
    command = complete(flow, status="valid", digits="000123456#")
    assert flow.stage == "failure"
    assert (
        json.loads(command.body)["payload"]
        == "We could not verify your entry. Goodbye."
    )
    assert complete(flow, "call.speak.ended", status="completed").action == "hangup"


def test_unsupported_result_scenario():
    flow = flow_at("result", scenario="unsupported_result")
    assert (
        json.loads(flow.pending.body)["payload"]
        == "Your requested value is unavailable."
    )
    assert complete(flow, "call.speak.ended", status="completed").action == "hangup"


def test_early_hangup_scenario():
    flow = flow_at("welcome", scenario="early_hangup")
    assert complete(flow, status="valid", digits="1").action == "hangup"
    assert flow.stage == "hanging_up"


@pytest.mark.parametrize("ending", ["remote", "deadline", "close"])
def test_silent_scenario_cleanup(ending):
    async def exercise():
        sent = []

        async def send(command):
            sent.append(command)

        flow = flow_at("welcome", scenario="silent_stage")
        assert complete(flow, status="valid", digits="1") is None
        assert flow.stage == "silent" and flow.pending is None
        assert flow.deadline == flow.call_deadline
        assert flow.command_failed("obsolete", now=2) is None
        for kind in ("call.gather.ended", "call.speak.ended", "call.answered"):
            assert flow.handle(kind, {"client_state": "obsolete"}, now=2) is None
        runtime = Fixture(
            flow.settings,
            send,
            started_at=datetime.now(UTC),
            clock=lambda: flow.call_deadline if ending == "deadline" else 2,
        )
        runtime.active = flow
        if ending == "remote":
            flow.handle("call.hangup", {}, now=2)
            await runtime.tick()
            assert runtime.active is None
            assert not sent
        elif ending == "deadline":
            await runtime.tick()
            await runtime.drain()
            assert [c.action for c in sent] == ["hangup"]
        await runtime.close()
        assert runtime.active is None and not runtime.tasks
        assert len(sent) == (0 if ending == "remote" else 1)

    asyncio.run(exercise())
