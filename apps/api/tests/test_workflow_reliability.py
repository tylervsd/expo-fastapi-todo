from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.auth_repository import create_user
from app.workflow_domain import (
    MAX_WORKFLOW_REVISION,
    AnswerMultipleSteps,
    Cancel,
    Confirm,
    InvalidWorkflowAction,
    TerminalWorkflow,
    WorkflowSnapshot,
    WorkflowState,
    create_submit_tasks,
)
from app.workflow_repository import (
    WorkflowActionRequestRow,
    WorkflowRow,
    WorkflowStartRequestRow,
)
from app.workflow_service import (
    RequestIdReused,
    RevisionExhausted,
    StaleWorkflowStep,
    UnsupportedWorkflowDefinition,
    advance_workflow,
    get_workflow,
    list_active_workflows,
    start_workflow,
)


def setup_reliability_owner(
    session_factory: sessionmaker[Session], username: str = "owner"
) -> int:
    with session_factory() as setup_session:
        owner = create_user(setup_session, uuid4(), username, "hash")
        setup_session.commit()
        return owner.id


def start_owned(
    session_factory: sessionmaker[Session],
    owner_id: int,
    title: str,
    request_id: UUID | None = None,
) -> WorkflowSnapshot:
    with session_factory() as session:
        return start_workflow(session, owner_id, title, request_id or uuid4())


def advance_owned(
    session_factory: sessionmaker[Session],
    owner_id: int,
    workflow_id: UUID,
    command: Any,
    revision: int,
    state: str,
    request_id: UUID | None = None,
) -> WorkflowSnapshot | None:
    with session_factory() as session:
        return advance_workflow(
            session,
            owner_id,
            workflow_id,
            command,
            request_id=request_id or uuid4(),
            expected_revision=revision,
            step_id=f"{workflow_id}:{state}",
        )


def table_count(session_factory: sessionmaker[Session], table: Any) -> int:
    with session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(table)) or 0)


def owner_workflow_count(session_factory: sessionmaker[Session], owner_id: int) -> int:
    with session_factory() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(WorkflowRow)
                .where(WorkflowRow.owner_id == owner_id)
            )
            or 0
        )


def todo_titles(session_factory: sessionmaker[Session], owner_id: int) -> list[str]:
    from app.todo_repository import TodoRow

    with session_factory() as verification_session:
        rows = verification_session.scalars(
            select(TodoRow).where(TodoRow.owner_id == owner_id).order_by(TodoRow.id)
        ).all()
        return [row.title for row in rows]


