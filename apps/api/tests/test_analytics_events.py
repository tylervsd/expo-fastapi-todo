from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.analytics_events import AnalyticsEventRow, record_event
from app.auth_repository import create_user
from app.main import create_app
from app.workflow_domain import AnswerMultipleSteps, Confirm, WorkflowState
from app.workflow_service import advance_workflow, start_workflow


def _events(session_factory: sessionmaker[Session]) -> list[tuple[str, str | None]]:
    with session_factory() as s:
        return [
            (row.event_name, row.outcome)
            for row in s.scalars(
                select(AnalyticsEventRow).order_by(AnalyticsEventRow.id)
            )
        ]


def _owner(session_factory: sessionmaker[Session]) -> int:
    with session_factory() as s:
        user = create_user(s, uuid4(), f"u{uuid4().hex[:8]}", "hash")
        s.commit()
        return user.id


@pytest.fixture
def client(
    database_session: Session, session_factory: sessionmaker[Session]
) -> Iterator[TestClient]:
    del database_session
    with TestClient(create_app(session_factory)) as test_client:
        yield test_client


def test_record_event_resolves_user_key_and_defaults(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    user = create_user(database_session, uuid4(), "owner", "hash")
    database_session.flush()
    record_event(database_session, "user_signed_up", user.id)
    database_session.commit()
    with session_factory() as s:
        row = s.scalars(select(AnalyticsEventRow)).one()
    assert row.user_key == user.public_id
    assert row.event_id is not None and row.schema_version == 1
    assert row.occurred_at is not None and row.exported_at is None


def test_record_event_rejects_unknown_name(database_session: Session) -> None:
    with pytest.raises(ValueError):
        record_event(database_session, "page_viewed", 1)


def test_event_is_absent_after_rollback(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    user = create_user(database_session, uuid4(), "owner", "hash")
    database_session.commit()
    record_event(database_session, "workflow_started", user.id, workflow_key=uuid4())
    database_session.rollback()
    assert _events(session_factory) == []


@pytest.mark.parametrize(
    ("name", "outcome"),
    [
        ("page_viewed", None),
        ("suggestion_finished", None),
        ("suggestion_finished", "superseded"),
        ("workflow_started", "ready"),
    ],
)
def test_database_rejects_invalid_events(
    database_session: Session, name: str, outcome: str | None
) -> None:
    user = create_user(database_session, uuid4(), "owner", "hash")
    database_session.commit()
    with pytest.raises(IntegrityError):
        database_session.execute(
            text(
                "INSERT INTO analytics_events (event_id, event_name, user_key, outcome) "
                "VALUES (:id, :name, :key, :outcome)"
            ),
            {"id": uuid4(), "name": name, "key": user.public_id, "outcome": outcome},
        )


def test_signup_records_one_event_and_taken_username_records_none(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    body = {"username": "analyst-a", "password": "correct horse battery"}
    assert client.post("/auth/signup", json=body).status_code == 201
    assert client.post("/auth/signup", json=body).status_code == 422
    assert _events(session_factory) == [("user_signed_up", None)]


def test_start_workflow_records_once_and_replay_records_nothing(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = _owner(session_factory)
    request_id = uuid4()
    with session_factory() as s:
        snapshot = start_workflow(s, owner_id, "Plan party", request_id)
    with session_factory() as s:
        start_workflow(s, owner_id, "Plan party", request_id)
    assert _events(session_factory) == [("workflow_started", None)]
    with session_factory() as s:
        assert s.scalars(select(AnalyticsEventRow.workflow_key)).one() == snapshot.id


def test_only_the_completing_action_records_workflow_completed(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = _owner(session_factory)
    with session_factory() as s:
        snapshot = start_workflow(s, owner_id, "Plan party", uuid4())
    with session_factory() as s:
        review = advance_workflow(
            s, owner_id, snapshot.id, AnswerMultipleSteps(answer=False),
            request_id=uuid4(), expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )
    assert review is not None and review.state == WorkflowState.REVIEW
    assert _events(session_factory) == [("workflow_started", None)]
    final_request = uuid4()
    for _ in range(2):  # second call is an idempotent replay
        with session_factory() as s:
            done = advance_workflow(
                s, owner_id, snapshot.id, Confirm(),
                request_id=final_request, expected_revision=1,
                step_id=f"{snapshot.id}:REVIEW",
            )
        assert done is not None and done.state == WorkflowState.COMPLETED
    assert _events(session_factory) == [
        ("workflow_started", None),
        ("workflow_completed", None),
    ]
