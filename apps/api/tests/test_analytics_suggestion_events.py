"""suggestion_finished is recorded on every terminal path, never on supersede."""

from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker
from test_suggestion_worker import (
    FailingProvider,
    RecordingProvider,
    post_task,
    reserve_for_worker,
    worker_client,
)
from test_workflow_suggestions import make_collecting, reserve, setup_owner

from app.analytics_events import AnalyticsEventRow
from app.suggestion_provider import ProviderUnavailable
from app.suggestion_service import SuggestionErrorCode, finish_suggestion


def _outcomes(session_factory: sessionmaker[Session]) -> list[str | None]:
    with session_factory() as s:
        return list(
            s.scalars(
                select(AnalyticsEventRow.outcome)
                .where(AnalyticsEventRow.event_name == "suggestion_finished")
                .order_by(AnalyticsEventRow.id)
            )
        )


def _expire(session_factory: sessionmaker[Session], row_id: int) -> None:
    with session_factory() as s:
        s.execute(
            text(
                "UPDATE todo_workflow_suggestion_requests "
                "SET queued_at = now() - interval '20 minutes', "
                "expires_at = now() - interval '5 minutes' WHERE id = :id"
            ),
            {"id": row_id},
        )
        s.commit()


def test_worker_ready_records_ready_once_even_when_redelivered(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    row_id = reserve_for_worker(session_factory)
    with worker_client(session_factory, RecordingProvider()) as client:
        assert post_task(client, row_id).status_code == 204
        assert post_task(client, row_id).status_code == 204
    assert _outcomes(session_factory) == ["ready"]


def test_worker_provider_failure_records_failed(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    row_id = reserve_for_worker(session_factory)
    provider = FailingProvider(ProviderUnavailable("synthetic outage"))
    with worker_client(session_factory, provider) as client:
        assert post_task(client, row_id).status_code == 204
    assert _outcomes(session_factory) == ["failed"]


def test_sweep_expiry_records_expired(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    row_id = reserve_for_worker(session_factory)
    _expire(session_factory, row_id)
    with worker_client(session_factory, RecordingProvider()) as client:
        assert client.post("/internal/suggestions/expire", json={}).status_code == 200
    assert _outcomes(session_factory) == ["expired"]


def test_claiming_an_expired_row_records_expired(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    row_id = reserve_for_worker(session_factory)
    _expire(session_factory, row_id)
    provider = RecordingProvider()
    with worker_client(session_factory, provider) as client:
        post_task(client, row_id)
    assert provider.calls == []
    assert _outcomes(session_factory) == ["expired"]


def test_local_finish_records_ready_and_failed_and_supersede_records_nothing(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    superseded_id, ready_id, failed_id = uuid4(), uuid4(), uuid4()
    reserve(session_factory, owner_id, workflow_id, revision, step_id, superseded_id)
    reserve(session_factory, owner_id, workflow_id, revision, step_id, ready_id)
    with session_factory() as s:
        finish_suggestion(
            s, owner_id, workflow_id, ready_id,
            titles=("Choose a date", "Invite guests"), error_code=None,
        )
    reserve(session_factory, owner_id, workflow_id, revision, step_id, failed_id)
    with session_factory() as s:
        finish_suggestion(
            s, owner_id, workflow_id, failed_id,
            titles=None, error_code=SuggestionErrorCode.PROVIDER_UNAVAILABLE,
        )
    assert _outcomes(session_factory) == ["ready", "failed"]
