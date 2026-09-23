from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth_repository import create_user
from app.backfill_completed_at import BATCH_SQL, backfill
from app.todo_repository import TodoRow, create_todo, set_completed


def _legacy_completed(session: Session, owner_id: int, count: int) -> list[TodoRow]:
    """Simulate rows completed before release A: completed but no timestamp."""
    rows = [
        create_todo(session, uuid4(), f"Legacy {i}", owner_id) for i in range(count)
    ]
    session.flush()
    session.execute(
        update(TodoRow)
        .where(TodoRow.id.in_([row.id for row in rows]))
        .values(completed=True, completed_at=None)
    )
    return rows


def test_backfill_stamps_legacy_rows_in_batches_and_is_idempotent(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    _legacy_completed(database_session, owner.id, 5)
    open_todo = create_todo(database_session, uuid4(), "Still open", owner.id)
    database_session.commit()

    assert backfill(session_factory, batch_size=2) == 5
    assert backfill(session_factory, batch_size=2) == 0

    with session_factory() as check:
        rows = check.scalars(select(TodoRow)).all()
        assert all((row.completed_at is not None) == row.completed for row in rows)
        assert check.get(TodoRow, open_todo.id).completed_at is None


def test_backfill_keeps_existing_timestamps_and_skips_reopened(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    done = create_todo(database_session, uuid4(), "Done in A", owner.id)
    database_session.commit()
    stamped = set_completed(database_session, done.public_id, True, owner.id)
    database_session.commit()
    original = stamped.completed_at
    reopened = create_todo(database_session, uuid4(), "Reopened", owner.id)
    database_session.commit()
    set_completed(database_session, reopened.public_id, True, owner.id)
    set_completed(database_session, reopened.public_id, False, owner.id)
    database_session.commit()

    assert backfill(session_factory) == 0
    with session_factory() as check:
        assert check.get(TodoRow, done.id).completed_at == original
        assert check.get(TodoRow, reopened.id).completed_at is None


def test_backfill_on_empty_table_reports_zero(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    database_session.commit()
    assert backfill(session_factory) == 0


def test_backfill_update_rechecks_conditions() -> None:
    """A row reopened after selection must not be stamped (outer WHERE re-check)."""
    assert BATCH_SQL.count("completed AND completed_at IS NULL") == 2


def test_backfill_clears_stamps_left_by_pre_a_code_after_a_rollback(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    """Rolled back to pre-A code, a reopen writes only `completed`, leaving a stale
    stamp that release B would read as completed. The backfill reconciles it."""
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    todo = create_todo(database_session, uuid4(), "Reopened by old code", owner.id)
    database_session.commit()
    set_completed(database_session, todo.public_id, True, owner.id)
    database_session.execute(
        update(TodoRow).where(TodoRow.id == todo.id).values(completed=False)
    )
    database_session.commit()

    assert backfill(session_factory) == 1
    assert backfill(session_factory) == 0
    with session_factory() as check:
        assert check.get(TodoRow, todo.id).completed_at is None
