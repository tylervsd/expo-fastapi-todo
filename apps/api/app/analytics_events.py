"""Phase 26 analytics outbox. Events commit with their business change.

Every column is an identifier, enum, timestamp or integer: no free text can
enter the pipeline. user_key is users.public_id (pseudonymous, not anonymous).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    SmallInteger,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.auth_repository import UserRow
from app.database import Base

EVENT_NAMES = frozenset(
    {"user_signed_up", "workflow_started", "workflow_completed", "suggestion_finished"}
)


class AnalyticsEventRow(Base):
    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), unique=True)
    event_name: Mapped[str] = mapped_column(Text)
    user_key: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True))
    workflow_key: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    schema_version: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def record_event(
    session: Session,
    event_name: str,
    owner_id: int,
    *,
    workflow_key: UUID | None = None,
    outcome: str | None = None,
) -> None:
    """Add one event to the caller's transaction; never commits."""
    if event_name not in EVENT_NAMES:
        raise ValueError(f"unknown analytics event {event_name!r}")
    session.add(
        AnalyticsEventRow(
            event_id=uuid4(),
            event_name=event_name,
            user_key=select(UserRow.public_id)
            .where(UserRow.id == owner_id)
            .scalar_subquery(),
            workflow_key=workflow_key,
            outcome=outcome,
        )
    )
