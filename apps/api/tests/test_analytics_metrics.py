"""PostgreSQL reconciliation SQL encodes the Phase 26 metric definitions."""

from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

SQL = Path(__file__).parents[1] / "analytics_sql"


def _event(
    s: Session, name: str, user: UUID, at: str, outcome: str | None = None
) -> None:
    s.execute(
        text(
            "INSERT INTO analytics_events "
            "(event_id, event_name, user_key, outcome, occurred_at) "
            "VALUES (:id, :n, :u, :o, CAST(:at AS timestamptz))"
        ),
        {"id": uuid4(), "n": name, "u": user, "o": outcome, "at": at},
    )


def _run(s: Session, name: str):
    return s.execute(text((SQL / name).read_text())).mappings().all()


def test_activation_funnel_counts_distinct_users_within_7_days(
    database_session: Session,
) -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    for user in (a, b, c):
        _event(database_session, "user_signed_up", user, "2026-08-03T10:00:00Z")
    _event(database_session, "workflow_started", a, "2026-08-04T10:00:00Z")
    _event(database_session, "workflow_started", a, "2026-08-05T10:00:00Z")
    _event(database_session, "workflow_completed", a, "2026-08-05T11:00:00Z")
    _event(database_session, "workflow_started", b, "2026-08-11T10:00:00Z")  # day 8
    database_session.commit()
    rows = _run(database_session, "postgres_activation_funnel.sql")
    assert len(rows) == 1
    r = rows[0]
    assert str(r["cohort_week"]) == "2026-08-03"
    assert (r["signed_up"], r["started_7d"], r["completed_7d"]) == (3, 1, 1)
    assert float(r["started_rate"]) == round(1 / 3, 4)
    assert r["cohort_complete"] is True


def test_current_week_cohort_is_marked_incomplete(database_session: Session) -> None:
    _event(database_session, "user_signed_up", uuid4(), "now")
    database_session.commit()
    rows = _run(database_session, "postgres_activation_funnel.sql")
    assert rows[-1]["cohort_complete"] is False


def test_suggestion_success_rate_over_terminal_outcomes(
    database_session: Session,
) -> None:
    user = uuid4()
    for outcome in ("ready", "ready", "failed", "expired"):
        _event(
            database_session, "suggestion_finished", user,
            "2026-08-03T10:00:00Z", outcome,
        )
    database_session.commit()
    r = _run(database_session, "postgres_suggestion_success.sql")[0]
    assert (str(r["day"]), r["ready"], r["failed"], r["expired"]) == (
        "2026-08-03", 2, 1, 1,
    )
    assert float(r["success_rate"]) == 0.5
