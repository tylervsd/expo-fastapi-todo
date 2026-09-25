"""Phase 28b synthetic outbox seed: deterministic, constraint-valid, removable."""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.analytics_events import record_event
from app.auth_repository import create_user

SCRIPTS = Path(__file__).parents[3] / "analytics_practice"
PREFIX = "00000000-0000-4000-8000-"


def _run(engine: Engine, name: str) -> None:
    # Raw cursor, no parameters: runs the file as plain SQL, as Cloud SQL Studio
    # does (so the LIKE '...%' in unseed.sql isn't parsed as a placeholder).
    with engine.begin() as connection:
        connection.connection.cursor().execute((SCRIPTS / name).read_text())


def _scalar(session: Session, sql: str):
    return session.execute(text(sql)).scalar_one()


def test_seed_is_deterministic_and_rerun_inserts_nothing(
    database_session: Session, database_engine: Engine
) -> None:
    _run(database_engine, "seed_outbox.sql")
    first = _scalar(database_session, "SELECT count(*) FROM analytics_events")
    fingerprint = _scalar(
        database_session,
        "SELECT md5(string_agg(event_id::text || event_name || occurred_at::text, ',' "
        "ORDER BY event_id)) FROM analytics_events",
    )
    _run(database_engine, "seed_outbox.sql")
    assert _scalar(database_session, "SELECT count(*) FROM analytics_events") == first
    assert first > 1000
    assert fingerprint == _scalar(
        database_session,
        "SELECT md5(string_agg(event_id::text || event_name || occurred_at::text, ',' "
        "ORDER BY event_id)) FROM analytics_events",
    )


def test_seed_shape(database_session: Session, database_engine: Engine) -> None:
    _run(database_engine, "seed_outbox.sql")
    row = (
        database_session.execute(
            text(
                "SELECT "
                "count(DISTINCT user_key) FILTER (WHERE event_name = 'user_signed_up') AS users, "
                "count(*) FILTER (WHERE occurred_at >= '2026-09-25T00:00:00Z') AS after_cutoff, "
                "count(*) FILTER (WHERE event_name = 'user_signed_up' "
                "  AND occurred_at >= '2026-09-21T00:00:00Z') AS partial_week_signups, "
                "count(*) FILTER (WHERE user_key::text NOT LIKE :prefix) AS unprefixed "
                "FROM analytics_events"
            ),
            {"prefix": PREFIX + "%"},
        )
        .mappings()
        .one()
    )
    assert row["users"] == 400
    assert row["after_cutoff"] == 0
    assert row["partial_week_signups"] > 0
    assert row["unprefixed"] == 0


def test_dip_week_has_lowest_success_rate(
    database_session: Session, database_engine: Engine
) -> None:
    _run(database_engine, "seed_outbox.sql")
    weeks = database_session.execute(
        text(
            "SELECT date_trunc('week', occurred_at AT TIME ZONE 'UTC')::date AS week, "
            "avg((outcome = 'ready')::int) AS rate "
            "FROM analytics_events WHERE event_name = 'suggestion_finished' "
            "AND occurred_at < '2026-09-21T00:00:00Z' GROUP BY 1"
        )
    ).all()
    lowest = min(weeks, key=lambda w: w.rate)
    assert str(lowest.week) == "2026-09-07"
    others = [w.rate for w in weeks if str(w.week) != "2026-09-07"]
    assert float(min(others)) - float(lowest.rate) >= 0.2


def test_unseed_removes_only_synthetic_rows(
    database_session: Session, database_engine: Engine
) -> None:
    real_user = create_user(database_session, uuid4(), "real-user", "hash")
    database_session.flush()
    record_event(database_session, "user_signed_up", real_user.id)
    database_session.commit()
    _run(database_engine, "seed_outbox.sql")
    _run(database_engine, "unseed.sql")
    assert _scalar(database_session, "SELECT count(*) FROM analytics_events") == 1
    assert (
        _scalar(database_session, "SELECT user_key FROM analytics_events")
        == real_user.public_id
    )
