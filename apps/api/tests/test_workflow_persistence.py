from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.auth_repository import create_user
from app.workflow_domain import (
    CURRENT_WORKFLOW_DEFINITION_VERSION,
    MAX_WORKFLOW_REVISION,
    AnswerMultipleSteps,
    Cancel,
    Confirm,
    CreatedTodo,
    InvalidWorkflowAction,
    WorkflowSnapshot,
    WorkflowState,
    create_submit_tasks,
)
from app.workflow_repository import (
    create_workflow,
    find_workflow,
    lock_workflow,
    snapshot_from_record,
    snapshot_to_record,
    update_workflow,
)


def make_owner(database_session: Session, username: str = "owner") -> int:
    owner = create_user(database_session, uuid4(), username, "hash")
    database_session.flush()
    return owner.id


def test_insert_flushes_assess_task_row(database_session: Session) -> None:
    owner_id = make_owner(database_session)

    row = create_workflow(database_session, uuid4(), owner_id, "Plan birthday party")

    assert row.id is not None
    assert row.state == "ASSESS_TASK"
    assert row.title == "Plan birthday party"
    assert row.involves_multiple_steps is None
    assert row.proposed_todo_titles == []
    assert row.completion_result is None
    assert row.revision == 0
    assert row.definition_version == CURRENT_WORKFLOW_DEFINITION_VERSION


def test_new_assess_task_completion_result_is_sql_null(
    database_session: Session,
) -> None:
    owner_id = make_owner(database_session)
    public_id = uuid4()
    create_workflow(database_session, public_id, owner_id, "Plan birthday party")
    database_session.commit()

    value = database_session.execute(
        text(
            "SELECT completion_result IS NULL FROM todo_workflows "
            "WHERE public_id = :public_id"
        ),
        {"public_id": str(public_id)},
    ).scalar_one()

    assert value is True


def test_cancelled_completion_result_is_sql_null(database_session: Session) -> None:
    owner_id = make_owner(database_session)
    row = create_workflow(database_session, uuid4(), owner_id, "Plan birthday party")
    update_workflow(
        database_session,
        row,
        state="CANCELLED",
        involves_multiple_steps=None,
        proposed_todo_titles=[],
        completion_result=None,
    )
    database_session.commit()

    value = database_session.execute(
        text(
            "SELECT completion_result IS NULL FROM todo_workflows "
            "WHERE public_id = :public_id"
        ),
        {"public_id": str(row.public_id)},
    ).scalar_one()

    assert value is True


def test_database_rejects_non_object_completion_result(
    database_session: Session,
) -> None:
    from sqlalchemy.exc import IntegrityError

    owner_id = make_owner(database_session)
    row = create_workflow(database_session, uuid4(), owner_id, "Plan birthday party")

    with pytest.raises(IntegrityError):
        update_workflow(
            database_session,
            row,
            state="COMPLETED",
            involves_multiple_steps=False,
            proposed_todo_titles=["Plan birthday party"],
            completion_result=["not", "an", "object"],
        )
        database_session.flush()


