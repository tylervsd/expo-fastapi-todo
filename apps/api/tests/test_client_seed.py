"""Phase 30a synthetic client events: deterministic, free of text, aligned with the 28b seed."""

import importlib.util
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

SCRIPTS = Path(__file__).parents[3] / "analytics_practice"
_spec = importlib.util.spec_from_file_location("seed_client_events", SCRIPTS / "seed_client_events.py")
assert _spec is not None and _spec.loader is not None
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)

ALLOWED = {
    "auth_screen_viewed": {"mode"},
    "signup_submitted": set(),
    "signin_submitted": set(),
    "suggestion_requested": {"workflow_key"},
}


def test_build_is_deterministic_unique_and_prefixed() -> None:
    events = seed.build_events()
    assert events == seed.build_events()
    assert 2500 < len(events) < 5000
    assert len({e["messageId"] for e in events}) == len(events)
    assert all(e["anonymousId"].startswith(seed.ANON_PREFIX) for e in events)
    assert all(e.get("userId", seed.USER_PREFIX).startswith(seed.USER_PREFIX) for e in events)
    assert all(e["timestamp"] < "2026-09-25" for e in events)


def test_events_carry_no_free_text_or_traits() -> None:
    for event in seed.build_events():
        if event["type"] == "identify":
            assert "traits" not in event and "properties" not in event
            continue
        assert event["type"] == "track"
        assert set(event["properties"]) == ALLOWED[event["event"]]


def test_shape_has_blocked_users_visitors_and_retaps() -> None:
    events = seed.build_events()
    identified = {e["userId"] for e in events if e["type"] == "identify"}
    assert 340 <= len(identified) <= 390  # about 8% of 400 simulate ad blockers
    anonymous = {e["anonymousId"] for e in events}
    linked = {e["anonymousId"] for e in events if e["type"] == "identify"}
    assert 550 <= len(anonymous - linked) <= 600  # visitors who never sign up
    taps = [e for e in events if e.get("event") == "suggestion_requested"]
    server_suggestions = sum(
        sum(1 for at in u["suggestions"] if at < seed.CUTOFF)
        for u in seed.server_timeline()
        if u["user_key"] in identified
    )
    assert len(taps) > server_suggestions  # retaps add taps without outcomes

    # Returning users: anonymous visitors who stayed on sign-in and signed back in,
    # never submitting a signup (about 600 * 0.5 * 0.4 = 120).
    signed_up_anon = {
        e["anonymousId"] for e in events if e.get("event") == "signup_submitted"
    }
    signed_in_anon = {
        e["anonymousId"] for e in events if e.get("event") == "signin_submitted"
    }
    returning = signed_in_anon - signed_up_anon
    assert 80 <= len(returning) <= 160


def test_visitor_events_never_carry_a_userid() -> None:
    # Visitor anonymous IDs are ANON_PREFIX + (100000 + v); synthetic-user anonymous IDs
    # are ANON_PREFIX + n for n in 1..400. The returning-user metric depends on visitor
    # events (including signin_submitted) never being attributable to a userId, and on
    # a user's own signin_submitted always carrying that user's userId.
    for event in seed.build_events():
        n = int(event["anonymousId"][len(seed.ANON_PREFIX):])
        if n > 100000:
            assert "userId" not in event
        elif event.get("event") == "signin_submitted":
            assert event["userId"] == f"{seed.USER_PREFIX}{n:012d}"


def test_matches_the_28b_outbox_seed(database_session: Session, database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.connection.cursor().execute((SCRIPTS / "seed_outbox.sql").read_text())
    signups = dict(
        database_session.execute(
            text("SELECT user_key::text, occurred_at FROM analytics_events WHERE event_name = 'user_signed_up'")
        ).all()
    )
    outcomes = database_session.execute(
        text("SELECT workflow_key::text, occurred_at FROM analytics_events WHERE event_name = 'suggestion_finished'")
    ).all()
    events = seed.build_events()
    at = lambda e: datetime.fromisoformat(e["timestamp"])

    identifies = [e for e in events if e["type"] == "identify"]
    assert identifies
    for event in identifies:
        assert at(event) - timedelta(seconds=1) == signups[event["userId"]]

    taps = defaultdict(list)
    for event in events:
        if event.get("event") == "suggestion_requested":
            taps[event["properties"]["workflow_key"]].append(at(event))
    tapped_workflows = set(taps)
    matched = 0
    for workflow_key, finished_at in outcomes:
        if workflow_key in tapped_workflows:
            assert any(timedelta(seconds=5) <= finished_at - t <= timedelta(seconds=60) for t in taps[workflow_key])
            matched += 1
    assert matched > 500
