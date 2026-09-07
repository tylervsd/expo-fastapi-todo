from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Text,
    delete,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql.expression import false

from app.database import Base


class TodoRow(Base):
    __tablename__ = "todos"
    __table_args__ = (
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 120", name="ck_todos_title_length"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), unique=True, nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


def list_todos(session: Session, owner_id: int) -> Sequence[TodoRow]:
    return session.scalars(
        select(TodoRow).where(TodoRow.owner_id == owner_id).order_by(TodoRow.id)
    ).all()


def create_todo(
    session: Session, public_id: UUID, title: str, owner_id: int
) -> TodoRow:
    todo = TodoRow(public_id=public_id, title=title, completed=False, owner_id=owner_id)
    session.add(todo)
    session.flush()
    return todo


def set_completed(
    session: Session, public_id: UUID, completed: bool, owner_id: int
) -> TodoRow | None:
    return session.execute(
        update(TodoRow)
        .where(TodoRow.public_id == public_id, TodoRow.owner_id == owner_id)
        .values(completed=completed)
        .returning(TodoRow)
    ).scalar_one_or_none()


def set_title(
    session: Session, public_id: UUID, title: str, owner_id: int
) -> TodoRow | None:
    return session.execute(
        update(TodoRow)
        .where(TodoRow.public_id == public_id, TodoRow.owner_id == owner_id)
        .values(title=title)
        .returning(TodoRow)
    ).scalar_one_or_none()


def delete_todo(session: Session, public_id: UUID, owner_id: int) -> bool:
    return (
        session.execute(
            delete(TodoRow)
            .where(TodoRow.public_id == public_id, TodoRow.owner_id == owner_id)
            .returning(TodoRow.public_id)
        ).scalar_one_or_none()
        is not None
    )