def test_fresh_session_reads_accepted_progress(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    owner_id = make_owner(database_session)
    public_id = uuid4()
    create_workflow(database_session, public_id, owner_id, "Plan birthday party")
    database_session.commit()

    with session_factory() as verification_session:
        found = find_workflow(verification_session, public_id, owner_id)

        assert found is not None
        assert found.state == "ASSESS_TASK"
        assert found.proposed_todo_titles == []


def test_find_and_lock_return_none_for_another_owner(
    database_session: Session,
) -> None:
    owner_id = make_owner(database_session, "owner")
    other_id = make_owner(database_session, "other")
    public_id = uuid4()
    create_workflow(database_session, public_id, owner_id, "Plan birthday party")
    database_session.commit()

    assert find_workflow(database_session, public_id, other_id) is None
    assert lock_workflow(database_session, public_id, other_id) is None


def test_update_persists_answer_and_ordered_duplicate_proposals(
    database_session: Session,
) -> None:
    owner_id = make_owner(database_session)
    row = create_workflow(database_session, uuid4(), owner_id, "Plan birthday party")

    update_workflow(
        database_session,
        row,
        state="REVIEW",
        involves_multiple_steps=True,
        proposed_todo_titles=["Buy decorations", "Send invitations", "Buy decorations"],
        completion_result=None,
    )
    database_session.commit()

    assert row.involves_multiple_steps is True
    assert row.proposed_todo_titles == [
        "Buy decorations",
        "Send invitations",
        "Buy decorations",
    ]


def test_rolled_back_update_leaves_committed_row(
    database_session: Session,
) -> None:
    owner_id = make_owner(database_session)
    public_id = uuid4()
    create_workflow(database_session, public_id, owner_id, "Plan birthday party")
    database_session.commit()

    row = find_workflow(database_session, public_id, owner_id)
    assert row is not None
    update_workflow(
        database_session,
        row,
        state="CANCELLED",
        involves_multiple_steps=None,
        proposed_todo_titles=[],
        completion_result=None,
    )
    database_session.rollback()

    reread = find_workflow(database_session, public_id, owner_id)
    assert reread is not None
    assert reread.state == "ASSESS_TASK"


def test_deleting_owner_cascades_to_workflow(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    from app.auth_repository import UserRow

    owner_id = make_owner(database_session)
    public_id = uuid4()
    create_workflow(database_session, public_id, owner_id, "Plan birthday party")
    database_session.commit()

    with session_factory() as deleter:
        deleter.delete(deleter.get_one(UserRow, owner_id))
        deleter.commit()

    with session_factory() as verification_session:
        assert find_workflow(verification_session, public_id, owner_id) is None


def setup_owner(session_factory: sessionmaker[Session], username: str = "owner") -> int:
    with session_factory() as setup_session:
        owner = create_user(setup_session, uuid4(), username, "hash")
        setup_session.commit()
        return owner.id


def todo_titles(session_factory: sessionmaker[Session], owner_id: int) -> list[str]:
    from app.todo_repository import TodoRow

    with session_factory() as verification_session:
        rows = verification_session.scalars(
            select(TodoRow)
            .where(TodoRow.owner_id == owner_id)
            .order_by(TodoRow.id)
        ).all()
        return [row.title for row in rows]


def test_start_commits_assess_task_with_zero_todos(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    from app.workflow_service import get_workflow, start_workflow

    owner_id = setup_owner(session_factory)
    with session_factory() as write_session:
        snapshot = start_workflow(write_session, owner_id, "Plan birthday party", uuid4())

    assert snapshot.state == WorkflowState.ASSESS_TASK
    assert snapshot.title == "Plan birthday party"
    assert snapshot.involves_multiple_steps is None
    assert snapshot.proposed_todo_titles == ()
    assert snapshot.created_todos is None
    with session_factory() as verification_session:
        reread = get_workflow(verification_session, owner_id, snapshot.id)
        assert reread == snapshot
    assert todo_titles(session_factory, owner_id) == []


def test_yes_then_submit_persists_review_with_zero_todos(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    from app.workflow_service import advance_workflow, start_workflow

    owner_id = setup_owner(session_factory)
    with session_factory() as write_session:
        snapshot = start_workflow(write_session, owner_id, "Plan birthday party", uuid4())
    with session_factory() as write_session:
        offered = advance_workflow(
            write_session, owner_id, snapshot.id, AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )
    assert offered is not None
    assert offered.state == WorkflowState.OFFER_BREAKDOWN
    with session_factory() as write_session:
        collecting = advance_workflow(
            write_session, owner_id, snapshot.id, AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=1,
            step_id=f"{snapshot.id}:OFFER_BREAKDOWN",
        )
    assert collecting is not None
    assert collecting.state == WorkflowState.COLLECT_TASKS
    with session_factory() as write_session:
        review = advance_workflow(
            write_session,
            owner_id,
            snapshot.id,
            create_submit_tasks(("Send invitations", "Buy decorations")),
            request_id=uuid4(),
            expected_revision=2,
            step_id=f"{snapshot.id}:COLLECT_TASKS",
        )
    assert review is not None
    assert review.state == WorkflowState.REVIEW
    assert review.proposed_todo_titles == ("Send invitations", "Buy decorations")
    assert todo_titles(session_factory, owner_id) == []


def test_no_persists_review_with_original_title(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    from app.workflow_service import advance_workflow, start_workflow

    owner_id = setup_owner(session_factory)
    with session_factory() as write_session:
        snapshot = start_workflow(write_session, owner_id, "Plan birthday party", uuid4())
    with session_factory() as write_session:
        review = advance_workflow(
            write_session, owner_id, snapshot.id, AnswerMultipleSteps(answer=False),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )

    assert review is not None
    assert review.state == WorkflowState.REVIEW
    assert review.involves_multiple_steps is False
    assert review.proposed_todo_titles == ("Plan birthday party",)
    assert todo_titles(session_factory, owner_id) == []


def test_cancel_from_each_active_state_persists_cancelled(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    from app.workflow_service import advance_workflow, start_workflow

    owner_id = setup_owner(session_factory)
    workflow_ids = []
    for index in range(3):
        with session_factory() as write_session:
            snapshot = start_workflow(
                write_session, owner_id, f"Plan birthday party {index}", uuid4()
            )
            workflow_ids.append(snapshot.id)
    with session_factory() as write_session:
        offered = advance_workflow(
            write_session, owner_id, workflow_ids[1], AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{workflow_ids[1]}:ASSESS_TASK",
        )
        assert offered is not None
        assert offered.state == WorkflowState.OFFER_BREAKDOWN
    with session_factory() as write_session:
        collecting = advance_workflow(
            write_session, owner_id, workflow_ids[1], AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=1,
            step_id=f"{workflow_ids[1]}:OFFER_BREAKDOWN",
        )
        assert collecting is not None
    with session_factory() as write_session:
        offered = advance_workflow(
            write_session,
            owner_id,
            workflow_ids[2],
            AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{workflow_ids[2]}:ASSESS_TASK",
        )
        assert offered is not None
        assert offered.state == WorkflowState.OFFER_BREAKDOWN
    with session_factory() as write_session:
        review = advance_workflow(
            write_session,
            owner_id,
            workflow_ids[2],
            AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=1,
            step_id=f"{workflow_ids[2]}:OFFER_BREAKDOWN",
        )
        assert review is not None
        review = advance_workflow(
            write_session,
            owner_id,
            workflow_ids[2],
            create_submit_tasks(("Send invitations", "Buy decorations")),
            request_id=uuid4(),
            expected_revision=2,
            step_id=f"{workflow_ids[2]}:COLLECT_TASKS",
        )
        assert review is not None

    cancel_preconditions = (
        (0, "ASSESS_TASK"),
        (2, "COLLECT_TASKS"),
        (3, "REVIEW"),
    )
    for workflow_id, (expected_revision, state) in zip(
        workflow_ids, cancel_preconditions
    ):
        with session_factory() as write_session:
            result = advance_workflow(
                write_session,
                owner_id,
                workflow_id,
                Cancel(),
                request_id=uuid4(),
                expected_revision=expected_revision,
                step_id=f"{workflow_id}:{state}",
            )
        assert result is not None
        assert result.state == WorkflowState.CANCELLED
        assert result.created_todos is None
    assert todo_titles(session_factory, owner_id) == []


def test_confirm_simple_path_creates_one_ordinary_todo(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    from app.workflow_service import advance_workflow, start_workflow

    owner_id = setup_owner(session_factory)
    with session_factory() as write_session:
        snapshot = start_workflow(write_session, owner_id, "Plan birthday party", uuid4())
    with session_factory() as write_session:
        advance_workflow(
            write_session, owner_id, snapshot.id, AnswerMultipleSteps(answer=False),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )
    with session_factory() as write_session:
        completed = advance_workflow(write_session, owner_id, snapshot.id, Confirm(),
            request_id=uuid4(),
            expected_revision=1,
            step_id=f"{snapshot.id}:REVIEW",
        )

    assert completed is not None
    assert completed.state == WorkflowState.COMPLETED
    assert completed.created_todos is not None
    assert [todo.title for todo in completed.created_todos] == ["Plan birthday party"]
    assert [todo.completed for todo in completed.created_todos] == [False]
    assert todo_titles(session_factory, owner_id) == ["Plan birthday party"]


def test_confirm_breakdown_path_creates_exact_ordered_todos(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    from app.workflow_service import advance_workflow, start_workflow

    owner_id = setup_owner(session_factory)
    with session_factory() as write_session:
        snapshot = start_workflow(write_session, owner_id, "Plan birthday party", uuid4())
    with session_factory() as write_session:
        advance_workflow(
            write_session, owner_id, snapshot.id, AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )
    with session_factory() as write_session:
        advance_workflow(
            write_session, owner_id, snapshot.id, AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=1,
            step_id=f"{snapshot.id}:OFFER_BREAKDOWN",
        )
    with session_factory() as write_session:
        advance_workflow(
            write_session,
            owner_id,
            snapshot.id,
            create_submit_tasks(
                ("Buy decorations", "Send invitations", "Buy decorations")
            ),
            request_id=uuid4(),
            expected_revision=2,
            step_id=f"{snapshot.id}:COLLECT_TASKS",
        )
    with session_factory() as write_session:
        completed = advance_workflow(write_session, owner_id, snapshot.id, Confirm(),
            request_id=uuid4(),
            expected_revision=3,
            step_id=f"{snapshot.id}:REVIEW",
        )

    assert completed is not None
    assert completed.state == WorkflowState.COMPLETED
    assert completed.created_todos is not None
    assert [todo.title for todo in completed.created_todos] == [
        "Buy decorations",
        "Send invitations",
        "Buy decorations",
    ]
    assert todo_titles(session_factory, owner_id) == [
        "Buy decorations",
        "Send invitations",
        "Buy decorations",
    ]


def test_other_owner_gets_none_without_changing_row(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    from app.workflow_service import advance_workflow, get_workflow, start_workflow

    owner_id = setup_owner(session_factory, "owner")
    other_id = setup_owner(session_factory, "other")
    with session_factory() as write_session:
        snapshot = start_workflow(write_session, owner_id, "Plan birthday party", uuid4())

    with session_factory() as strangers_session:
        assert get_workflow(strangers_session, other_id, snapshot.id) is None
    with session_factory() as strangers_session:
        assert (
            advance_workflow(
                strangers_session, other_id, snapshot.id, AnswerMultipleSteps(answer=True),
                request_id=uuid4(),
                expected_revision=0,
                step_id=f"{snapshot.id}:ASSESS_TASK",
            )
            is None
        )

    with session_factory() as verification_session:
        reread = get_workflow(verification_session, owner_id, snapshot.id)
        assert reread is not None
        assert reread.state == WorkflowState.ASSESS_TASK


def test_confirm_rollback_leaves_review_and_zero_todos(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    from app import workflow_service
    from app.workflow_service import advance_workflow, start_workflow

    owner_id = setup_owner(session_factory)
    with session_factory() as write_session:
        snapshot = start_workflow(write_session, owner_id, "Plan birthday party", uuid4())
    with session_factory() as write_session:
        advance_workflow(
            write_session, owner_id, snapshot.id, AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )
    with session_factory() as write_session:
        advance_workflow(
            write_session, owner_id, snapshot.id, AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=1,
            step_id=f"{snapshot.id}:OFFER_BREAKDOWN",
        )
    with session_factory() as write_session:
        advance_workflow(
            write_session,
            owner_id,
            snapshot.id,
            create_submit_tasks(("Send invitations", "Buy decorations")),
            request_id=uuid4(),
            expected_revision=2,
            step_id=f"{snapshot.id}:COLLECT_TASKS",
        )

    real_create = workflow_service.create_todo
    calls = 0

    def fail_after_one(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("forced completion failure")
        return real_create(*args, **kwargs)

    workflow_service.create_todo = fail_after_one
    try:
        with (
            session_factory() as write_session,
            pytest.raises(RuntimeError, match="forced completion failure"),
        ):
            advance_workflow(write_session, owner_id, snapshot.id, Confirm(),
                request_id=uuid4(),
                expected_revision=3,
                step_id=f"{snapshot.id}:REVIEW",
            )
    finally:
        workflow_service.create_todo = real_create

    assert calls == 2
    assert todo_titles(session_factory, owner_id) == []
    with session_factory() as verification_session:
        reread = workflow_service.get_workflow(
            verification_session, owner_id, snapshot.id
        )
        assert reread is not None
        assert reread.state == WorkflowState.REVIEW
        assert reread.proposed_todo_titles == ("Send invitations", "Buy decorations")
        assert reread.created_todos is None


def test_confirm_in_assess_task_rejects_without_mutation(
    database_session: Session,
    session_factory: sessionmaker[Session],
) -> None:
    del database_session
    from app.workflow_service import advance_workflow, get_workflow, start_workflow

    owner_id = setup_owner(session_factory)
    with session_factory() as write_session:
        snapshot = start_workflow(write_session, owner_id, "Plan birthday party", uuid4())

    with session_factory() as verification_session:
        before_row = verification_session.execute(
            text(
                "SELECT state, title, involves_multiple_steps, "
                "proposed_todo_titles::text, completion_result::text "
                "FROM todo_workflows WHERE public_id = :public_id"
            ),
            {"public_id": str(snapshot.id)},
        ).one()
        before_todos = todo_titles(session_factory, owner_id)

    with session_factory() as write_session, pytest.raises(InvalidWorkflowAction):
        advance_workflow(write_session, owner_id, snapshot.id, Confirm(),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{snapshot.id}:ASSESS_TASK",
        )

    with session_factory() as verification_session:
        after_row = verification_session.execute(
            text(
                "SELECT state, title, involves_multiple_steps, "
                "proposed_todo_titles::text, completion_result::text "
                "FROM todo_workflows WHERE public_id = :public_id"
            ),
            {"public_id": str(snapshot.id)},
        ).one()
        assert after_row == before_row
        assert todo_titles(session_factory, owner_id) == before_todos
        assert get_workflow(verification_session, owner_id, snapshot.id) == snapshot


def test_offer_breakdown_row_persists(database_session: Session) -> None:
    owner_id = make_owner(database_session)
    row = create_workflow(database_session, uuid4(), owner_id, "Plan birthday party")
    update_workflow(
        database_session, row, state="OFFER_BREAKDOWN",
        involves_multiple_steps=True, proposed_todo_titles=[],
        completion_result=None,
    )
    assert find_workflow(database_session, row.public_id, owner_id).state == "OFFER_BREAKDOWN"


def test_downgrade_rewinds_offer_before_narrowing(database_engine: Engine) -> None:
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    public_id = uuid4()
    try:
        with database_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO users (public_id, username, password_hash) "
                    "VALUES (:public_id, :username, 'hash') RETURNING id"
                ),
                {"public_id": uuid4(), "username": f"downgrade-{public_id}"},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO todo_workflows "
                    "(public_id, owner_id, state, title, involves_multiple_steps, proposed_todo_titles) "
                    "VALUES (:public_id, :owner_id, 'OFFER_BREAKDOWN', "
                    "'Plan birthday party', true, '[]'::jsonb)"
                ),
                {"public_id": public_id, "owner_id": owner_id},
            )
            config.attributes["connection"] = connection
            command.downgrade(config, "2026090702")
            row = connection.execute(
                text(
                    "SELECT state, involves_multiple_steps, proposed_todo_titles "
                    "FROM todo_workflows WHERE public_id = :public_id"
                ),
                {"public_id": public_id},
            ).one()
            assert tuple(row) == ("ASSESS_TASK", None, [])
    finally:
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM todo_workflows WHERE public_id = :public_id"),
                {"public_id": public_id},
            )
            connection.execute(
                text("DELETE FROM users WHERE username = :username"),
                {"username": f"downgrade-{public_id}"},
            )
            config.attributes["connection"] = connection
            command.upgrade(config, "head")


def active_snapshot(workflow_id: UUID) -> WorkflowSnapshot:
    return WorkflowSnapshot(
        id=workflow_id,
        state=WorkflowState.COLLECT_TASKS,
        title="Plan birthday party",
        involves_multiple_steps=True,
        proposed_todo_titles=(),
        created_todos=None,
        revision=0,
        definition_version=CURRENT_WORKFLOW_DEFINITION_VERSION,
    )


def cancelled_snapshot(workflow_id: UUID) -> WorkflowSnapshot:
    return WorkflowSnapshot(
        id=workflow_id,
        state=WorkflowState.CANCELLED,
        title="Plan birthday party",
        involves_multiple_steps=True,
        proposed_todo_titles=("Send invitations", "Buy decorations"),
        created_todos=None,
        revision=3,
        definition_version=CURRENT_WORKFLOW_DEFINITION_VERSION,
    )


def completed_snapshot(workflow_id: UUID, todo_id: UUID) -> WorkflowSnapshot:
    return WorkflowSnapshot(
        id=workflow_id,
        state=WorkflowState.COMPLETED,
        title="Plan birthday party",
        involves_multiple_steps=False,
        proposed_todo_titles=("Plan birthday party",),
        created_todos=(
            CreatedTodo(id=todo_id, title="Plan birthday party", completed=False),
        ),
        revision=2,
        definition_version=CURRENT_WORKFLOW_DEFINITION_VERSION,
    )


def test_snapshot_record_round_trip_active_cancelled_completed() -> None:
    workflow_id = uuid4()
    todo_id = uuid4()
    for snapshot in (
        active_snapshot(workflow_id),
        cancelled_snapshot(workflow_id),
        completed_snapshot(workflow_id, todo_id),
    ):
        record = snapshot_to_record(snapshot)

        assert set(record) == {
            "workflow_id",
            "revision",
            "definition_version",
            "state",
            "title",
            "involves_multiple_steps",
            "proposed_todo_titles",
            "created_todos",
        }
        assert record["workflow_id"] == str(workflow_id)
        assert isinstance(record["proposed_todo_titles"], list)
        assert snapshot_from_record(record) == snapshot


def test_snapshot_record_encodes_uuids_and_tuples_as_json_values() -> None:
    todo_id = uuid4()
    record = snapshot_to_record(completed_snapshot(uuid4(), todo_id))

    assert record["created_todos"] == [
        {"id": str(todo_id), "title": "Plan birthday party", "completed": False}
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.pop("revision"),
        lambda record: record.update({"unexpected": 1}),
        lambda record: record.update({"workflow_id": "not-a-uuid"}),
        lambda record: record.update({"revision": -1}),
        lambda record: record.update({"revision": MAX_WORKFLOW_REVISION + 1}),
        lambda record: record.update({"definition_version": 0}),
        lambda record: record.update({"state": "NOT_A_STATE"}),
        lambda record: record.update({"title": "   "}),
        lambda record: record.update({"involves_multiple_steps": "yes"}),
        lambda record: record.update({"proposed_todo_titles": "nope"}),
        lambda record: record.update({"proposed_todo_titles": ["   "]}),
        lambda record: record.update({"created_todos": []}),
        lambda record: record.update(
            {"created_todos": [{"id": "x", "title": "T", "completed": False}]}
        ),
    ],
    ids=[
        "missing-key",
        "extra-key",
        "bad-workflow-id",
        "negative-revision",
        "revision-above-max",
        "definition-version-zero",
        "unknown-state",
        "blank-title",
        "non-boolean-flag",
        "proposals-not-array",
        "blank-proposal",
        "completed-requires-todos",
        "bad-todo-id",
    ],
)
def test_snapshot_from_record_rejects_malformed_records(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    record = snapshot_to_record(active_snapshot(uuid4()))
    mutate(record)

    with pytest.raises(ValueError):
        snapshot_from_record(record)


def _review_snapshot(workflow_id: UUID) -> WorkflowSnapshot:
    return WorkflowSnapshot(
        id=workflow_id,
        state=WorkflowState.REVIEW,
        title="Plan birthday party",
        involves_multiple_steps=True,
        proposed_todo_titles=("Send invitations", "Buy decorations"),
        created_todos=None,
        revision=1,
        definition_version=CURRENT_WORKFLOW_DEFINITION_VERSION,
    )


@pytest.mark.parametrize(
    "base, mutate",
    [
        (
            "active",
            lambda record: record.update(
                {"proposed_todo_titles": [f"Todo {index}" for index in range(11)]}
            ),
        ),
        (
            "review",
            lambda record: record.update(
                {"proposed_todo_titles": [f"Todo {index}" for index in range(11)]}
            ),
        ),
        (
            "completed",
            lambda record: record.update(
                {
                    "proposed_todo_titles": [
                        f"Todo {index}" for index in range(11)
                    ],
                    "created_todos": [
                        {
                            "id": str(uuid4()),
                            "title": f"Todo {index}",
                            "completed": False,
                        }
                        for index in range(11)
                    ],
                }
            ),
        ),
        (
            "completed",
            lambda record: record["created_todos"].append(
                {
                    "id": str(uuid4()),
                    "title": "Plan birthday party",
                    "completed": False,
                }
            ),
        ),
        (
            "completed",
            lambda record: record.update(
                {
                    "proposed_todo_titles": [
                        "Send invitations",
                        "Buy decorations",
                    ],
                }
            ),
        ),
        (
            "review",
            lambda record: record.update({"involves_multiple_steps": False}),
        ),
        (
            "completed",
            lambda record: record.update(
                {
                    "proposed_todo_titles": ["Todo 0", "Todo 1"],
                    "created_todos": [
                        {
                            "id": str(uuid4()),
                            "title": "Todo 0",
                            "completed": False,
                        },
                        {
                            "id": str(uuid4()),
                            "title": "Todo 1",
                            "completed": False,
                        },
                    ],
                }
            ),
        ),
        (
            "review",
            lambda record: record.update({"involves_multiple_steps": None}),
        ),
    ],
    ids=[
        "active-proposals-over-limit",
        "review-proposals-over-limit",
        "completed-proposals-over-limit",
        "completed-extra-todo",
        "completed-todo-count-mismatch",
        "review-single-step-flag-with-two-proposals",
        "completed-single-step-flag-with-two-proposals",
        "review-missing-flag",
    ],
)
def test_snapshot_from_record_rejects_count_violations(
    base: str, mutate: Callable[[dict[str, object]], None]
) -> None:
    workflow_id = uuid4()
    if base == "active":
        record = snapshot_to_record(active_snapshot(workflow_id))
    elif base == "review":
        record = snapshot_to_record(_review_snapshot(workflow_id))
    else:
        record = snapshot_to_record(completed_snapshot(workflow_id, uuid4()))
    mutate(record)

    with pytest.raises(ValueError):
        snapshot_from_record(record)


def test_snapshot_from_record_accepts_single_proposal_multi_step_review() -> None:
    # The domain yields one proposal with involves_multiple_steps=True when
    # OFFER_BREAKDOWN is answered "no", so a single proposal is valid for
    # either flag at REVIEW/COMPLETED; only False requires exactly one.
    workflow_id = uuid4()
    todo_id = uuid4()
    review = WorkflowSnapshot(
        id=workflow_id,
        state=WorkflowState.REVIEW,
        title="Plan birthday party",
        involves_multiple_steps=True,
        proposed_todo_titles=("Plan birthday party",),
        created_todos=None,
        revision=1,
        definition_version=CURRENT_WORKFLOW_DEFINITION_VERSION,
    )
    completed = WorkflowSnapshot(
        id=workflow_id,
        state=WorkflowState.COMPLETED,
        title="Plan birthday party",
        involves_multiple_steps=True,
        proposed_todo_titles=("Plan birthday party",),
        created_todos=(
            CreatedTodo(id=todo_id, title="Plan birthday party", completed=False),
        ),
        revision=2,
        definition_version=CURRENT_WORKFLOW_DEFINITION_VERSION,
    )

    assert snapshot_from_record(snapshot_to_record(review)) == review
    assert snapshot_from_record(snapshot_to_record(completed)) == completed


def _phase8_insert(connection, owner_id: int, public_id: UUID, state: str,
                   involves: bool | None, proposals: str,
                   completion: str | None) -> None:
    connection.execute(
        text(
            "INSERT INTO todo_workflows (public_id, owner_id, state, title, "
            "involves_multiple_steps, proposed_todo_titles, completion_result) "
            "VALUES (:public_id, :owner_id, :state, 'Plan birthday party', "
            ":involves, CAST(:proposals AS jsonb), "
            "CAST(:completion AS jsonb))"
        ),
        {
            "public_id": public_id,
            "owner_id": owner_id,
            "state": state,
            "involves": involves,
            "proposals": proposals,
            "completion": completion,
        },
    )


def test_reliability_migration_backfills_each_state(database_engine: Engine) -> None:
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    states = [
        ("ASSESS_TASK", None, "[]", None),
        ("OFFER_BREAKDOWN", True, "[]", None),
        ("COLLECT_TASKS", True, "[]", None),
        ("REVIEW", True, '["Send invitations", "Buy decorations"]', None),
        (
            "COMPLETED",
            False,
            '["Plan birthday party"]',
            (
                '{"created_todos": [{"id": "5f699d61-9449-407e-aa37-89e759b78df0", '
                '"title": "Plan birthday party", "completed": false}]}'
            ),
        ),
        ("CANCELLED", None, "[]", None),
    ]
    public_ids = [uuid4() for _ in states]
    username = f"migrate-{uuid4()}"
    try:
        with database_engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "2026090801")
            owner_id = connection.execute(
                text(
                    "INSERT INTO users (public_id, username, password_hash) "
                    "VALUES (:public_id, :username, 'hash') RETURNING id"
                ),
                {"public_id": uuid4(), "username": username},
            ).scalar_one()
            for public_id, (state, involves, proposals, completion) in zip(
                public_ids, states
            ):
                _phase8_insert(
                    connection, owner_id, public_id, state, involves, proposals,
                    completion,
                )
            command.upgrade(config, "head")
            rows = connection.execute(
                text(
                    "SELECT state, revision, definition_version, title, "
                    "involves_multiple_steps, "
                    "proposed_todo_titles::text, completion_result::text "
                    "FROM todo_workflows WHERE owner_id = :owner_id "
                    "ORDER BY public_id"
                ),
                {"owner_id": owner_id},
            ).all()
            assert len(rows) == len(states)
            for row in rows:
                assert row.revision == 0
                assert row.definition_version == 1
                assert row.title == "Plan birthday party"
            by_state = {row.state: row for row in rows}
            assert by_state["REVIEW"].proposed_todo_titles == (
                '["Send invitations", "Buy decorations"]'
            )
            assert "5f699d61-9449-407e-aa37-89e759b78df0" in (
                by_state["COMPLETED"].completion_result or ""
            )
            for bad_sql, params, expected in [
                (
                    (
                        "UPDATE todo_workflows SET revision = -1 "
                        "WHERE public_id = :public_id"
                    ),
                    {"public_id": public_ids[0]},
                    IntegrityError,
                ),
                # 2147483648 overflows INTEGER, so PostgreSQL raises a
                # numeric-range error before the CHECK constraint is reached.
                (
                    (
                        "UPDATE todo_workflows SET revision = 2147483648 "
                        "WHERE public_id = :public_id"
                    ),
                    {"public_id": public_ids[0]},
                    (IntegrityError, DataError),
                ),
                (
                    (
                        "UPDATE todo_workflows SET definition_version = 0 "
                        "WHERE public_id = :public_id"
                    ),
                    {"public_id": public_ids[0]},
                    IntegrityError,
                ),
            ]:
                # Same connection via savepoint: a second connection would
                # block on this transaction's DDL locks and deadlock.
                with pytest.raises(expected), connection.begin_nested():
                    connection.execute(text(bad_sql), params)
    finally:
        with database_engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.execute(
                text("DELETE FROM users WHERE username = :username"),
                {"username": username},
            )


def test_reliability_rollback_and_reupgrade_preserve_data(
    database_engine: Engine,
) -> None:
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    public_id = uuid4()
    todo_id = uuid4()
    username = f"roundtrip-{uuid4()}"
    try:
        with database_engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            owner_id = connection.execute(
                text(
                    "INSERT INTO users (public_id, username, password_hash) "
                    "VALUES (:public_id, :username, 'hash') RETURNING id"
                ),
                {"public_id": uuid4(), "username": username},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO todo_workflows (public_id, owner_id, state, "
                    "title, involves_multiple_steps, proposed_todo_titles, "
                    "revision, definition_version) "
                    "VALUES (:public_id, :owner_id, 'REVIEW', "
                    "'Plan birthday party', true, "
                    "'[\"Send invitations\"]'::jsonb, 0, 1)"
                ),
                {"public_id": public_id, "owner_id": owner_id},
            )
            connection.execute(
                text(
                    "INSERT INTO todos (public_id, owner_id, title, completed) "
                    "VALUES (:public_id, :owner_id, 'Keep', false)"
                ),
                {"public_id": todo_id, "owner_id": owner_id},
            )
            command.downgrade(config, "2026090801")
            assert connection.execute(
                text(
                    "SELECT count(*) FROM todo_workflows "
                    "WHERE public_id = :public_id"
                ),
                {"public_id": public_id},
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM todos WHERE public_id = :public_id"),
                {"public_id": todo_id},
            ).scalar_one() == 1
            command.upgrade(config, "head")
            row = connection.execute(
                text(
                    "SELECT state, revision, definition_version, "
                    "proposed_todo_titles::text FROM todo_workflows "
                    "WHERE public_id = :public_id"
                ),
                {"public_id": public_id},
            ).one()
            assert tuple(row) == ("REVIEW", 0, 1, '["Send invitations"]')
            assert connection.execute(
                text("SELECT count(*) FROM todos WHERE public_id = :public_id"),
                {"public_id": todo_id},
            ).scalar_one() == 1
    finally:
        with database_engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.execute(
                text("DELETE FROM users WHERE username = :username"),
                {"username": username},
            )
