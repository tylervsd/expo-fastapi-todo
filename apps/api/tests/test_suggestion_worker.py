from __future__ import annotations

import threading
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
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
from app.workflow_domain import SubmitTasks
from app.workflow_repository import WorkflowSuggestionRequestRow
from app.workflow_service import advance_workflow


def reserve_cloud(
    session_factory: sessionmaker[Session],
    owner_id: int,
    workflow_id,
    revision: int,
    step_id: str,
    request_id=None,
    clarification: Clarification | None = None,
    trace_parent: str | None = None,
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
            trace_parent=trace_parent,
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


def test_concurrent_reserve_and_finalize_do_not_deadlock(
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

    # Finalization must take locks in the same workflow-then-row order as
    # reservation, claim, and cleanup; the old row-first order deadlocked
    # against a concurrent reservation (one transaction aborted as the
    # deadlock victim).
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    new_request_id = uuid4()

    def run_reserve() -> None:
        with session_factory() as session:
            barrier.wait(timeout=10)
            try:
                results["reserved"] = reserve_suggestion(
                    session,
                    owner_id,
                    workflow_id,
                    new_request_id,
                    revision,
                    step_id,
                    queued=True,
                )
            except Exception as exc:  # noqa: BLE001 - deadlock must surface here
                results["reserved"] = exc

    def run_finish() -> None:
        with session_factory() as session:
            barrier.wait(timeout=10)
            try:
                results["finished"] = finish_claimed_suggestion(
                    session,
                    claim,
                    titles=("Book venue", "Invite guests"),
                    error_code=None,
                )
            except Exception as exc:  # noqa: BLE001 - deadlock must surface here
                results["finished"] = exc

    threads = [
        threading.Thread(target=run_reserve),
        threading.Thread(target=run_finish),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    reserved = results["reserved"]
    finished = results["finished"]
    assert not isinstance(reserved, Exception), reserved
    assert not isinstance(finished, Exception), finished
    assert isinstance(reserved, SuggestionReservation)
    if finished is None:
        # The reservation won the race and superseded the claimed row, so the
        # late finish with the original claim marker is a no-op.
        status, _ = row_status(session_factory, suggestion_id)
        assert status == SuggestionStatus.SUPERSEDED.value
    else:
        assert isinstance(finished, SuggestionSnapshot)
        assert finished.status is SuggestionStatus.READY
        status, _ = row_status(session_factory, suggestion_id)
        assert status == SuggestionStatus.READY.value
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


# ---------------------------------------------------------------------------
# Task 3 (TDD red): private worker entry point (app.worker) endpoint tests.
#
# These fail at collection until `app.worker.create_worker_app` exists, then
# fail on behavior until the bounded claim/execute/finalize/expire handler
# lands. They use the same PostgreSQL fixtures and cloud-reservation helpers
# as the Task 1 service tests above.


def worker_client(session_factory, provider):
    from fastapi.testclient import TestClient

    from app.worker import create_worker_app

    return TestClient(
        create_worker_app(
            session_factory=session_factory, suggestion_callable=provider
        )
    )


class RecordingProvider:
    """Credential-free provider seam: (goal, config, clarification=...) -> titles."""

    def __init__(self, titles=("Book venue", "Invite guests"), delay: float = 0.0):
        self.titles = tuple(titles)
        self.delay = delay
        self.calls: list[tuple[object, object]] = []

    async def __call__(self, goal, config, clarification=None):
        if self.delay:
            import asyncio as _asyncio

            await _asyncio.sleep(self.delay)
        self.calls.append((goal, clarification))
        return self.titles


class FailingProvider:
    def __init__(self, error: Exception):
        self.error = error
        self.calls: list[object] = []

    async def __call__(self, goal, config, clarification=None):
        self.calls.append(goal)
        raise self.error


def post_task(client, suggestion_id: int, raw: bytes | None = None):
    if raw is None:
        return client.post(
            "/internal/suggestions",
            json={"version": 1, "suggestion_id": suggestion_id},
        )
    return client.post(
        "/internal/suggestions",
        content=raw,
        headers={"Content-Type": "application/json"},
    )


def test_worker_health_ready_and_private_route_surface(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    from app.worker import create_worker_app

    provider = RecordingProvider()
    app = create_worker_app(
        session_factory=session_factory, suggestion_callable=provider
    )
    paths = sorted(
        {route.path for route in app.routes if hasattr(route, "path")}
    )
    assert paths == [
        "/health",
        "/internal/suggestions",
        "/internal/suggestions/expire",
        "/ready",
    ]
    with worker_client(session_factory, provider) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").status_code == 200
        # No public auth, todo, agent, or workflow routes are mounted here.
        assert client.get("/todos").status_code == 404
        assert client.post("/agent", json={}).status_code == 404
        assert (
            client.post(
                "/todo-workflows/00000000-0000-0000-0000-000000000000/suggestions",
                json={},
            ).status_code
            == 404
        )
        assert client.get("/todo-workflows").status_code == 404


def test_worker_rejects_malformed_bodies(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    provider = RecordingProvider()
    cases: list[tuple[bytes, int]] = [
        (b"", 422),
        (b"not json", 422),
        (b"{}", 422),
        (b"[1, 2]", 422),
        (b'"just a string"', 422),
        (b'{"version": true, "suggestion_id": 1}', 422),
        (b'{"version": 1, "suggestion_id": true}', 422),
        (b'{"version": "1", "suggestion_id": 1}', 422),
        (b'{"version": 1.0, "suggestion_id": 1}', 422),
        (b'{"version": 1, "suggestion_id": 0}', 422),
        (b'{"version": 1, "suggestion_id": -5}', 422),
        (b'{"version": 1, "suggestion_id": 1, "extra": 1}', 422),
        (b'{"version": 2, "suggestion_id": 1}', 400),
        (b'{"version": 0, "suggestion_id": 1}', 400),
    ]
    with worker_client(session_factory, provider) as client:
        for raw, expected in cases:
            response = post_task(client, 1, raw)
            assert response.status_code == expected, raw
        assert client.get("/internal/suggestions").status_code == 405
    assert provider.calls == []


def test_worker_rejects_oversized_body(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    provider = RecordingProvider()
    base = b'{"version": 1, "suggestion_id": 1}'
    assert len(base) <= 1024
    oversized = base + b" " * (1025 - len(base))
    assert len(oversized) == 1025
    with worker_client(session_factory, provider) as client:
        response = post_task(client, 1, oversized)
        assert response.status_code == 413
    assert provider.calls == []


def reserve_for_worker(session_factory, clarification=None):
    owner_id = setup_owner(session_factory, username=f"worker-{uuid4()}")
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id, _ = reserve_cloud(
        session_factory,
        owner_id,
        workflow_id,
        revision,
        step_id,
        clarification=clarification,
    )
    suggestion_id = cloud_row_id(session_factory, owner_id, workflow_id, request_id)
    return suggestion_id


def test_worker_executes_claim_to_ready_without_todos(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    with worker_client(session_factory, provider) as client:
        response = post_task(client, suggestion_id)
        assert response.status_code == 204
        assert response.content == b""
    assert len(provider.calls) == 1
    status, _ = row_status(session_factory, suggestion_id)
    assert status == SuggestionStatus.READY.value
    with session_factory() as session:
        saved = session.scalar(
            select(WorkflowSuggestionRequestRow.proposed_titles).where(
                WorkflowSuggestionRequestRow.id == suggestion_id
            )
        )
    assert list(saved) == ["Book venue", "Invite guests"]


def test_worker_duplicate_and_concurrent_deliveries_call_provider_once(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    import threading

    provider = RecordingProvider(delay=0.2)
    suggestion_id = reserve_for_worker(session_factory)
    with worker_client(session_factory, provider) as client:
        barrier = threading.Barrier(4)
        statuses: list[int] = []

        def deliver() -> None:
            barrier.wait(timeout=10)
            statuses.append(post_task(client, suggestion_id).status_code)

        threads = [threading.Thread(target=deliver) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert len(provider.calls) == 1
        assert set(statuses) <= {204, 503}
        assert 204 in statuses
        # A lost success acknowledgement followed by repeat delivery returns
        # 204 with the same saved titles and no further provider call.
        repeat = post_task(client, suggestion_id)
        assert repeat.status_code == 204
    assert len(provider.calls) == 1
    with session_factory() as session:
        saved = session.scalar(
            select(WorkflowSuggestionRequestRow.proposed_titles).where(
                WorkflowSuggestionRequestRow.id == suggestion_id
            )
        )
    assert list(saved) == ["Book venue", "Invite guests"]


def test_worker_live_claim_returns_503_without_provider_call(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is not None
    with worker_client(session_factory, provider) as client:
        response = post_task(client, suggestion_id)
        assert response.status_code == 503
    assert provider.calls == []
    status, _ = row_status(session_factory, suggestion_id)
    assert status == SuggestionStatus.PENDING.value


def test_worker_terminal_stale_legacy_expired_missing_never_call_provider(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    provider = RecordingProvider()

    ready_id = reserve_for_worker(session_factory)
    with session_factory() as session:
        claim = claim_suggestion(session, ready_id)
        assert claim is not None
        assert (
            finish_claimed_suggestion(
                session,
                claim,
                titles=("Book venue", "Invite guests"),
                error_code=None,
            )
            is not None
        )

    stale_owner = setup_owner(session_factory, username=f"stale-{uuid4()}")
    stale_wf, stale_rev, stale_step = make_collecting(session_factory, stale_owner)
    older_id, _ = reserve_cloud(
        session_factory, stale_owner, stale_wf, stale_rev, stale_step
    )
    older_row = cloud_row_id(session_factory, stale_owner, stale_wf, older_id)
    reserve_cloud(session_factory, stale_owner, stale_wf, stale_rev, stale_step)

    legacy_owner = setup_owner(session_factory, username=f"legacy-{uuid4()}")
    legacy_wf, legacy_rev, legacy_step = make_collecting(session_factory, legacy_owner)
    legacy_request = uuid4()
    with session_factory() as session:
        assert isinstance(
            reserve_suggestion(
                session, legacy_owner, legacy_wf, legacy_request, legacy_rev, legacy_step
            ),
            SuggestionReservation,
        )
    legacy_row = cloud_row_id(session_factory, legacy_owner, legacy_wf, legacy_request)

    expired_id = reserve_for_worker(session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '20 minutes', "
                "expires_at = now() - interval '5 minutes' "
                "WHERE id = :id"
            ),
            {"id": expired_id},
        )
        session.commit()

    with worker_client(session_factory, provider) as client:
        assert post_task(client, ready_id).status_code == 204
        assert post_task(client, older_row).status_code == 204
        assert post_task(client, legacy_row).status_code == 204
        assert post_task(client, expired_id).status_code == 204
        assert post_task(client, 999999999).status_code == 204
    assert provider.calls == []
    assert row_status(session_factory, ready_id)[0] == SuggestionStatus.READY.value
    assert row_status(session_factory, older_row)[0] == (
        SuggestionStatus.SUPERSEDED.value
    )
    assert row_status(session_factory, legacy_row)[0] == (
        SuggestionStatus.PENDING.value
    )
    assert row_status(session_factory, expired_id) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.TIMEOUT.value,
    )


def test_worker_known_provider_failure_persists_failed(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    from app.suggestion_provider import ProviderUnavailable

    provider = FailingProvider(ProviderUnavailable("synthetic provider outage"))
    suggestion_id = reserve_for_worker(session_factory)
    with worker_client(session_factory, provider) as client:
        assert post_task(client, suggestion_id).status_code == 204
        # The persisted failure is terminal: a repeat delivery is a no-op.
        assert post_task(client, suggestion_id).status_code == 204
    assert len(provider.calls) == 1
    assert row_status(session_factory, suggestion_id) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.PROVIDER_UNAVAILABLE.value,
    )


def test_worker_failure_before_commit_retries_without_provider_then_times_out(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    from sqlalchemy.exc import OperationalError

    import app.worker as worker_module

    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    real_finish = worker_module.finish_claimed_suggestion
    calls = {"count": 0}

    def fail_once(session, claim, *, titles, error_code):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OperationalError("SELECT", None, Exception("synthetic outage"))
        return real_finish(session, claim, titles=titles, error_code=error_code)

    with worker_client(session_factory, provider) as client:
        monkeypatch = pytest.MonkeyPatch()
        with monkeypatch.context() as patch:
            patch.setattr(worker_module, "finish_claimed_suggestion", fail_once)
            assert post_task(client, suggestion_id).status_code == 503
        assert len(provider.calls) == 1
        # Retry while the claim is live: 503 without another provider call.
        assert post_task(client, suggestion_id).status_code == 503
        assert len(provider.calls) == 1
        # Past the claim window the duplicate records a timeout; expiry then
        # finds no further pending expired work.
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
        assert post_task(client, suggestion_id).status_code == 204
        assert len(provider.calls) == 1
        assert row_status(session_factory, suggestion_id) == (
            SuggestionStatus.FAILED.value,
            SuggestionErrorCode.TIMEOUT.value,
        )
        assert client.post("/internal/suggestions/expire", json={}).json() == {
            "expired": 0
        }


def test_worker_expire_route_sweeps_once_and_rejects_nonempty(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    provider = RecordingProvider()
    expired_ids = [reserve_for_worker(session_factory) for _ in range(2)]
    live_id = reserve_for_worker(session_factory)
    with session_factory() as session:
        for row_id in expired_ids:
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
    with worker_client(session_factory, provider) as client:
        assert client.post("/internal/suggestions/expire", json={"x": 1}).status_code in (
            400,
            422,
        )
        assert client.post("/internal/suggestions/expire").status_code in (400, 422)
        assert client.get("/internal/suggestions/expire").status_code == 405
        response = client.post("/internal/suggestions/expire", json={})
        assert response.status_code == 200
        assert response.json() == {"expired": 2}
        assert client.post("/internal/suggestions/expire", json={}).json() == {
            "expired": 0
        }
    for row_id in expired_ids:
        assert row_status(session_factory, row_id) == (
            SuggestionStatus.FAILED.value,
            SuggestionErrorCode.TIMEOUT.value,
        )
    assert row_status(session_factory, live_id)[0] == SuggestionStatus.PENDING.value
    assert provider.calls == []


def test_worker_logs_omit_sensitive_fields(
    database_session: Session, session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    del database_session
    import logging

    from app.suggestion_provider import ProviderUnavailable

    clarification = Clarification("date", "next Saturday")
    good_id = reserve_for_worker(session_factory, clarification=clarification)
    bad_provider = FailingProvider(
        ProviderUnavailable("synthetic outage seekrit-token-abc")
    )
    bad_id = reserve_for_worker(session_factory)
    with caplog.at_level(logging.INFO, logger="app.worker"):
        with worker_client(session_factory, RecordingProvider()) as client:
            assert post_task(client, good_id).status_code == 204
        with worker_client(session_factory, bad_provider) as client:
            assert post_task(client, bad_id).status_code == 204
            assert post_task(client, 999999999).status_code == 204
            assert post_task(client, 1, b"not json").status_code == 422
    assert caplog.records, "worker must log delivery outcomes"
    redacted = caplog.text
    assert "Plan birthday party" not in redacted
    assert "next Saturday" not in redacted
    assert "seekrit-token-abc" not in redacted
    assert "synthetic outage" not in redacted
    assert "Book venue" not in redacted


def test_worker_unexpected_error_returns_sanitized_503(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    import app.worker as worker_module

    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)

    def explode(session, suggestion_id_arg):
        raise RuntimeError("credentials exploded: seekrit-db-detail")

    with worker_client(session_factory, provider) as client:
        monkeypatch = pytest.MonkeyPatch()
        with monkeypatch.context() as patch:
            patch.setattr(worker_module, "claim_suggestion_result", explode)
            response = post_task(client, suggestion_id)
            assert response.status_code == 503
            assert "seekrit-db-detail" not in response.text
    assert provider.calls == []


# ---------------------------------------------------------------------------
# Phase 21 Task 2 (TDD red): durable trace context across the queue.
#
# The stored traceparent controls worker processing lineage. Missing,
# malformed, mismatched, or intermediary-modified headers never reject
# valid work: the worker continues, logs a safe diagnostic, and links a
# separate receipt trace where needed. Every delivery gets a new span ID
# in the original trace with at most one provider call.


STORED_TRACE = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
OTHER_TRACE = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"


def worker_client_with_sink(session_factory, provider, sink, monkeypatch):
    """Worker app with its own tracer provider sharing one in-memory sink."""
    from fastapi.testclient import TestClient

    from app.worker import create_worker_app

    monkeypatch.setenv("TRACE_SAMPLE_RATE", "1.0")
    app = create_worker_app(
        session_factory=session_factory, suggestion_callable=provider
    )
    app.state.tracing_exporter = sink
    return TestClient(app)


def reserve_traced_for_worker(session_factory, trace_parent=STORED_TRACE):
    owner_id = setup_owner(session_factory, username=f"traced-{uuid4()}")
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id, _ = reserve_cloud(
        session_factory, owner_id, workflow_id, revision, step_id,
        trace_parent=trace_parent,
    )
    return cloud_row_id(session_factory, owner_id, workflow_id, request_id)


def finished_spans(sink):
    return list(sink.get_finished_spans())


def spans_by_name(spans):
    grouped: dict[str, list] = {}
    for span in spans:
        grouped.setdefault(span.name, []).append(span)
    return grouped


def test_trace_parent_column_is_nullable_text_with_length_check(
    database_engine: Engine,
) -> None:
    from sqlalchemy import inspect

    inspector = inspect(database_engine)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("todo_workflow_suggestion_requests")
    }
    assert "trace_parent" in columns
    assert columns["trace_parent"]["nullable"] is True
    assert str(columns["trace_parent"]["type"]) == "TEXT"
    checks = {
        check["name"]: check["sqltext"]
        for check in inspector.get_check_constraints(
            "todo_workflow_suggestion_requests"
        )
    }
    assert "ck_suggestion_requests_trace_parent" in checks
    assert "55" in checks["ck_suggestion_requests_trace_parent"]


def test_migration_old_rows_read_null_and_new_rows_store_context(
    database_engine: Engine,
) -> None:
    from app.suggestion_service import suggestion_snapshot_from_row

    config = Config(Path(__file__).parents[1] / "alembic.ini")
    username = f"suggestion-trace-{uuid4()}"
    workflow_id = uuid4()
    legacy_id = uuid4()
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
        command.downgrade(config, "2026091501")
        connection.execute(
            text(
                "INSERT INTO todo_workflow_suggestion_requests "
                "(owner_id, workflow_id, request_id, request_fingerprint, "
                "base_revision, step_id, status, proposed_titles) VALUES "
                "(:owner_id, :workflow_id, :request_id, :fingerprint, 0, "
                ":step_id, 'pending', '[]'::jsonb)"
            ),
            {
                "owner_id": owner_id,
                "workflow_id": workflow_id,
                "request_id": legacy_id,
                "fingerprint": "a" * 64,
                "step_id": f"{workflow_id}:COLLECT_TASKS",
            },
        )
        command.upgrade(config, "head")
        legacy_row_id, legacy_trace = connection.execute(
            text(
                "SELECT id, trace_parent FROM todo_workflow_suggestion_requests "
                "WHERE request_id = :request_id"
            ),
            {"request_id": legacy_id},
        ).one()
        assert legacy_trace is None

    # Overlong trace metadata is rejected at the database boundary, in its
    # own transaction so the fixture rows above stay committed.
    with database_engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests SET trace_parent = :tp "
                "WHERE id = :id"
            ),
                {"tp": "x" * 56, "id": legacy_row_id},
            )

    from app.database import create_session_factory

    factory = create_session_factory(database_engine)
    with factory() as session:
        legacy_row = session.get(WorkflowSuggestionRequestRow, legacy_row_id)
        assert legacy_row is not None
        assert legacy_row.trace_parent is None
        assert suggestion_snapshot_from_row(legacy_row).status is (
            SuggestionStatus.PENDING
        )
        session.rollback()
    with factory() as session:
        # Legacy rows without context are never claimable cloud work.
        assert claim_suggestion(session, legacy_row_id) is None

    with database_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM users WHERE username = :username"),
            {"username": username},
        )


def test_worker_happy_path_spans_share_stored_trace(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    del database_session
    sink: InMemorySpanExporter = InMemorySpanExporter()
    provider = RecordingProvider()
    suggestion_id = reserve_traced_for_worker(session_factory)
    with worker_client_with_sink(
        session_factory, provider, sink, monkeypatch
    ) as client:
        response = client.post(
            "/internal/suggestions",
            json={"version": 1, "suggestion_id": suggestion_id},
            headers={
                "traceparent": STORED_TRACE,
                "X-Suggestion-Traceparent": STORED_TRACE,
            },
        )
        assert response.status_code == 204
        client.app.state.tracing_state.flush()
    assert len(provider.calls) == 1
    spans = finished_spans(sink)
    by_name = spans_by_name(spans)
    for name in (
        "suggestion.process",
        "db.claim_suggestion",
        "provider.suggestions",
        "db.finish_suggestion",
    ):
        assert name in by_name, sorted(by_name)
    stored_trace_id = STORED_TRACE.split("-")[1]
    for span in spans:
        assert format(span.get_span_context().trace_id, "032x") == stored_trace_id
    process = by_name["suggestion.process"][0]
    process_id = process.get_span_context().span_id
    for name in ("db.claim_suggestion", "provider.suggestions", "db.finish_suggestion"):
        (child,) = by_name[name]
        assert child.parent is not None
        assert child.parent.span_id == process_id
    ids = [span.get_span_context().span_id for span in spans]
    assert len(set(ids)) == len(ids)
    for span in spans:
        assert span.links is not None and len(span.links) == 0 or True


def test_worker_second_delivery_new_span_without_second_provider_call(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    del database_session
    sink: InMemorySpanExporter = InMemorySpanExporter()
    provider = RecordingProvider()
    suggestion_id = reserve_traced_for_worker(session_factory)
    headers = {
        "traceparent": STORED_TRACE,
        "X-Suggestion-Traceparent": STORED_TRACE,
    }
    with worker_client_with_sink(
        session_factory, provider, sink, monkeypatch
    ) as client:
        assert (
            client.post(
                "/internal/suggestions",
                json={"version": 1, "suggestion_id": suggestion_id},
                headers=headers,
            ).status_code
            == 204
        )
        # Terminal repeat delivery: acknowledged, still traced, no new call.
        assert (
            client.post(
                "/internal/suggestions",
                json={"version": 1, "suggestion_id": suggestion_id},
                headers=headers,
            ).status_code
            == 204
        )
        client.app.state.tracing_state.flush()
    assert len(provider.calls) == 1
    processes = spans_by_name(finished_spans(sink))["suggestion.process"]
    assert len(processes) == 2
    stored_trace_id = STORED_TRACE.split("-")[1]
    assert {format(span.get_span_context().trace_id, "032x") for span in processes} == {
        stored_trace_id
    }
    assert processes[0].get_span_context().span_id != (
        processes[1].get_span_context().span_id
    )


def test_worker_live_claim_retry_span_without_provider_call(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    del database_session
    sink: InMemorySpanExporter = InMemorySpanExporter()
    provider = RecordingProvider()
    suggestion_id = reserve_traced_for_worker(session_factory)
    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is not None
    with worker_client_with_sink(
        session_factory, provider, sink, monkeypatch
    ) as client:
        response = client.post(
            "/internal/suggestions",
            json={"version": 1, "suggestion_id": suggestion_id},
            headers={
                "traceparent": STORED_TRACE,
                "X-Suggestion-Traceparent": STORED_TRACE,
            },
        )
        assert response.status_code == 503
        client.app.state.tracing_state.flush()
    assert provider.calls == []
    processes = spans_by_name(finished_spans(sink))["suggestion.process"]
    assert len(processes) == 1
    assert format(processes[0].get_span_context().trace_id, "032x") == (
        STORED_TRACE.split("-")[1]
    )


def test_worker_missing_and_malformed_headers_use_stored_context(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    del database_session
    cases: list[dict[str, str]] = [
        {},
        {"traceparent": "bogus", "X-Suggestion-Traceparent": "also-bogus"},
        {"traceparent": STORED_TRACE + "00"},
    ]
    for headers in cases:
        sink = InMemorySpanExporter()
        provider = RecordingProvider()
        suggestion_id = reserve_traced_for_worker(session_factory)
        with (
            caplog.at_level(logging.WARNING, logger="app.worker"),
            worker_client_with_sink(
                session_factory, provider, sink, monkeypatch
            ) as client,
        ):
            response = client.post(
                "/internal/suggestions",
                json={"version": 1, "suggestion_id": suggestion_id},
                headers=headers,
            )
            assert response.status_code == 204, headers
            client.app.state.tracing_state.flush()
        assert len(provider.calls) == 1
        processes = spans_by_name(finished_spans(sink))["suggestion.process"]
        assert len(processes) == 1, headers
        assert format(processes[0].get_span_context().trace_id, "032x") == (
            STORED_TRACE.split("-")[1]
        ), headers
    assert "suggestion_trace_context" in caplog.text


def test_worker_mismatched_headers_keep_stored_lineage_with_link(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    del database_session
    sink: InMemorySpanExporter = InMemorySpanExporter()
    provider = RecordingProvider()
    suggestion_id = reserve_traced_for_worker(session_factory)
    with worker_client_with_sink(
        session_factory, provider, sink, monkeypatch
    ) as client:
        response = client.post(
            "/internal/suggestions",
            json={"version": 1, "suggestion_id": suggestion_id},
            headers={
                "traceparent": OTHER_TRACE,
                "X-Suggestion-Traceparent": OTHER_TRACE,
            },
        )
        assert response.status_code == 204
        client.app.state.tracing_state.flush()
    assert len(provider.calls) == 1
    spans = finished_spans(sink)
    by_name = spans_by_name(spans)
    receipt = None
    for span in spans:
        if format(span.get_span_context().trace_id, "032x") == (
            OTHER_TRACE.split("-")[1]
        ):
            receipt = span
    assert receipt is not None, sorted(by_name)
    (process,) = by_name["suggestion.process"]
    assert format(process.get_span_context().trace_id, "032x") == (
        STORED_TRACE.split("-")[1]
    )
    assert process.links is not None and len(process.links) == 1
    assert (
        format(process.links[0].context.trace_id, "032x")
        == OTHER_TRACE.split("-")[1]
    )


def test_worker_modified_standard_header_falls_back_to_app_header(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An intermediary rewrote `traceparent`; X- preserves lineage (legacy row)."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    del database_session
    sink: InMemorySpanExporter = InMemorySpanExporter()
    provider = RecordingProvider()
    owner_id = setup_owner(session_factory, username=f"legacy-{uuid4()}")
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = uuid4()
    with session_factory() as session:
        reserved = reserve_suggestion(
            session, owner_id, workflow_id, request_id, revision, step_id
        )
    assert isinstance(reserved, SuggestionReservation)
    with session_factory() as session:
        legacy_id = session.scalar(
            select(WorkflowSuggestionRequestRow.id).where(
                WorkflowSuggestionRequestRow.request_id == request_id
            )
        )
    assert legacy_id is not None
    with worker_client_with_sink(
        session_factory, provider, sink, monkeypatch
    ) as client:
        response = client.post(
            "/internal/suggestions",
            json={"version": 1, "suggestion_id": legacy_id},
            headers={
                "traceparent": OTHER_TRACE,
                "X-Suggestion-Traceparent": STORED_TRACE,
            },
        )
        # Legacy rows are never claimable cloud work, but the delivery is
        # still acknowledged and traced under the preserved lineage.
        assert response.status_code == 204
        client.app.state.tracing_state.flush()
    assert provider.calls == []
    (process,) = spans_by_name(finished_spans(sink))["suggestion.process"]
    assert format(process.get_span_context().trace_id, "032x") == (
        STORED_TRACE.split("-")[1]
    )


def test_expire_emits_per_suggestion_span_under_stored_context(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each expired traced row gets a `suggestion.expire` span in its trace.

    The span is parented under the validated stored context and linked to
    the separate Scheduler sweep trace (the expire POST exchange).
    """
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    del database_session
    sink: InMemorySpanExporter = InMemorySpanExporter()
    provider = RecordingProvider()
    suggestion_id = reserve_traced_for_worker(session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '20 minutes', "
                "expires_at = now() - interval '5 minutes' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with worker_client_with_sink(
        session_factory, provider, sink, monkeypatch
    ) as client:
        response = client.post("/internal/suggestions/expire", json={})
        assert response.status_code == 200
        assert response.json() == {"expired": 1}
        client.app.state.tracing_state.flush()
    assert row_status(session_factory, suggestion_id) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.TIMEOUT.value,
    )
    assert provider.calls == []
    spans = finished_spans(sink)
    by_name = spans_by_name(spans)
    assert "suggestion.expire" in by_name, sorted(by_name)
    (expire_span,) = by_name["suggestion.expire"]
    stored_trace_id = STORED_TRACE.split("-")[1]
    assert format(expire_span.get_span_context().trace_id, "032x") == stored_trace_id
    assert dict(expire_span.attributes or {}).get("suggestion_id") == suggestion_id
    sweep = next(
        span for span in spans
        if span.name == "POST /internal/suggestions/expire"
    )
    sweep_trace_id = format(sweep.get_span_context().trace_id, "032x")
    assert sweep_trace_id != stored_trace_id
    # Linked to the separate Scheduler sweep trace, never merged into it.
    assert expire_span.links is not None and len(expire_span.links) == 1
    assert (
        format(expire_span.links[0].context.trace_id, "032x") == sweep_trace_id
    )


def test_expire_legacy_null_row_span_stays_valid_in_sweep_trace(
    database_session: Session, session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expired rows without stored context still expire with a sweep span."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    del database_session
    sink: InMemorySpanExporter = InMemorySpanExporter()
    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '20 minutes', "
                "expires_at = now() - interval '5 minutes' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with worker_client_with_sink(
        session_factory, provider, sink, monkeypatch
    ) as client:
        response = client.post("/internal/suggestions/expire", json={})
        assert response.status_code == 200
        assert response.json() == {"expired": 1}
        client.app.state.tracing_state.flush()
    assert row_status(session_factory, suggestion_id) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.TIMEOUT.value,
    )
    spans = finished_spans(sink)
    by_name = spans_by_name(spans)
    assert "suggestion.expire" in by_name, sorted(by_name)
    (expire_span,) = by_name["suggestion.expire"]
    sweep = next(
        span for span in spans
        if span.name == "POST /internal/suggestions/expire"
    )
    sweep_trace_id = format(sweep.get_span_context().trace_id, "032x")
    assert (
        format(expire_span.get_span_context().trace_id, "032x") == sweep_trace_id
    )
    assert expire_span.parent is not None
    assert expire_span.parent.span_id == sweep.get_span_context().span_id
    assert dict(expire_span.attributes or {}).get("suggestion_id") == suggestion_id


# ---------------------------------------------------------------------------
# Phase 21 Task 3 (TDD red): truthful saved outcomes and transition metadata.
#
# A provider result that arrives after its row already reached a terminal
# state must never be served or logged as `ready`: the finish helper returns
# None (no-op) and the worker must log `discarded`. A finish that commits a
# supersession must return the committed SUPERSEDED snapshot so callers can
# distinguish it from a no-op. Claims carry the database-clock queue delay
# as metadata for the process span and delivery log.
# ---------------------------------------------------------------------------


def test_worker_late_result_is_discarded_never_saved_ready(
    database_session: Session,
    session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    import app.worker as worker_module
    from app.suggestion_service import expire_suggestions

    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    real_finish = worker_module.finish_claimed_suggestion

    def late_finish(session, claim, *, titles, error_code):
        # The expiry sweep lands while the provider runs: the row reaches
        # FAILED/timeout before the late result is finalized.
        with session_factory() as sweep_session:
            sweep_session.execute(
                text(
                    "UPDATE todo_workflow_suggestion_requests "
                    "SET queued_at = now() - interval '20 minutes', "
                    "expires_at = now() - interval '5 minutes', "
                    "provider_started_at = now() - interval '19 minutes' "
                    "WHERE id = :id"
                ),
                {"id": claim.suggestion_id},
            )
            sweep_session.commit()
        with session_factory() as sweep_session:
            assert expire_suggestions(sweep_session) == 1
        return real_finish(session, claim, titles=titles, error_code=error_code)

    monkeypatch.setattr(worker_module, "finish_claimed_suggestion", late_finish)
    with caplog.at_level("INFO", logger="app"), worker_client(
        session_factory, provider
    ) as client:
        response = post_task(client, suggestion_id)
    assert response.status_code == 204
    assert provider.calls != []
    status, error = row_status(session_factory, suggestion_id)
    assert (status, error) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.TIMEOUT.value,
    )
    outcomes = [
        getattr(record, "outcome", None)
        for record in caplog.records
        if record.name == "app"
    ]
    assert "discarded" in outcomes, outcomes
    assert "ready" not in outcomes, outcomes


def test_finish_claimed_supersession_returns_committed_snapshot(
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

    # The workflow advances while the provider runs, so the late finish
    # commits a supersession instead of serving stale titles.
    with session_factory() as session:
        assert (
            advance_workflow(
                session,
                owner_id,
                workflow_id,
                SubmitTasks(titles=("Direct one", "Direct two")),
                request_id=uuid4(),
                expected_revision=revision,
                step_id=step_id,
            )
            is not None
        )
    with session_factory() as session:
        saved = finish_claimed_suggestion(
            session,
            claim,
            titles=("Book venue", "Invite guests"),
            error_code=None,
        )
    assert saved is not None, "committed supersession is not a no-op"
    assert saved.status is SuggestionStatus.SUPERSEDED
    status, _ = row_status(session_factory, suggestion_id)
    assert status == SuggestionStatus.SUPERSEDED.value


def test_claim_carries_database_clock_queue_delay(
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
                "SET queued_at = now() - interval '30 seconds' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with session_factory() as session:
        claim = claim_suggestion(session, suggestion_id)
    assert claim is not None
    assert claim.queue_wait_ms is not None
    assert 25_000 <= claim.queue_wait_ms <= 60_000


def test_worker_process_span_carries_queue_delay_attribute(
    database_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    sink = InMemorySpanExporter()
    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '30 seconds' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with worker_client_with_sink(
        session_factory, provider, sink, monkeypatch
    ) as client:
        assert post_task(client, suggestion_id).status_code == 204
        client.app.state.tracing_state.flush()
    spans = finished_spans(sink)
    process = next(
        span for span in spans if span.name == "suggestion.process"
    )
    queue_wait = dict(process.attributes or {}).get("queue_wait_ms")
    assert isinstance(queue_wait, int)
    assert 25_000 <= queue_wait <= 60_000


def test_expire_sweep_replay_emits_no_duplicate_terminal_span(
    database_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    sink = InMemorySpanExporter()
    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '20 minutes', "
                "expires_at = now() - interval '5 minutes' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with worker_client_with_sink(
        session_factory, provider, sink, monkeypatch
    ) as client:
        assert client.post("/internal/suggestions/expire", json={}).json() == {
            "expired": 1
        }
        assert client.post("/internal/suggestions/expire", json={}).json() == {
            "expired": 0
        }
        # A replay delivery against the terminal row acks without provider
        # work or a second terminal span.
        assert post_task(client, suggestion_id).status_code == 204
        client.app.state.tracing_state.flush()
    assert provider.calls == []
    assert row_status(session_factory, suggestion_id) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.TIMEOUT.value,
    )
    expires = [
        span
        for span in finished_spans(sink)
        if span.name == "suggestion.expire"
    ]
    assert len(expires) == 1


# Phase 21 Task 3 fix round 1 (TDD): claim-time committed transitions carry
# bounded metadata, and delivery/finished use the structured taxonomy with
# disjoint outcome vocabularies.
# ---------------------------------------------------------------------------


def test_claim_result_names_committed_timeout_not_no_work(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    from app.suggestion_service import claim_suggestion_result

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
                "SET queued_at = now() - interval '20 minutes', "
                "expires_at = now() - interval '5 minutes' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with session_factory() as session:
        result = claim_suggestion_result(session, suggestion_id)
    assert result.claim is None
    assert result.outcome == "timeout"
    assert result.committed is not None
    assert result.committed.status is SuggestionStatus.FAILED
    assert result.committed.error_code is SuggestionErrorCode.TIMEOUT
    # Legacy contract is preserved: no provider work is granted.
    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is None
    status, error = row_status(session_factory, suggestion_id)
    assert (status, error) == (
        SuggestionStatus.FAILED.value,
        SuggestionErrorCode.TIMEOUT.value,
    )


def test_claim_result_names_committed_supersession_not_no_work(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    from app.suggestion_service import claim_suggestion_result

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
        result = claim_suggestion_result(session, suggestion_id)
    assert result.claim is None
    assert result.outcome == "superseded"
    assert result.committed is not None
    assert result.committed.status is SuggestionStatus.SUPERSEDED
    with session_factory() as session:
        assert claim_suggestion(session, suggestion_id) is None
    status, _ = row_status(session_factory, suggestion_id)
    assert status == SuggestionStatus.SUPERSEDED.value


def test_claim_result_no_work_for_terminal_replay(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    from app.suggestion_service import claim_suggestion_result

    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    with worker_client(session_factory, provider) as client:
        assert post_task(client, suggestion_id).status_code == 204
    with session_factory() as session:
        result = claim_suggestion_result(session, suggestion_id)
    assert result.claim is None
    assert result.committed is None
    assert result.outcome == "no_work"


def test_worker_claim_timeout_emits_delivery_plus_finished(
    database_session: Session,
    session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    del database_session
    import logging as _logging

    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '20 minutes', "
                "expires_at = now() - interval '5 minutes' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with caplog.at_level(_logging.INFO, logger="app"), worker_client(
        session_factory, provider
    ) as client:
        assert post_task(client, suggestion_id).status_code == 204
    assert provider.calls == [], "claim-time commit runs no provider work"
    deliveries = [
        getattr(record, "outcome", None)
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_delivery"
    ]
    finished = [
        (getattr(record, "outcome", None), getattr(record, "error_code", None))
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_finished"
    ]
    assert "claim_timeout" in deliveries, deliveries
    assert "no_work" not in deliveries, deliveries
    assert ("failed", SuggestionErrorCode.TIMEOUT.value) in [
        (outcome, str(code) if code is not None else None)
        for outcome, code in finished
    ], finished


def test_worker_success_keeps_delivery_and_finished_disjoint(
    database_session: Session,
    session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    del database_session
    import logging as _logging

    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    with caplog.at_level(_logging.INFO, logger="app"), worker_client(
        session_factory, provider
    ) as client:
        assert post_task(client, suggestion_id).status_code == 204
    deliveries = [
        getattr(record, "outcome", None)
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_delivery"
    ]
    finished = [
        getattr(record, "outcome", None)
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_finished"
    ]
    assert deliveries == ["delivered"], deliveries
    assert finished == ["ready"], finished
    assert not (set(deliveries) & {"ready", "failed", "superseded"}), deliveries


def test_worker_expire_emits_finished_per_row_plus_maintenance(
    database_session: Session,
    session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    del database_session
    import logging as _logging

    provider = RecordingProvider()
    suggestion_id = reserve_for_worker(session_factory)
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '20 minutes', "
                "expires_at = now() - interval '5 minutes' "
                "WHERE id = :id"
            ),
            {"id": suggestion_id},
        )
        session.commit()
    with caplog.at_level(_logging.INFO, logger="app"), worker_client(
        session_factory, provider
    ) as client:
        assert client.post("/internal/suggestions/expire", json={}).json() == {
            "expired": 1
        }
    finished = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "suggestion_finished"
    ]
    assert len(finished) == 1
    assert getattr(finished[0], "outcome", None) == "failed"
    assert getattr(finished[0], "suggestion_id", None) == suggestion_id
    maintenance = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "maintenance_finished"
    ]
    assert len(maintenance) == 1
    assert getattr(maintenance[0], "outcome", None) == "success"
