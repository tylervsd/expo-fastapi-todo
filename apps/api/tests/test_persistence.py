from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
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

REVISION = "2026092601"


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
        "analytics_events",
        "sessions",
        "todo_workflow_action_requests",
        "todo_workflow_start_requests",
        "todo_workflow_suggestion_requests",
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
        "revision",
        "definition_version",
    ]
    assert workflow_columns["revision"]["nullable"] is False
    assert workflow_columns["definition_version"]["nullable"] is False
    assert str(workflow_columns["revision"]["type"]) == "INTEGER"
    assert str(workflow_columns["definition_version"]["type"]) == "INTEGER"
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
    assert sorted(
        [
            (constraint["name"], constraint["column_names"])
            for constraint in inspector.get_unique_constraints("todo_workflows")
        ]
    ) == [
        ("uq_todo_workflows_public_id", ["public_id"]),
        ("uq_todo_workflows_public_owner", ["public_id", "owner_id"]),
    ]
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
            "ck_todo_workflows_definition_version",
            "definition_version >= 1",
        ),
        (
            "ck_todo_workflows_proposals_array",
            "jsonb_typeof(proposed_todo_titles) = 'array'::text",
        ),
        (
            "ck_todo_workflows_revision_range",
            "revision >= 0 AND revision <= 2147483647",
        ),
        (
            "ck_todo_workflows_state",
            (
                "state = ANY (ARRAY['ASSESS_TASK'::text, 'OFFER_BREAKDOWN'::text, "
                "'COLLECT_TASKS'::text, 'REVIEW'::text, 'COMPLETED'::text, "
                "'CANCELLED'::text])"
            ),
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
    start_columns = {
        column["name"]: column
        for column in inspector.get_columns("todo_workflow_start_requests")
    }
    assert list(start_columns) == [
        "owner_id",
        "request_id",
        "request_fingerprint",
        "workflow_id",
        "accepted_snapshot",
    ]
    assert (
        inspector.get_pk_constraint("todo_workflow_start_requests")[
            "constrained_columns"
        ]
        == ["owner_id", "request_id"]
    )
    assert sorted(
        (fk["referred_table"], tuple(fk["constrained_columns"]))
        for fk in inspector.get_foreign_keys("todo_workflow_start_requests")
    ) == [("todo_workflows", ("workflow_id",)), ("users", ("owner_id",))]
    assert sorted(
        constraint["name"]
        for constraint in inspector.get_check_constraints(
            "todo_workflow_start_requests"
        )
    ) == [
        "ck_start_requests_fingerprint_hex",
        "ck_start_requests_snapshot_object",
    ]
    action_columns = {
        column["name"]: column
        for column in inspector.get_columns("todo_workflow_action_requests")
    }
    assert list(action_columns) == [
        "owner_id",
        "workflow_id",
        "request_id",
        "request_fingerprint",
        "accepted_snapshot",
    ]
    assert (
        inspector.get_pk_constraint("todo_workflow_action_requests")[
            "constrained_columns"
        ]
        == ["owner_id", "workflow_id", "request_id"]
    )
    assert [
        (fk["referred_table"], tuple(fk["constrained_columns"]))
        for fk in inspector.get_foreign_keys("todo_workflow_action_requests")
    ] == [("todo_workflows", ("workflow_id", "owner_id"))]
    assert sorted(
        constraint["name"]
        for constraint in inspector.get_check_constraints(
            "todo_workflow_action_requests"
        )
    ) == [
        "ck_action_requests_fingerprint_hex",
        "ck_action_requests_snapshot_object",
    ]
    users_columns = {
        column["name"]: column for column in inspector.get_columns("users")
    }
    assert list(users_columns) == ["id", "public_id", "username", "password_hash", "real_name_ciphertext"]
    assert users_columns["real_name_ciphertext"]["nullable"] is True
    assert str(users_columns["real_name_ciphertext"]["type"]) == "BYTEA"
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
    assert list(columns) == [
        "id",
        "public_id",
        "title",
        "completed",
        "owner_id",
        "completed_at",
    ]
    assert all(
        column["nullable"] is False
        for name, column in columns.items()
        if name != "completed_at"
    )
    assert columns["completed_at"]["nullable"] is True
    assert columns["completed_at"]["type"].timezone is True
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


def test_set_completed_dual_writes_and_preserves_first_completion_time(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    todo = create_todo(database_session, uuid4(), "Pay invoice", owner.id)
    database_session.commit()
    assert todo.completed_at is None

    first = set_completed(database_session, todo.public_id, True, owner.id)
    database_session.commit()
    assert first is not None and first.completed is True
    assert first.completed_at is not None
    first_time = first.completed_at

    again = set_completed(database_session, todo.public_id, True, owner.id)
    database_session.commit()
    assert again is not None and again.completed_at == first_time

    reopened = set_completed(database_session, todo.public_id, False, owner.id)
    database_session.commit()
    assert reopened is not None
    assert reopened.completed is False and reopened.completed_at is None
    assert reopened.is_completed is False


def test_set_completed_other_owner_touches_nothing(database_session: Session) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    other = create_user(database_session, uuid4(), "other", "hash")
    database_session.flush()
    todo = create_todo(database_session, uuid4(), "Mine", owner.id)
    database_session.commit()

    assert set_completed(database_session, todo.public_id, True, other.id) is None
    database_session.commit()
    database_session.refresh(todo)
    assert todo.completed is False and todo.completed_at is None


def test_add_completed_at_migration_reverses(database_engine: Engine) -> None:
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    with database_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "2026091801")
        assert "completed_at" not in {
            column["name"] for column in inspect(connection).get_columns("todos")
        }
        command.upgrade(config, "head")


def test_reads_come_from_completed_at_so_unbackfilled_rows_read_open(
    database_session: Session,
) -> None:
    """Pins the drill defect: before the backfill, legacy completions read as open."""
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    legacy = create_todo(database_session, uuid4(), "Legacy done", owner.id)
    database_session.flush()
    database_session.execute(
        update(TodoRow).where(TodoRow.id == legacy.id).values(completed=True)
    )
    database_session.commit()
    database_session.refresh(legacy)
    assert legacy.completed is True and legacy.is_completed is False

    done = set_completed(database_session, legacy.public_id, True, owner.id)
    database_session.commit()
    assert done is not None and done.is_completed is True and done.completed is True


def test_dual_write_keeps_columns_consistent_for_rollback_to_a(
    database_session: Session,
) -> None:
    owner = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    todo = create_todo(database_session, uuid4(), "Workflow-made", owner.id)
    database_session.commit()
    assert todo.is_completed is False
    for value in (True, False, True):
        row = set_completed(database_session, todo.public_id, value, owner.id)
        database_session.commit()
        assert row is not None
        assert row.completed is value and row.is_completed is value
