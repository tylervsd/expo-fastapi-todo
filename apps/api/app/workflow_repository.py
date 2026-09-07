from uuid import UUID

from sqlalchemy import BigInteger, Boolean, ForeignKey, Identity, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base


class WorkflowRow(Base):
    __tablename__ = "todo_workflows"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), unique=True, nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    involves_multiple_steps: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    proposed_todo_titles: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    completion_result: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )


def create_workflow(
    session: Session, public_id: UUID, owner_id: int, title: str
) -> WorkflowRow:
    row = WorkflowRow(
        public_id=public_id,
        owner_id=owner_id,
        state="ASSESS_TASK",
        title=title,
        involves_multiple_steps=None,
        proposed_todo_titles=[],
        completion_result=None,
    )
    session.add(row)
    session.flush()
    return row


def find_workflow(
    session: Session, public_id: UUID, owner_id: int
) -> WorkflowRow | None:
    return session.scalar(
        select(WorkflowRow).where(
            WorkflowRow.public_id == public_id, WorkflowRow.owner_id == owner_id
        )
    )


def lock_workflow(
    session: Session, public_id: UUID, owner_id: int
) -> WorkflowRow | None:
    return session.scalar(
        select(WorkflowRow)
        .where(WorkflowRow.public_id == public_id, WorkflowRow.owner_id == owner_id)
        .with_for_update()
    )


def update_workflow(
    session: Session,
    row: WorkflowRow,
    *,
    state: str,
    involves_multiple_steps: bool | None,
    proposed_todo_titles: list[str],
    completion_result: dict[str, object] | None,
) -> WorkflowRow:
    row.state = state
    row.involves_multiple_steps = involves_multiple_steps
    row.proposed_todo_titles = list(proposed_todo_titles)
    if completion_result is None:
        row.completion_result = None
    elif isinstance(completion_result, dict):
        row.completion_result = dict(completion_result)
    else:
        # Pass through so the database object check rejects it.
        row.completion_result = completion_result
    session.flush()
    return row
