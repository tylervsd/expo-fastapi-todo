from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.todo_repository import TodoRow, create_todo, list_todos, set_completed

REVISION = "2026090601"


def test_migration_creates_expected_todos_shape(database_engine: Engine) -> None:
    inspector = inspect(database_engine)

    assert inspector.get_table_names() == ["alembic_version", "todos"]
    columns = {column["name"]: column for column in inspector.get_columns("todos")}
    assert list(columns) == ["id", "public_id", "title", "completed"]
    assert all(column["nullable"] is False for column in columns.values())
    assert str(columns["id"]["type"]) == "BIGINT"
    assert str(columns["public_id"]["type"]) == "UUID"
    assert str(columns["title"]["type"]) == "TEXT"
    assert str(columns["completed"]["type"]) == "BOOLEAN"
    assert columns["id"]["identity"] is not None
    assert columns["completed"]["default"] == "false"
    assert inspector.get_pk_constraint("todos")["constrained_columns"] == ["id"]
    assert [
        (constraint["name"], constraint["column_names"])
        for constraint in inspector.get_unique_constraints("todos")
    ] == [("uq_todos_public_id", ["public_id"])]
    assert [
        (constraint["name"], constraint["sqltext"])
        for constraint in inspector.get_check_constraints("todos")
    ] == [
        (
            "ck_todos_title_length",
            "char_length(title) >= 1 AND char_length(title) <= 120",
        )
    ]
    with database_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def test_list_todos_preserves_duplicate_creation_order(database_session: Session) -> None:
    first = create_todo(database_session, uuid4(), "Repeat")
    second = create_todo(database_session, uuid4(), "Repeat")
    database_session.commit()

    assert [todo.public_id for todo in list_todos(database_session)] == [
        first.public_id,
        second.public_id,
    ]


def test_create_todo_flushes_and_persists_across_sessions(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    public_id = uuid4()
    created = create_todo(database_session, public_id, "Persisted")

    assert created.id is not None
    database_session.commit()
    with session_factory() as verification_session:
        assert verification_session.scalar(
            select(TodoRow).where(TodoRow.public_id == public_id)
        ).title == "Persisted"


def test_set_completed_updates_without_reordering(database_session: Session) -> None:
    first = create_todo(database_session, uuid4(), "First")
    second = create_todo(database_session, uuid4(), "Second")
    database_session.commit()

    updated = set_completed(database_session, first.public_id, True)
    database_session.commit()

    assert updated is not None
    assert updated.completed is True
    assert [todo.public_id for todo in list_todos(database_session)] == [
        first.public_id,
        second.public_id,
    ]


def test_set_completed_returns_none_for_missing_public_id(database_session: Session) -> None:
    assert set_completed(database_session, uuid4(), True) is None


def test_database_rejects_title_longer_than_120_code_points(
    database_session: Session,
) -> None:
    with pytest.raises(IntegrityError):
        create_todo(database_session, uuid4(), "x" * 121)


def test_rollback_does_not_persist_flushed_todo(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    public_id = uuid4()
    create_todo(database_session, public_id, "Rollback")

    database_session.rollback()
    with session_factory() as verification_session:
        assert verification_session.scalar(
            select(TodoRow).where(TodoRow.public_id == public_id)
        ) is None


def test_stale_session_patch_persists_requested_boolean(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    public_id = uuid4()
    create_todo(database_session, public_id, "Race")
    database_session.commit()

    with session_factory() as session_a:
        loaded_a = session_a.scalar(
            select(TodoRow).where(TodoRow.public_id == public_id)
        )
        assert loaded_a is not None
        assert loaded_a.completed is False
        with session_factory() as session_b:
            assert set_completed(session_b, public_id, True) is not None
            session_b.commit()
        assert loaded_a.completed is False
        assert set_completed(session_a, public_id, False) is not None
        session_a.commit()
    with session_factory() as verification_session:
        assert verification_session.scalar(
            select(TodoRow).where(TodoRow.public_id == public_id)
        ).completed is False
