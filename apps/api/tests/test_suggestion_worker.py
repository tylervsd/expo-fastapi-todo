from __future__ import annotations

import threading
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from test_workflow_suggestions import make_collecting, setup_owner

from alembic import command
from app.suggestion_service import (
    Clarification,
    InvalidStoredSuggestion,
    SuggestionErrorCode,
    SuggestionInProgress,
    SuggestionReservation,
    SuggestionSnapshot,
    SuggestionStatus,
    claim_suggestion,
    expire_suggestions,
    finish_claimed_suggestion,
    reserve_suggestion,
)
from app.todo_repository import TodoRow
from app.workflow_repository import WorkflowSuggestionRequestRow


def reserve_cloud(
    session_factory: sessionmaker[Session],
    owner_id: int,
    workflow_id,
    revision: int,
    step_id: str,
    request_id=None,
    clarification: Clarification | None = None,
):
    request_id = request_id or uuid4()
    with session_factory() as session:
        result = reserve_suggestion(
            session,
            owner_id,
            workflow_id,
            request_id,
            revision,
            step_id,
            clarification=clarification,
            queued=True,
        )
    assert isinstance(result, SuggestionReservation)
    return request_id, result


def cloud_row_id(
    session_factory: sessionmaker[Session],
    owner_id: int,
    workflow_id,
    request_id,
) -> int:
    with session_factory() as session:
        row_id = session.scalar(
            select(WorkflowSuggestionRequestRow.id).where(
                WorkflowSuggestionRequestRow.owner_id == owner_id,
                WorkflowSuggestionRequestRow.workflow_id == workflow_id,
                WorkflowSuggestionRequestRow.request_id == request_id,
            )
        )
    assert row_id is not None
    return row_id


def todo_count(session_factory: sessionmaker[Session], owner_id: int) -> int:
    with session_factory() as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(TodoRow)
                .where(TodoRow.owner_id == owner_id)
            )
            or 0
        )


def row_status(
    session_factory: sessionmaker[Session], row_id: int
) -> tuple[str, str | None]:
    with session_factory() as session:
        row = session.get(WorkflowSuggestionRequestRow, row_id)
        assert row is not None
        return row.status, row.error_code


def test_claim_finish_lifecycle_marks_ready_without_todos(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id, _ = reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id
    )
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)

    with session_factory() as session:
        claim = claim_suggestion(session, suggestion_id)
    assert claim is not None
    assert claim.suggestion_id == suggestion_id
    assert claim.owner_id == owner_id
    assert claim.reservation.request_id == request_id
    assert claim.provider_started_at is not None
    with session_factory() as session, pytest.raises(SuggestionInProgress):
        claim_suggestion(session, suggestion_id)
    with session_factory() as session:
        saved = finish_claimed_suggestion(
            session,
            claim,
            titles=("Book venue", "Invite guests"),
            error_code=None,
        )
    assert saved is not None
    assert saved.status is SuggestionStatus.READY
    assert saved.proposed_titles == ("Book venue", "Invite guests")
    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is None
    assert todo_count(session_factory, owner_id) == 0
    status, _ = row_status(session_factory, suggestion_id)
    assert status == SuggestionStatus.READY.value


def test_concurrent_claims_allow_exactly_one_provider_attempt(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id, _ = reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id
    )
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)

    barrier = threading.Barrier(2)
    outcomes: list[object] = []

    def attempt() -> None:
        with session_factory() as session:
            barrier.wait(timeout=10)
            try:
                outcomes.append(claim_suggestion(session, suggestion_id))
            except SuggestionInProgress as exc:
                outcomes.append(exc)
            except Exception as exc:  # noqa: BLE001 - record unexpected failure
                outcomes.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    claims = [outcome for outcome in outcomes if outcome is not None and not isinstance(outcome, Exception)]
    conflicts = [
        outcome for outcome in outcomes if isinstance(outcome, SuggestionInProgress)
    ]
    assert len(claims) == 1
    assert len(conflicts) == 1
    assert todo_count(session_factory, owner_id) == 0


