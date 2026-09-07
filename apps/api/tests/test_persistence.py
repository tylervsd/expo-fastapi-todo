from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.auth_repository import (
    create_session,
    create_user,
    delete_expired_sessions,
    delete_session,
    find_user_by_username,
    find_valid_session,
    generate_token,
    hash_token,
)
from app.todo_repository import (
    TodoRow,
    create_todo,
    delete_todo,
    list_todos,
    set_completed,
)
from app.todo_repository import set_title as set_todo_title

REVISION = "2026090702"


def test_alembic_cli_loads_api_package() -> None:
    alembic = shutil.which("alembic")
    assert alembic is not None

    completed = subprocess.run(
        [alembic, "upgrade", "head", "--sql"],
        cwd=Path(__file__).parents[1],
        env=os.environ
        | {"DATABASE_URL": "postgresql+psycopg://todo:todo@127.0.0.1:5432/todo"},
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "CREATE TABLE todos" in completed.stdout


def test_migration_creates_expected_todos_shape(database_engine: Engine) -> None:
    inspector = inspect(database_engine)

    assert sorted(inspector.get_table_names()) == [
        "alembic_version",
        "sessions",
        "todo_workflows",
        "todos",
        "users",
    ]
    workflow_columns = {
        column["name"]: column for column in inspector.get_columns("todo_workflows")
    }
    assert list(workflow_columns) == [
        "id",
        "public_id",
        "owner_id",
        "state",
        "title",
        "involves_multiple_steps",
        "proposed_todo_titles",
        "completion_result",
    ]
    assert all(
        workflow_columns[name]["nullable"] is False
        for name in (
            "id",
            "public_id",
            "owner_id",
            "state",
            "title",
            "proposed_todo_titles",
        )
    )
    assert workflow_columns["involves_multiple_steps"]["nullable"] is True
    assert workflow_columns["completion_result"]["nullable"] is True
    assert str(workflow_columns["id"]["type"]) == "BIGINT"
    assert str(workflow_columns["public_id"]["type"]) == "UUID"
    assert str(workflow_columns["state"]["type"]) == "TEXT"
    assert str(workflow_columns["title"]["type"]) == "TEXT"
    assert str(workflow_columns["involves_multiple_steps"]["type"]) == "BOOLEAN"
    assert workflow_columns["id"]["identity"] is not None
    assert (
        inspector.get_pk_constraint("todo_workflows")["constrained_columns"]
        == ["id"]
    )
    assert [
        (constraint["name"], constraint["column_names"])
        for constraint in inspector.get_unique_constraints("todo_workflows")
    ] == [("uq_todo_workflows_public_id", ["public_id"])]
    assert sorted(
        [
            (constraint["name"], constraint["sqltext"])
            for constraint in inspector.get_check_constraints("todo_workflows")
        ]
    ) == [
        (
            "ck_todo_workflows_completion_object",
            "completion_result IS NULL OR jsonb_typeof(completion_result) = 'object'::text",
        ),
        (
            "ck_todo_workflows_proposals_array",
            "jsonb_typeof(proposed_todo_titles) = 'array'::text",
        ),
        (
            "ck_todo_workflows_state",
            "state = ANY (ARRAY['ASSESS_TASK'::text, 'COLLECT_TASKS'::text, 'REVIEW'::text, 'COMPLETED'::text, 'CANCELLED'::text])",
        ),
        (
            "ck_todo_workflows_title_length",
            "char_length(title) >= 1 AND char_length(title) <= 120",
        ),
    ]
    assert [
        (fk["referred_table"], tuple(fk["constrained_columns"]))
        for fk in inspector.get_foreign_keys("todo_workflows")
    ] == [("users", ("owner_id",))]
    users_columns = {
        column["name"]: column for column in inspector.get_columns("users")
    }
    assert list(users_columns) == ["id", "public_id", "username", "password_hash"]
    sessions_columns = {
        column["name"]: column for column in inspector.get_columns("sessions")
    }
    assert list(sessions_columns) == ["id", "token_hash", "user_id", "expires_at"]
    todos_columns = {
        column["name"]: column for column in inspector.get_columns("todos")
    }
    assert todos_columns["owner_id"]["nullable"] is False
    foreign_keys = inspector.get_foreign_keys("todos") + inspector.get_foreign_keys(
        "sessions"
    )
    assert {
        (fk["referred_table"], tuple(fk["constrained_columns"])) for fk in foreign_keys
    } >= {
        ("users", ("owner_id",)),
        ("users", ("user_id",)),
    }
    columns = {column["name"]: column for column in inspector.get_columns("todos")}
    assert list(columns) == ["id", "public_id", "title", "completed", "owner_id"]
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
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == REVISION
        )


