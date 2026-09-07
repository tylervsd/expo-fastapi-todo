import hashlib
import secrets
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Text,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), unique=True, nullable=False
    )
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


def generate_token() -> str:
    return secrets.token_hex(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user(
    session: Session, public_id: UUID, username: str, password_hash: str
) -> UserRow:
    user = UserRow(public_id=public_id, username=username, password_hash=password_hash)
    session.add(user)
    session.flush()
    return user


def find_user_by_username(session: Session, username: str) -> UserRow | None:
    return session.scalar(select(UserRow).where(UserRow.username == username))


def find_user_by_id(session: Session, user_id: int) -> UserRow | None:
    return session.get(UserRow, user_id)


def create_session(
    session: Session, user_id: int, token_hash: str, expires_at: datetime
) -> SessionRow:
    row = SessionRow(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    session.add(row)
    session.flush()
    return row


def find_valid_session(session: Session, token_hash: str) -> SessionRow | None:
    return session.scalar(
        select(SessionRow).where(
            SessionRow.token_hash == token_hash, SessionRow.expires_at > func.now()
        )
    )


def delete_session(session: Session, token_hash: str) -> bool:
    return (
        session.execute(
            delete(SessionRow)
            .where(SessionRow.token_hash == token_hash)
            .returning(SessionRow.id)
        ).scalar_one_or_none()
        is not None
    )


def delete_expired_sessions(session: Session, user_id: int) -> int:
    result = session.execute(
        delete(SessionRow).where(
            SessionRow.user_id == user_id, SessionRow.expires_at <= func.now()
        )
    )
    return result.rowcount