def test_changed_fingerprint_is_not_claimable(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id, _ = reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id
    )
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)

    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET request_fingerprint = :fingerprint WHERE id = :id"
            ),
            {"fingerprint": "b" * 64, "id": suggestion_id},
        )
        session.commit()

    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is None
    status, _ = row_status(session_factory, suggestion_id)
    assert status == SuggestionStatus.SUPERSEDED.value
    assert todo_count(session_factory, owner_id) == 0


def test_cancelled_workflow_is_not_claimable(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id, _ = reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id
    )
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)

    with session_factory() as session:
        session.execute(
            text("UPDATE todo_workflows SET state = 'CANCELLED' WHERE public_id = :id"),
            {"id": str(workflow_id)},
        )
        session.commit()

    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is None
    status, _ = row_status(session_factory, suggestion_id)
    assert status == SuggestionStatus.SUPERSEDED.value
    assert todo_count(session_factory, owner_id) == 0


def test_superseded_request_is_not_claimable(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    older_id, _ = reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id
    )
    older_row = cloud_row_id(session_factory, owner_id, workflow_id, older_id)
    reserve_cloud(session_factory, owner_id, workflow_id, revision, step_id)

    with session_factory() as session:
        assert claim_suggestion(session, older_row) is None
    status, _ = row_status(session_factory, older_row)
    assert status == SuggestionStatus.SUPERSEDED.value
    assert todo_count(session_factory, owner_id) == 0


def test_expiry_boundary_and_stale_finish_after_expiry(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id, _ = reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id
    )
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)

    # A reservation well within its useful lifetime is still claimable.
    with session_factory() as session:
        claim = claim_suggestion(session, suggestion_id)
    assert claim is not None

    # Move the reservation past its database deadline: the sweep records the
    # timeout and a late finish with the original claim marker is a no-op.
    # The whole reservation travels back coherently so timestamp ordering
    # checks stay satisfied.
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '20 minutes', "
                "expires_at = now() - interval '5 minutes', "
                "provider_started_at = now() - interval '19 minutes' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with session_factory() as session:
        assert expire_suggestions(session) == 1
    status, error = row_status(session_factory, suggestion_id)
    assert (status, error) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.TIMEOUT.value,
    )
    with session_factory() as session:
        assert (
            finish_claimed_suggestion(
                session,
                claim,
                titles=("Book venue", "Invite guests"),
                error_code=None,
            )
            is None
        )
    status, error = row_status(session_factory, suggestion_id)
    assert (status, error) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.TIMEOUT.value,
    )
    assert todo_count(session_factory, owner_id) == 0


def test_claim_window_is_permanent_and_never_reclaimed(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id, _ = reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id
    )
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)

    with session_factory() as session:
        claim = claim_suggestion(session, suggestion_id)
    assert claim is not None
    marker = claim.provider_started_at

    # A duplicate delivery inside the claim window must not execute.
    with session_factory() as session, pytest.raises(SuggestionInProgress):
        claim_suggestion(session, suggestion_id)

    # Past the claim window the duplicate records a timeout instead of a
    # replacement claim; the permanent marker is never reset. The claim
    # travels back coherently so timestamp ordering checks stay satisfied.
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '10 minutes', "
                "expires_at = queued_at + interval '15 minutes', "
                "provider_started_at = now() - interval '3 minutes' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is None
    status, error = row_status(session_factory, suggestion_id)
    assert (status, error) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.TIMEOUT.value,
    )
    with session_factory() as session:
        row = session.get(WorkflowSuggestionRequestRow, suggestion_id)
        assert row is not None
        assert row.provider_started_at is not None
        assert row.provider_started_at < marker
    # The timed-out row is terminal: later duplicates still do nothing and a
    # stale finish with the original claim marker cannot overwrite the failure.
    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is None
        assert (
            finish_claimed_suggestion(
                session,
                claim,
                titles=("Book venue", "Invite guests"),
                error_code=None,
            )
            is None
        )
    assert todo_count(session_factory, owner_id) == 0


