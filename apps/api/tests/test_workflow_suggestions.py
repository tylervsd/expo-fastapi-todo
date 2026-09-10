from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.auth_repository import create_user
from app.suggestion_service import (
    InvalidStoredSuggestion,
    InvalidSuggestionState,
    StaleSuggestion,
    SuggestionErrorCode,
    SuggestionInProgress,
    SuggestionReservation,
    SuggestionSnapshot,
    SuggestionStatus,
    finish_suggestion,
    get_current_suggestion,
    reserve_suggestion,
    suggestion_snapshot_from_row,
)
from app.workflow_domain import (
    AnswerMultipleSteps,
    WorkflowState,
)
from app.workflow_repository import WorkflowSuggestionRequestRow
from app.workflow_service import (
    RequestIdReused,
    advance_workflow,
    start_workflow,
)


def setup_owner(session_factory: sessionmaker[Session], username: str = "owner") -> int:
    with session_factory() as session:
        owner = create_user(session, uuid4(), username, "hash")
        session.commit()
        return owner.id


def make_collecting(
    session_factory: sessionmaker[Session], owner_id: int
) -> tuple[UUID, int, str]:
    with session_factory() as session:
        initial = start_workflow(session, owner_id, "Plan birthday party", uuid4())
    with session_factory() as session:
        offered = advance_workflow(
            session,
            owner_id,
            initial.id,
            AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{initial.id}:ASSESS_TASK",
        )
    assert offered is not None
    with session_factory() as session:
        collecting = advance_workflow(
            session,
            owner_id,
            initial.id,
            AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=1,
            step_id=f"{initial.id}:OFFER_BREAKDOWN",
        )
    assert collecting is not None
    assert collecting.state is WorkflowState.COLLECT_TASKS
    return initial.id, collecting.revision, f"{initial.id}:COLLECT_TASKS"


def reserve(
    session_factory: sessionmaker[Session],
    owner_id: int,
    workflow_id: UUID,
    revision: int,
    step_id: str,
    request_id: UUID | None = None,
) -> SuggestionReservation | SuggestionSnapshot | None:
    with session_factory() as session:
        return reserve_suggestion(
            session,
            owner_id,
            workflow_id,
            request_id or uuid4(),
            revision,
            step_id,
        )


def test_reserve_creates_pending_record_without_workflow_mutation(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = uuid4()

    result = reserve(session_factory, owner_id, workflow_id, revision, step_id, request_id)

    assert isinstance(result, SuggestionReservation)
    assert result.goal == "Plan birthday party"
    assert result.base_revision == revision
    with session_factory() as session:
        row = session.scalar(
            select(WorkflowSuggestionRequestRow).where(
                WorkflowSuggestionRequestRow.request_id == request_id
            )
        )
        assert row is not None
        assert row.status == SuggestionStatus.PENDING.value
        assert row.proposed_titles == []
        assert row.error_code is None
        workflow = session.execute(
            text(
                "SELECT revision, state, proposed_todo_titles::text "
                "FROM todo_workflows WHERE public_id = :id"
            ),
            {"id": str(workflow_id)},
        ).one()
        assert tuple(workflow) == (revision, "COLLECT_TASKS", "[]")


def test_owner_hidden_lookup_and_collect_state_guard(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory, "owner")
    other_id = setup_owner(session_factory, "other")
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)

    assert reserve(session_factory, other_id, workflow_id, revision, step_id) is None
    with session_factory() as session:
        initial = start_workflow(session, owner_id, "Another plan", uuid4())
    with session_factory() as session, pytest.raises(InvalidSuggestionState):
        reserve_suggestion(
            session,
            owner_id,
            initial.id,
            uuid4(),
            0,
            f"{initial.id}:ASSESS_TASK",
        )


