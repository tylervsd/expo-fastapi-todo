"""Phase 23 operator backfill: stamp legacy completed todos with completed_at.

Deliberately not an Alembic migration, so releases can run ahead of it. The
timestamp is the backfill time: real historical completion times are unknown.
Run on the migration job:  python -m app.backfill_completed_at
"""

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.database import (
    create_database_engine,
    create_session_factory,
    get_database_url,
)

# The outer WHERE re-checks the conditions so a row reopened concurrently is skipped.
BATCH_SQL = """
UPDATE todos SET completed_at = now()
WHERE id IN (
    SELECT id FROM todos
    WHERE completed AND completed_at IS NULL
    ORDER BY id LIMIT :batch_size
    FOR UPDATE SKIP LOCKED
)
AND completed AND completed_at IS NULL
"""


def backfill(session_factory: sessionmaker[Session], batch_size: int = 500) -> int:
    total = 0
    batches = 0
    while True:
        with session_factory.begin() as session:
            updated = session.execute(
                text(BATCH_SQL), {"batch_size": batch_size}
            ).rowcount
        if updated == 0:
            break
        total += updated
        batches += 1
    print(f"backfill_completed_at: updated={total} batches={batches}", flush=True)
    return total


if __name__ == "__main__":
    engine = create_database_engine(get_database_url())
    try:
        backfill(create_session_factory(engine))
    finally:
        engine.dispose()