def test_cloud_replay_returns_snapshot_without_extending_deadline(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = uuid4()
    with session_factory() as session:
        first = reserve_suggestion(
            session, owner_id, workflow_id, request_id, revision, step_id, queued=True
        )
    assert isinstance(first, SuggestionReservation)
    with session_factory() as session:
        before = session.scalar(
            select(
                WorkflowSuggestionRequestRow.queued_at,
                WorkflowSuggestionRequestRow.expires_at,
            ).where(WorkflowSuggestionRequestRow.request_id == request_id)
        )
    assert before is not None
    with session_factory() as session:
        replay = reserve_suggestion(
            session, owner_id, workflow_id, request_id, revision, step_id, queued=True
        )
    assert isinstance(replay, SuggestionSnapshot)
    assert replay.status is SuggestionStatus.PENDING
    with session_factory() as session:
        after = session.scalar(
            select(
                WorkflowSuggestionRequestRow.queued_at,
                WorkflowSuggestionRequestRow.expires_at,
            ).where(WorkflowSuggestionRequestRow.request_id == request_id)
        )
    assert after == before
    assert todo_count(session_factory, owner_id) == 0


def test_legacy_pending_replay_still_conflicts(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = uuid4()
    with session_factory() as session:
        first = reserve_suggestion(
            session, owner_id, workflow_id, request_id, revision, step_id
        )
    assert isinstance(first, SuggestionReservation)
    with session_factory() as session, pytest.raises(SuggestionInProgress):
        reserve_suggestion(session, owner_id, workflow_id, request_id, revision, step_id)


def test_legacy_rows_are_never_claimable_cloud_work(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = uuid4()
    with session_factory() as session:
        reserved = reserve_suggestion(
            session, owner_id, workflow_id, request_id, revision, step_id
        )
    assert isinstance(reserved, SuggestionReservation)
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)
    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is None
    status, _ = row_status(session_factory, suggestion_id)
    assert status == SuggestionStatus.PENDING.value


def test_expire_sweep_bounds_skips_and_excludes(
    database_session: Session,
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)

    def expired_pair() -> tuple[object, int]:
        workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
        request_id, _ = reserve_cloud(
            session_factory, owner_id, workflow_id, revision, step_id
        )
        row_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)
        with session_factory() as session:
            session.execute(
                text(
                    "UPDATE todo_workflow_suggestion_requests "
                    "SET queued_at = now() - interval '20 minutes', "
                    "expires_at = now() - interval '5 minutes' "
                    "WHERE id = :id"
                ),
                {"id": row_id},
            )
            session.commit()
        return workflow_id, row_id

    expired = [expired_pair() for _ in range(101)]

    # Live cloud row, live claim, terminal row, and legacy row are excluded.
    live_wf, live_rev, live_step = make_collecting(session_factory, owner_id)
    live_request, _ = reserve_cloud(
        session_factory, owner_id, live_wf, live_rev, live_step
    )
    live_id = cloud_row_id(session_factory, owner_id, live_wf, live_request)
    claimed_wf, claimed_rev, claimed_step = make_collecting(
        session_factory, owner_id
    )
    claimed_request, _ = reserve_cloud(
        session_factory, owner_id, claimed_wf, claimed_rev, claimed_step
    )
    claimed_id = cloud_row_id(
        session_factory, owner_id, claimed_wf, claimed_request
    )
    with session_factory() as session:
        live_claim = claim_suggestion(session, claimed_id)
    assert live_claim is not None
    done_wf, done_rev, done_step = make_collecting(session_factory, owner_id)
    done_request, _ = reserve_cloud(
        session_factory, owner_id, done_wf, done_rev, done_step
    )
    done_id = cloud_row_id(session_factory, owner_id, done_wf, done_request)
    with session_factory() as session:
        done_claim = claim_suggestion(session, done_id)
    assert done_claim is not None
    with session_factory() as session:
        done_saved = finish_claimed_suggestion(
            session,
            done_claim,
            titles=("Book venue", "Invite guests"),
            error_code=None,
        )
    assert done_saved is not None
    legacy_wf, legacy_rev, legacy_step = make_collecting(session_factory, owner_id)
    legacy_request = uuid4()
    with session_factory() as session:
        legacy_reserved = reserve_suggestion(
            session, owner_id, legacy_wf, legacy_request, legacy_rev, legacy_step
        )
    assert isinstance(legacy_reserved, SuggestionReservation)
    legacy_id = cloud_row_id(session_factory, owner_id, legacy_wf, legacy_request)

    # Lock the newest expired workflow out of the sweep: the first batch
    # still expires 100 rows and skips the locked one.
    locked_workflow, locked_row = expired[-1]
    holder = database_engine.connect()
    holder_tx = holder.begin()
    try:
        holder.execute(
            text("SELECT id FROM todo_workflows WHERE public_id = :id FOR UPDATE"),
            {"id": str(locked_workflow)},
        )
        with session_factory() as session:
            assert expire_suggestions(session) == 100
    finally:
        holder_tx.rollback()
        holder.close()

    with session_factory() as session:
        assert expire_suggestions(session) == 1
    with session_factory() as session:
        assert expire_suggestions(session) == 0

    for _, row_id in expired:
        status, error = row_status(session_factory, row_id)
        assert (status, error) == (
            SuggestionStatus.FAILED.value,
            SuggestionErrorCode.TIMEOUT.value,
        )
    status, _ = row_status(session_factory, locked_row)
    assert status == SuggestionStatus.FAILED.value
    assert row_status(session_factory, live_id)[0] == (
        SuggestionStatus.PENDING.value
    )
    assert row_status(session_factory, claimed_id)[0] == (
        SuggestionStatus.PENDING.value
    )
    assert row_status(session_factory, done_id)[0] == (
        SuggestionStatus.READY.value
    )
    assert row_status(session_factory, legacy_id)[0] == (
        SuggestionStatus.PENDING.value
    )
    assert todo_count(session_factory, owner_id) == 0


def test_expire_and_finish_race_is_safe_without_sleeping(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id, _ = reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id
    )
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)
    with session_factory() as session:
        claim = claim_suggestion(session, suggestion_id)
    assert claim is not None

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def run_expire() -> None:
        with session_factory() as session:
            barrier.wait(timeout=10)
            results["expired"] = expire_suggestions(session)

    def run_finish() -> None:
        with session_factory() as session:
            barrier.wait(timeout=10)
            results["finished"] = finish_claimed_suggestion(
                session,
                claim,
                titles=("Book venue", "Invite guests"),
                error_code=None,
            )

    threads = [
        threading.Thread(target=run_expire),
        threading.Thread(target=run_finish),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert results["expired"] == 0
    finished = results["finished"]
    assert isinstance(finished, SuggestionSnapshot)
    assert finished.status is SuggestionStatus.READY
    assert todo_count(session_factory, owner_id) == 0


def test_clarification_snapshot_round_trip_and_fail_closed(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    clarification = Clarification("date", "next Saturday")
    request_id, _ = reserve_cloud(
        session_factory,
        owner_id,
        workflow_id,
        revision,
        step_id,
        clarification=clarification,
    )
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)

    with session_factory() as session:
        stored = session.scalar(
            select(WorkflowSuggestionRequestRow.clarification_snapshot).where(
                WorkflowSuggestionRequestRow.id == suggestion_id
            )
        )
    assert stored == {"field": "date", "value": "next Saturday"}
    with session_factory() as session:
        claim = claim_suggestion(session, suggestion_id)
    assert claim is not None
    assert claim.reservation.clarification == clarification

    corrupt_request = uuid4()
    reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id,
        request_id=corrupt_request,
    )
    with session_factory() as session:
        latest_id = cloud_row_id(
            session_factory, owner_id, workflow_id, corrupt_request
        )
        assert latest_id is not None
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET clarification_snapshot = :payload WHERE id = :id"
            ),
            {"payload": '{"field": "when", "value": "soon"}', "id": latest_id},
        )
        session.commit()
    with session_factory() as session, pytest.raises(InvalidStoredSuggestion):
        claim_suggestion(session, latest_id)
    assert todo_count(session_factory, owner_id) == 0