def test_list_todos_preserves_duplicate_creation_order(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    first = create_todo(database_session, uuid4(), "Repeat", owner.id)
    second = create_todo(database_session, uuid4(), "Repeat", owner.id)
    database_session.commit()

    assert [todo.public_id for todo in list_todos(database_session, owner.id)] == [
        first.public_id,
        second.public_id,
    ]


def test_create_todo_flushes_and_persists_across_sessions(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    public_id = uuid4()
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    created = create_todo(database_session, public_id, "Persisted", owner.id)

    assert created.id is not None
    database_session.commit()
    with session_factory() as verification_session:
        assert (
            verification_session.scalar(
                select(TodoRow).where(TodoRow.public_id == public_id)
            ).title
            == "Persisted"
        )


def test_set_completed_updates_without_reordering(database_session: Session) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    first = create_todo(database_session, uuid4(), "First", owner.id)
    second = create_todo(database_session, uuid4(), "Second", owner.id)
    database_session.commit()

    updated = set_completed(database_session, first.public_id, True, owner.id)
    database_session.commit()

    assert updated is not None
    assert updated.completed is True
    assert [todo.public_id for todo in list_todos(database_session, owner.id)] == [
        first.public_id,
        second.public_id,
    ]


def test_set_completed_returns_none_for_missing_public_id(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    assert set_completed(database_session, uuid4(), True, owner.id) is None


def test_database_rejects_title_longer_than_120_code_points(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    with pytest.raises(IntegrityError):
        create_todo(database_session, uuid4(), "x" * 121, owner.id)


def test_rollback_does_not_persist_flushed_todo(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    public_id = uuid4()
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    create_todo(database_session, public_id, "Rollback", owner.id)

    database_session.rollback()
    with session_factory() as verification_session:
        assert (
            verification_session.scalar(
                select(TodoRow).where(TodoRow.public_id == public_id)
            )
            is None
        )


def test_stale_session_patch_persists_requested_boolean(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    public_id = uuid4()
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    create_todo(database_session, public_id, "Race", owner.id)
    database_session.commit()

    with session_factory() as session_a:
        loaded_a = session_a.scalar(
            select(TodoRow).where(TodoRow.public_id == public_id)
        )
        assert loaded_a is not None
        assert loaded_a.completed is False
        with session_factory() as session_b:
            assert set_completed(session_b, public_id, True, owner.id) is not None
            session_b.commit()
        assert loaded_a.completed is False
        assert set_completed(session_a, public_id, False, owner.id) is not None
        session_a.commit()
    with session_factory() as verification_session:
        assert (
            verification_session.scalar(
                select(TodoRow).where(TodoRow.public_id == public_id)
            ).completed
            is False
        )


def test_set_title_updates_without_reordering(database_session: Session) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    first = create_todo(database_session, uuid4(), "First", owner.id)
    second = create_todo(database_session, uuid4(), "Second", owner.id)
    database_session.commit()

    updated = set_todo_title(database_session, first.public_id, "Renamed", owner.id)
    database_session.commit()

    assert updated is not None
    assert updated.title == "Renamed"
    assert [todo.public_id for todo in list_todos(database_session, owner.id)] == [
        first.public_id,
        second.public_id,
    ]


def test_set_title_returns_none_for_missing_public_id(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    assert set_todo_title(database_session, uuid4(), "Absent", owner.id) is None


def test_set_title_persists_across_fresh_session(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    public_id = uuid4()
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    create_todo(database_session, public_id, "Before", owner.id)
    database_session.commit()

    assert set_todo_title(database_session, public_id, "After", owner.id) is not None
    database_session.commit()
    with session_factory() as verification_session:
        assert (
            verification_session.scalar(
                select(TodoRow).where(TodoRow.public_id == public_id)
            ).title
            == "After"
        )


def test_delete_todo_removes_row_and_preserves_survivor_order(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    first = create_todo(database_session, uuid4(), "First", owner.id)
    second = create_todo(database_session, uuid4(), "Second", owner.id)
    database_session.commit()

    assert delete_todo(database_session, first.public_id, owner.id) is True
    database_session.commit()

    assert [todo.public_id for todo in list_todos(database_session, owner.id)] == [
        second.public_id
    ]


def test_delete_todo_returns_false_for_missing_public_id(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    assert delete_todo(database_session, uuid4(), owner.id) is False


def test_delete_todo_persists_across_fresh_session(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    public_id = uuid4()
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    create_todo(database_session, public_id, "Gone", owner.id)
    database_session.commit()

    assert delete_todo(database_session, public_id, owner.id) is True
    database_session.commit()
    with session_factory() as verification_session:
        assert (
            verification_session.scalar(
                select(TodoRow).where(TodoRow.public_id == public_id)
            )
            is None
        )


def test_token_hash_is_stable_hex_and_token_is_hex_64() -> None:
    token = generate_token()

    assert len(token) == 64
    int(token, 16)
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token


def test_user_round_trip_and_duplicate_username_fails(
    database_session: Session,
) -> None:
    created = create_user(database_session, uuid4(), "alice", "hash-1")
    database_session.commit()

    assert (
        find_user_by_username(database_session, "alice").public_id == created.public_id
    )
    assert find_user_by_username(database_session, "nobody") is None
    with pytest.raises(IntegrityError):
        create_user(database_session, uuid4(), "alice", "hash-2")


def test_session_validity_honors_expiry(database_session: Session) -> None:
    user = create_user(database_session, uuid4(), "alice", "hash-1")
    database_session.flush()
    live = hash_token(generate_token())
    dead = hash_token(generate_token())
    create_session(
        database_session, user.id, live, datetime.now(UTC) + timedelta(days=30)
    )
    create_session(
        database_session,
        user.id,
        dead,
        datetime.now(UTC) - timedelta(seconds=1),
    )
    database_session.commit()

    assert find_valid_session(database_session, live).user_id == user.id
    assert find_valid_session(database_session, dead) is None
    assert find_valid_session(database_session, "0" * 64) is None


def test_session_delete_and_expired_cleanup(database_session: Session) -> None:
    user = create_user(database_session, uuid4(), "alice", "hash-1")
    database_session.flush()
    doomed = hash_token(generate_token())
    create_session(
        database_session, user.id, doomed, datetime.now(UTC) + timedelta(days=30)
    )
    database_session.commit()

    assert delete_session(database_session, doomed) is True
    database_session.commit()
    assert delete_session(database_session, doomed) is False
    assert delete_expired_sessions(database_session, user.id) == 0


def test_todos_are_scoped_to_owner(database_session: Session) -> None:
    alice = create_user(database_session, uuid4(), "alice", "hash-1")
    bob = create_user(database_session, uuid4(), "bob", "hash-2")
    database_session.flush()
    mine = create_todo(database_session, uuid4(), "Mine", alice.id)
    create_todo(database_session, uuid4(), "Theirs", bob.id)
    database_session.commit()

    assert [row.public_id for row in list_todos(database_session, alice.id)] == [
        mine.public_id
    ]
    assert set_completed(database_session, mine.public_id, True, bob.id) is None
    assert delete_todo(database_session, mine.public_id, bob.id) is False