def test_reserve_requires_exact_revision_and_step(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    for bad_revision, bad_step in (
        (revision - 1, step_id),
        (revision, f"{workflow_id}:OFFER_BREAKDOWN"),
    ):
        with session_factory() as session, pytest.raises(ValueError):
            reserve_suggestion(
                session, owner_id, workflow_id, uuid4(), bad_revision, bad_step
            )
    with session_factory() as session:
        assert session.scalar(select(WorkflowSuggestionRequestRow)) is None


def test_ready_and_failed_results_replay_same_request_without_provider(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    ready_id = uuid4()
    assert isinstance(
        reserve(session_factory, owner_id, workflow_id, revision, step_id, ready_id),
        SuggestionReservation,
    )
    with session_factory() as session:
        ready = finish_suggestion(
            session,
            owner_id,
            workflow_id,
            ready_id,
            titles=("Choose a date", "Invite guests"),
            error_code=None,
        )
    assert ready is not None
    assert ready.status is SuggestionStatus.READY
    with session_factory() as session:
        replay = reserve_suggestion(
            session, owner_id, workflow_id, ready_id, revision, step_id
        )
    assert replay == ready

    failed_id = uuid4()
    assert isinstance(
        reserve(session_factory, owner_id, workflow_id, revision, step_id, failed_id),
        SuggestionReservation,
    )
    with session_factory() as session:
        failed = finish_suggestion(
            session,
            owner_id,
            workflow_id,
            failed_id,
            titles=None,
            error_code=SuggestionErrorCode.PROVIDER_UNAVAILABLE,
        )
    assert failed is not None
    assert failed.status is SuggestionStatus.FAILED
    with session_factory() as session:
        replay = reserve_suggestion(
            session, owner_id, workflow_id, failed_id, revision, step_id
        )
    assert replay == failed


def test_pending_conflict_request_reuse_and_newer_supersession(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    older_id = uuid4()
    newer_id = uuid4()
    older = reserve(session_factory, owner_id, workflow_id, revision, step_id, older_id)
    assert isinstance(older, SuggestionReservation)
    with session_factory() as session, pytest.raises(SuggestionInProgress):
        reserve_suggestion(session, owner_id, workflow_id, older_id, revision, step_id)

    with session_factory() as session:
        newer = reserve_suggestion(
            session, owner_id, workflow_id, newer_id, revision, step_id
        )
    assert isinstance(newer, SuggestionReservation)
    with session_factory() as session, pytest.raises(StaleSuggestion):
        reserve_suggestion(session, owner_id, workflow_id, older_id, revision, step_id)
    with session_factory() as session:
        rows = session.scalars(
            select(WorkflowSuggestionRequestRow).order_by(WorkflowSuggestionRequestRow.id)
        ).all()
        assert [row.status for row in rows] == [
            SuggestionStatus.SUPERSEDED.value,
            SuggestionStatus.PENDING.value,
        ]

    with session_factory() as session, pytest.raises(RequestIdReused):
        reserve_suggestion(
            session,
            owner_id,
            workflow_id,
            older_id,
            revision,
            f"{workflow_id}:OFFER_BREAKDOWN",
        )


def test_finish_older_after_newer_is_stale_and_does_not_advance_workflow(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    older_id, newer_id = uuid4(), uuid4()
    assert isinstance(reserve(session_factory, owner_id, workflow_id, revision, step_id, older_id), SuggestionReservation)
    assert isinstance(reserve(session_factory, owner_id, workflow_id, revision, step_id, newer_id), SuggestionReservation)

    with session_factory() as session, pytest.raises(StaleSuggestion):
        finish_suggestion(
            session,
            owner_id,
            workflow_id,
            older_id,
            titles=("Invite guests", "Buy cake"),
            error_code=None,
        )
    with session_factory() as session:
        current = get_current_suggestion(session, owner_id, workflow_id)
        assert current is not None
        assert current.request_id == newer_id
        workflow = session.execute(
            text("SELECT revision, state FROM todo_workflows WHERE public_id = :id"),
            {"id": str(workflow_id)},
        ).one()
        assert tuple(workflow) == (revision, "COLLECT_TASKS")


def test_current_get_filters_by_workflow_step_and_revision(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = uuid4()
    assert isinstance(reserve(session_factory, owner_id, workflow_id, revision, step_id, request_id), SuggestionReservation)
    with session_factory() as session:
        assert get_current_suggestion(session, owner_id, workflow_id) is not None
        session.execute(
            text("UPDATE todo_workflows SET revision = revision + 1 WHERE public_id = :id"),
            {"id": str(workflow_id)},
        )
        session.commit()
    with session_factory() as session:
        assert get_current_suggestion(session, owner_id, workflow_id) is None


def test_pending_row_survives_session_crash_shape_and_can_be_superseded(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = uuid4()
    assert isinstance(reserve(session_factory, owner_id, workflow_id, revision, step_id, request_id), SuggestionReservation)
    # A fresh process can observe the pending request, but it is never
    # automatically resumed. An explicit new request supersedes it.
    with session_factory() as session:
        pending = get_current_suggestion(session, owner_id, workflow_id)
    assert pending is not None
    assert pending.status is SuggestionStatus.PENDING
    with session_factory() as session:
        replacement = reserve_suggestion(
            session, owner_id, workflow_id, uuid4(), revision, step_id
        )
    assert isinstance(replacement, SuggestionReservation)


def test_mapper_fails_closed_for_malformed_json_and_status_fields(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = uuid4()
    assert isinstance(reserve(session_factory, owner_id, workflow_id, revision, step_id, request_id), SuggestionReservation)
    with session_factory() as session:
        row = session.scalar(select(WorkflowSuggestionRequestRow))
        assert row is not None
        row.proposed_titles = ["not canonical "]
        with pytest.raises(InvalidStoredSuggestion):
            suggestion_snapshot_from_row(row)


def test_suggestion_table_constraints_and_owner_cascade(
    database_engine: Engine,
) -> None:
    inspector = inspect(database_engine)
    assert inspector.get_table_names().__contains__(
        "todo_workflow_suggestion_requests"
    )
    columns = {
        column["name"]: column
        for column in inspector.get_columns("todo_workflow_suggestion_requests")
    }
    assert list(columns) == [
        "id",
        "owner_id",
        "workflow_id",
        "request_id",
        "request_fingerprint",
        "base_revision",
        "step_id",
        "status",
        "proposed_titles",
        "error_code",
    ]
    assert not {"created_at", "prompt", "raw_output"} & set(columns)
    checks = {
        check["name"] for check in inspector.get_check_constraints(
            "todo_workflow_suggestion_requests"
        )
    }
    assert checks == {
        "ck_suggestion_requests_error_code",
        "ck_suggestion_requests_fingerprint_hex",
        "ck_suggestion_requests_revision_range",
        "ck_suggestion_requests_status",
        "ck_suggestion_requests_status_fields",
        "ck_suggestion_requests_step_id",
        "ck_suggestion_requests_titles_array",
    }


def test_suggestion_rows_round_trip_and_migration_downgrade_preserves_workflow(
    database_engine: Engine,
) -> None:
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    username = f"suggestion-migration-{uuid4()}"
    workflow_id = uuid4()
    request_id = uuid4()
    with database_engine.begin() as connection:
        owner_id = connection.execute(
            text(
                "INSERT INTO users (public_id, username, password_hash) "
                "VALUES (:public_id, :username, 'hash') RETURNING id"
            ),
            {"public_id": uuid4(), "username": username},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO todo_workflows (public_id, owner_id, state, title, "
                "involves_multiple_steps, proposed_todo_titles) VALUES "
                "(:id, :owner_id, 'COLLECT_TASKS', 'Party', true, '[]'::jsonb)"
            ),
            {"id": workflow_id, "owner_id": owner_id},
        )
        connection.execute(
            text(
                "INSERT INTO todo_workflow_suggestion_requests "
                "(owner_id, workflow_id, request_id, request_fingerprint, "
                "base_revision, step_id, status, proposed_titles) VALUES "
                "(:owner_id, :workflow_id, :request_id, :fingerprint, 0, "
                ":step_id, 'ready', '[\"One\", \"Two\"]'::jsonb)"
            ),
            {
                "owner_id": owner_id,
                "workflow_id": workflow_id,
                "request_id": request_id,
                "fingerprint": "a" * 64,
                "step_id": f"{workflow_id}:COLLECT_TASKS",
            },
        )
        config.attributes["connection"] = connection
        command.downgrade(config, "2026090901")
        assert connection.execute(
            text("SELECT count(*) FROM todo_workflows WHERE public_id = :id"),
            {"id": workflow_id},
        ).scalar_one() == 1
        command.upgrade(config, "head")
        assert connection.execute(
            text("SELECT count(*) FROM todo_workflow_suggestion_requests")
        ).scalar_one() == 0
    with database_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM users WHERE username = :username"),
            {"username": username},
        )