def test_execution_columns_constraints_and_partial_index(
    database_engine: Engine,
) -> None:
    from sqlalchemy import inspect

    inspector = inspect(database_engine)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("todo_workflow_suggestion_requests")
    }
    for name in (
        "queued_at",
        "expires_at",
        "provider_started_at",
        "goal_snapshot",
        "clarification_snapshot",
    ):
        assert name in columns, name
        assert columns[name]["nullable"] is True, name
    assert columns["queued_at"]["type"].timezone is True
    assert columns["expires_at"]["type"].timezone is True
    assert columns["provider_started_at"]["type"].timezone is True
    assert str(columns["goal_snapshot"]["type"]) == "TEXT"
    assert str(columns["clarification_snapshot"]["type"]) == "JSONB"

    checks = {
        check["name"]
        for check in inspector.get_check_constraints(
            "todo_workflow_suggestion_requests"
        )
    }
    assert {
        "ck_suggestion_requests_execution_coherent",
        "ck_suggestion_requests_expiry_order",
        "ck_suggestion_requests_claim_order",
        "ck_suggestion_requests_goal_snapshot",
        "ck_suggestion_requests_clarification_object",
    } <= checks

    with database_engine.connect() as connection:
        indexdef = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = "
                "'todo_workflow_suggestion_requests' AND indexname = "
                "'ix_suggestion_requests_pending_cloud_expiry'"
            )
        ).scalar_one()
    assert "WHERE" in indexdef and "pending" in indexdef