def test_start_replay_returns_single_accepted_outcome(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    request_id = uuid4()
    with session_factory() as session:
        first = start_workflow(session, owner_id, "Party", request_id)
    with session_factory() as session:
        replay = start_workflow(session, owner_id, "Party", request_id)
    assert replay == first
    with session_factory() as session, pytest.raises(RequestIdReused):
        start_workflow(session, owner_id, "Different", request_id)


def test_start_replay_after_advance_returns_initial_snapshot(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    request_id = uuid4()
    with session_factory() as session:
        first = start_workflow(session, owner_id, "Party", request_id)
    advance_owned(
        session_factory,
        owner_id,
        first.id,
        AnswerMultipleSteps(answer=True),
        0,
        "ASSESS_TASK",
    )
    with session_factory() as session:
        replay = start_workflow(session, owner_id, "Party", request_id)
    assert replay == first
    assert replay.revision == 0
    current = advance_owned(
        session_factory,
        owner_id,
        first.id,
        AnswerMultipleSteps(answer=True),
        1,
        "OFFER_BREAKDOWN",
    )
    assert current is not None
    assert current.revision == 2


def test_concurrent_identical_starts_create_single_workflow(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    request_id = uuid4()
    barrier = Barrier(2)

    def attempt() -> WorkflowSnapshot:
        with session_factory() as session:
            barrier.wait(timeout=10)
            return start_workflow(session, owner_id, "Party", request_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    assert owner_workflow_count(session_factory, owner_id) == 1
    assert table_count(session_factory, WorkflowStartRequestRow) == 1


def test_start_request_id_is_owner_scoped(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory, "owner")
    other_id = setup_reliability_owner(session_factory, "other")
    request_id = uuid4()
    first = start_owned(session_factory, owner_id, "Party", request_id)
    second = start_owned(session_factory, other_id, "Party", request_id)
    assert second.id != first.id
    assert owner_workflow_count(session_factory, owner_id) == 1
    assert owner_workflow_count(session_factory, other_id) == 1


def test_action_replay_before_stale_checks(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Party")
    first_request = uuid4()
    with session_factory() as session:
        offered = advance_workflow(
            session,
            owner_id,
            snapshot.id,
            AnswerMultipleSteps(answer=True),
            request_id=first_request,
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        AnswerMultipleSteps(answer=True),
        1,
        "OFFER_BREAKDOWN",
    )
    with session_factory() as session:
        replay = advance_workflow(
            session,
            owner_id,
            snapshot.id,
            AnswerMultipleSteps(answer=True),
            request_id=first_request,
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )
    assert replay == offered
    with session_factory() as session:
        current = get_workflow(session, owner_id, snapshot.id)
    assert current is not None
    assert current.state == WorkflowState.COLLECT_TASKS
    assert current.revision == 2


def test_action_request_id_reused_with_different_payload(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Party")
    request_id = uuid4()
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        AnswerMultipleSteps(answer=True),
        0,
        "ASSESS_TASK",
        request_id,
    )
    with session_factory() as session, pytest.raises(RequestIdReused):
        advance_workflow(
            session,
            owner_id,
            snapshot.id,
            AnswerMultipleSteps(answer=False),
            request_id=request_id,
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )


def test_concurrent_identical_actions_return_single_outcome(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Party")
    request_id = uuid4()
    step = f"{snapshot.id}:ASSESS_TASK"
    barrier = Barrier(2)

    def attempt() -> WorkflowSnapshot | None:
        with session_factory() as session:
            barrier.wait(timeout=10)
            return advance_workflow(
                session,
                owner_id,
                snapshot.id,
                AnswerMultipleSteps(answer=True),
                request_id=request_id,
                expected_revision=0,
                step_id=step,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
    assert results[0] is not None
    assert results[0].revision == 1
    assert table_count(session_factory, WorkflowActionRequestRow) == 1


def test_distinct_actions_at_one_revision_yield_one_advance_and_one_stale(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Party")
    step = f"{snapshot.id}:ASSESS_TASK"
    barrier = Barrier(2)
    outcomes: list[Any] = []

    def attempt(answer: bool) -> None:
        try:
            with session_factory() as session:
                barrier.wait(timeout=10)
                outcomes.append(
                    advance_workflow(
                        session,
                        owner_id,
                        snapshot.id,
                        AnswerMultipleSteps(answer=answer),
                        request_id=uuid4(),
                        expected_revision=0,
                        step_id=step,
                    )
                )
        except StaleWorkflowStep as exc:
            outcomes.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, answer) for answer in (True, False)]
        for future in futures:
            future.result(timeout=10)
    successes = [item for item in outcomes if isinstance(item, WorkflowSnapshot)]
    stales = [item for item in outcomes if isinstance(item, StaleWorkflowStep)]
    assert len(successes) == 1
    assert len(stales) == 1
    assert successes[0].revision == 1
    with session_factory() as session:
        current = get_workflow(session, owner_id, snapshot.id)
    assert current is not None
    assert current.revision == 1
    assert table_count(session_factory, WorkflowActionRequestRow) == 1


def test_confirmation_replay_creates_single_ordered_todo_set(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Plan birthday party")
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        AnswerMultipleSteps(answer=True),
        0,
        "ASSESS_TASK",
    )
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        AnswerMultipleSteps(answer=True),
        1,
        "OFFER_BREAKDOWN",
    )
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        create_submit_tasks(("Send invitations", "Order birthday cake")),
        2,
        "COLLECT_TASKS",
    )
    confirm_request = uuid4()
    with session_factory() as session:
        completed = advance_workflow(
            session,
            owner_id,
            snapshot.id,
            Confirm(),
            request_id=confirm_request,
            expected_revision=3,
            step_id=f"{snapshot.id}:REVIEW",
        )
    assert completed is not None
    assert completed.state == WorkflowState.COMPLETED
    with session_factory() as session:
        replay = advance_workflow(
            session,
            owner_id,
            snapshot.id,
            Confirm(),
            request_id=confirm_request,
            expected_revision=3,
            step_id=f"{snapshot.id}:REVIEW",
        )
    assert replay == completed
    assert todo_titles(session_factory, owner_id) == [
        "Send invitations",
        "Order birthday cake",
    ]
    assert table_count(session_factory, WorkflowActionRequestRow) == 4


def test_start_failure_between_claim_and_workflow_rolls_back(
    database_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    from app import workflow_service

    owner_id = setup_reliability_owner(session_factory)
    request_id = uuid4()

    def fail_create(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("forced start failure")

    monkeypatch.setattr(workflow_service, "create_workflow", fail_create)
    with (
        session_factory() as session,
        pytest.raises(RuntimeError, match="forced start failure"),
    ):
        start_workflow(session, owner_id, "Party", request_id)
    assert table_count(session_factory, WorkflowStartRequestRow) == 0
    assert owner_workflow_count(session_factory, owner_id) == 0

    monkeypatch.undo()
    retried = start_owned(session_factory, owner_id, "Party", request_id)
    assert retried.state == WorkflowState.ASSESS_TASK
    assert retried.revision == 0
    assert owner_workflow_count(session_factory, owner_id) == 1


def test_action_failure_after_todo_insertion_rolls_back(
    database_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del database_session
    from app import workflow_service

    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Plan birthday party")
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        AnswerMultipleSteps(answer=True),
        0,
        "ASSESS_TASK",
    )
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        AnswerMultipleSteps(answer=True),
        1,
        "OFFER_BREAKDOWN",
    )
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        create_submit_tasks(("Send invitations", "Order birthday cake")),
        2,
        "COLLECT_TASKS",
    )
    real_create = workflow_service.create_todo
    calls = 0

    def fail_after_one(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("forced action failure")
        return real_create(*args, **kwargs)

    monkeypatch.setattr(workflow_service, "create_todo", fail_after_one)
    confirm_request = uuid4()
    with (
        session_factory() as session,
        pytest.raises(RuntimeError, match="forced action failure"),
    ):
        advance_workflow(
            session,
            owner_id,
            snapshot.id,
            Confirm(),
            request_id=confirm_request,
            expected_revision=3,
            step_id=f"{snapshot.id}:REVIEW",
        )
    assert calls == 2
    assert todo_titles(session_factory, owner_id) == []
    with session_factory() as session:
        reread = get_workflow(session, owner_id, snapshot.id)
    assert reread is not None
    assert reread.state == WorkflowState.REVIEW
    assert reread.revision == 3
    assert table_count(session_factory, WorkflowActionRequestRow) == 3

    monkeypatch.undo()
    retried = advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        Confirm(),
        3,
        "REVIEW",
        confirm_request,
    )
    assert retried is not None
    assert retried.state == WorkflowState.COMPLETED
    assert retried.revision == 4
    assert todo_titles(session_factory, owner_id) == [
        "Send invitations",
        "Order birthday cake",
    ]


def test_revision_ceiling_replays_matching_request_but_rejects_new_ones(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Plan birthday party")
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        AnswerMultipleSteps(answer=True),
        0,
        "ASSESS_TASK",
    )
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        AnswerMultipleSteps(answer=True),
        1,
        "OFFER_BREAKDOWN",
    )
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflows SET revision = :revision WHERE public_id = :id"
            ),
            {"revision": MAX_WORKFLOW_REVISION - 1, "id": str(snapshot.id)},
        )
        session.commit()
    submit_request = uuid4()
    with session_factory() as session:
        accepted = advance_workflow(
            session,
            owner_id,
            snapshot.id,
            create_submit_tasks(("Send invitations", "Order birthday cake")),
            request_id=submit_request,
            expected_revision=MAX_WORKFLOW_REVISION - 1,
            step_id=f"{snapshot.id}:COLLECT_TASKS",
        )
    assert accepted is not None
    assert accepted.revision == MAX_WORKFLOW_REVISION
    assert accepted.state == WorkflowState.REVIEW
    with session_factory() as session:
        replay = advance_workflow(
            session,
            owner_id,
            snapshot.id,
            create_submit_tasks(("Send invitations", "Order birthday cake")),
            request_id=submit_request,
            expected_revision=MAX_WORKFLOW_REVISION - 1,
            step_id=f"{snapshot.id}:COLLECT_TASKS",
        )
    assert replay == accepted
    with session_factory() as session, pytest.raises(RevisionExhausted):
        advance_workflow(
            session,
            owner_id,
            snapshot.id,
            Cancel(),
            request_id=uuid4(),
            expected_revision=MAX_WORKFLOW_REVISION,
            step_id=f"{snapshot.id}:REVIEW",
        )
    with session_factory() as session:
        current = get_workflow(session, owner_id, snapshot.id)
    assert current is not None
    assert current.state == WorkflowState.REVIEW
    assert current.revision == MAX_WORKFLOW_REVISION
    assert table_count(session_factory, WorkflowActionRequestRow) == 3


def test_advance_missing_workflow_returns_none(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    missing = uuid4()
    with session_factory() as session:
        assert (
            advance_workflow(
                session,
                owner_id,
                missing,
                Cancel(),
                request_id=uuid4(),
                expected_revision=0,
                step_id=f"{missing}:ASSESS_TASK",
            )
            is None
        )
    assert table_count(session_factory, WorkflowActionRequestRow) == 0


def test_new_request_on_terminal_workflow_is_rejected(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Party")
    advance_owned(
        session_factory,
        owner_id,
        snapshot.id,
        AnswerMultipleSteps(answer=False),
        0,
        "ASSESS_TASK",
    )
    advance_owned(session_factory, owner_id, snapshot.id, Confirm(), 1, "REVIEW")
    with session_factory() as session, pytest.raises(TerminalWorkflow):
        advance_workflow(
            session,
            owner_id,
            snapshot.id,
            Cancel(),
            request_id=uuid4(),
            expected_revision=2,
            step_id=f"{snapshot.id}:COMPLETED",
        )
    with session_factory() as session:
        current = get_workflow(session, owner_id, snapshot.id)
    assert current is not None
    assert current.state == WorkflowState.COMPLETED
    assert table_count(session_factory, WorkflowActionRequestRow) == 2


def test_invalid_action_leaves_no_request_record(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Party")
    with session_factory() as session, pytest.raises(InvalidWorkflowAction):
        advance_workflow(
            session,
            owner_id,
            snapshot.id,
            Confirm(),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )
    assert table_count(session_factory, WorkflowActionRequestRow) == 0


def test_other_owner_cannot_act_or_replay(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory, "owner")
    other_id = setup_reliability_owner(session_factory, "other")
    snapshot = start_owned(session_factory, owner_id, "Party")
    with session_factory() as session:
        assert (
            advance_workflow(
                session,
                other_id,
                snapshot.id,
                AnswerMultipleSteps(answer=True),
                request_id=uuid4(),
                expected_revision=0,
                step_id=f"{snapshot.id}:ASSESS_TASK",
            )
            is None
        )
    with session_factory() as session:
        assert get_workflow(session, other_id, snapshot.id) is None
    assert list_active_scoped(session_factory, other_id) == []
    with session_factory() as session:
        current = get_workflow(session, owner_id, snapshot.id)
    assert current is not None
    assert current.state == WorkflowState.ASSESS_TASK
    assert table_count(session_factory, WorkflowActionRequestRow) == 0


def list_active_scoped(
    session_factory: sessionmaker[Session], owner_id: int
) -> list[WorkflowSnapshot]:
    with session_factory() as session:
        return list_active_workflows(session, owner_id)


def test_list_active_returns_only_owned_nonterminal_newest_first(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory, "owner")
    other_id = setup_reliability_owner(session_factory, "other")
    start_owned(session_factory, owner_id, "Alpha")
    beta = start_owned(session_factory, owner_id, "Beta")
    start_owned(session_factory, owner_id, "Gamma")
    done = start_owned(session_factory, owner_id, "Done")
    dropped = start_owned(session_factory, owner_id, "Dropped")
    start_owned(session_factory, other_id, "Other")
    advance_owned(
        session_factory,
        owner_id,
        beta.id,
        AnswerMultipleSteps(answer=True),
        0,
        "ASSESS_TASK",
    )
    advance_owned(
        session_factory,
        owner_id,
        done.id,
        AnswerMultipleSteps(answer=False),
        0,
        "ASSESS_TASK",
    )
    advance_owned(session_factory, owner_id, done.id, Confirm(), 1, "REVIEW")
    advance_owned(session_factory, owner_id, dropped.id, Cancel(), 0, "ASSESS_TASK")

    items = list_active_scoped(session_factory, owner_id)
    assert [item.title for item in items] == ["Gamma", "Beta", "Alpha"]
    assert [item.state for item in items] == [
        WorkflowState.ASSESS_TASK,
        WorkflowState.OFFER_BREAKDOWN,
        WorkflowState.ASSESS_TASK,
    ]
    assert all(item.definition_version == 1 for item in items)
    other_items = list_active_scoped(session_factory, other_id)
    assert [item.title for item in other_items] == ["Other"]


def test_list_active_empty_for_new_owner(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    assert list_active_scoped(session_factory, owner_id) == []


def test_unsupported_definition_rejected_without_mutation(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Party")
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflows SET definition_version = 2 WHERE public_id = :id"
            ),
            {"id": str(snapshot.id)},
        )
        session.commit()
    with session_factory() as session, pytest.raises(UnsupportedWorkflowDefinition):
        get_workflow(session, owner_id, snapshot.id)
    with session_factory() as session, pytest.raises(UnsupportedWorkflowDefinition):
        list_active_workflows(session, owner_id)
    with session_factory() as session, pytest.raises(UnsupportedWorkflowDefinition):
        advance_workflow(
            session,
            owner_id,
            snapshot.id,
            AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )
    with session_factory() as session:
        row = session.scalar(
            select(WorkflowRow).where(WorkflowRow.public_id == snapshot.id)
        )
    assert row is not None
    assert row.state == "ASSESS_TASK"
    assert row.revision == 0
    assert table_count(session_factory, WorkflowActionRequestRow) == 0


def test_get_workflow_unsupported_definition_with_nonv1_representation(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Party")
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflows SET definition_version = 2, "
                "state = 'REVIEW', completion_result = :result "
                "WHERE public_id = :id"
            ),
            {"id": str(snapshot.id), "result": '{"v2_result": []}'},
        )
        session.commit()
    with session_factory() as session, pytest.raises(UnsupportedWorkflowDefinition):
        get_workflow(session, owner_id, snapshot.id)


def test_list_active_unsupported_definition_with_nonv1_representation(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    owner_id = setup_reliability_owner(session_factory)
    snapshot = start_owned(session_factory, owner_id, "Party")
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE todo_workflows SET definition_version = 2, "
                "state = 'REVIEW', completion_result = :result "
                "WHERE public_id = :id"
            ),
            {"id": str(snapshot.id), "result": '{"v2_result": []}'},
        )
        session.commit()
    with session_factory() as session, pytest.raises(UnsupportedWorkflowDefinition):
        list_active_workflows(session, owner_id)
