from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.auth_repository import create_user
from app.workflow_repository import (
    create_workflow,
    find_workflow,
    lock_workflow,
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