def test_migration_legacy_rows_stay_readable_but_not_claimable(
    database_engine: Engine,
) -> None:
    from app.suggestion_service import suggestion_snapshot_from_row

    config = Config(Path(__file__).parents[1] / "alembic.ini")
    username = f"suggestion-exec-{uuid4()}"
    workflow_id = uuid4()
    ready_id = uuid4()
    pending_id = uuid4()
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
        config.attributes["connection"] = connection
        command.downgrade(config, "2026091001")
        for request_id, status, titles in (
            (ready_id, "ready", '["One", "Two"]'),
            (pending_id, "pending", "[]"),
        ):
            connection.execute(
                text(
                    "INSERT INTO todo_workflow_suggestion_requests "
                    "(owner_id, workflow_id, request_id, request_fingerprint, "
                    "base_revision, step_id, status, proposed_titles) VALUES "
                    "(:owner_id, :workflow_id, :request_id, :fingerprint, 0, "
                    ":step_id, :status, CAST(:titles AS jsonb))"
                ),
                {
                    "owner_id": owner_id,
                    "workflow_id": workflow_id,
                    "request_id": request_id,
                    "fingerprint": "a" * 64,
                    "step_id": f"{workflow_id}:COLLECT_TASKS",
                    "status": status,
                    "titles": titles,
                },
            )
        command.upgrade(config, "head")

        ready_row_id = connection.execute(
            text(
                "SELECT id FROM todo_workflow_suggestion_requests "
                "WHERE request_id = :request_id"
            ),
            {"request_id": ready_id},
        ).scalar_one()
        pending_row_id = connection.execute(
            text(
                "SELECT id FROM todo_workflow_suggestion_requests "
                "WHERE request_id = :request_id"
            ),
            {"request_id": pending_id},
        ).scalar_one()

    from app.database import create_session_factory

    factory = create_session_factory(database_engine)
    with factory() as session:
        ready_row = session.get(WorkflowSuggestionRequestRow, ready_row_id)
        assert ready_row is not None
        assert suggestion_snapshot_from_row(ready_row).status is (
            SuggestionStatus.READY
        )
    with factory() as session:
        assert claim_suggestion(session, pending_row_id) is None
    with factory() as session:
        assert claim_suggestion(session, ready_row_id) is None

    with database_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM users WHERE username = :username"),
            {"username": username},
        )
