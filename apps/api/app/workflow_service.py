from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.todo_repository import create_todo
from app.workflow_domain import (
    CreatedTodo,
    WorkflowCommand,
    WorkflowSnapshot,
    WorkflowState,
    create_initial_snapshot,
    transition,
)
from app.workflow_repository import (
    WorkflowRow,
    create_workflow,
    find_workflow,
    lock_workflow,
    update_workflow,
)


def _snapshot_from_row(row: WorkflowRow) -> WorkflowSnapshot:
    created_todos: tuple[CreatedTodo, ...] | None = None
    if row.completion_result is not None:
        created_todos = tuple(
            CreatedTodo(
                id=UUID(item["id"]),
                title=item["title"],
                completed=item["completed"],
            )
            for item in row.completion_result["created_todos"]
        )
    return WorkflowSnapshot(
        id=row.public_id,
        state=WorkflowState(row.state),
        title=row.title,
        involves_multiple_steps=row.involves_multiple_steps,
        proposed_todo_titles=tuple(row.proposed_todo_titles),
        created_todos=created_todos,
        revision=row.revision,
        definition_version=row.definition_version,
    )


def start_workflow(
    session: Session, owner_id: int, title: str
) -> WorkflowSnapshot:
    snapshot = create_initial_snapshot(uuid4(), title)
    with session.begin():
        create_workflow(session, snapshot.id, owner_id, snapshot.title)
    return snapshot


def get_workflow(
    session: Session, owner_id: int, workflow_id: UUID
) -> WorkflowSnapshot | None:
    row = find_workflow(session, workflow_id, owner_id)
    if row is None:
        return None
    return _snapshot_from_row(row)


def advance_workflow(
    session: Session,
    owner_id: int,
    workflow_id: UUID,
    command: WorkflowCommand,
) -> WorkflowSnapshot | None:
    with session.begin():
        row = lock_workflow(session, workflow_id, owner_id)
        if row is None:
            return None
        decision = transition(_snapshot_from_row(row), command)
        created: list[CreatedTodo] = []
        completion_result: dict[str, object] | None = None
        if decision.todo_titles_to_create:
            for title in decision.todo_titles_to_create:
                todo = create_todo(session, uuid4(), title, owner_id)
                created.append(
                    CreatedTodo(
                        id=todo.public_id, title=todo.title, completed=todo.completed
                    )
                )
            completion_result = {
                "created_todos": [
                    {
                        "id": str(item.id),
                        "title": item.title,
                        "completed": item.completed,
                    }
                    for item in created
                ]
            }
        update_workflow(
            session,
            row,
            state=decision.state.value,
            involves_multiple_steps=decision.involves_multiple_steps,
            proposed_todo_titles=list(decision.proposed_todo_titles),
            completion_result=completion_result,
        )
        return WorkflowSnapshot(
            id=row.public_id,
            state=decision.state,
            title=row.title,
            involves_multiple_steps=decision.involves_multiple_steps,
            proposed_todo_titles=decision.proposed_todo_titles,
            created_todos=tuple(created) if completion_result is not None else None,
            revision=row.revision,
            definition_version=row.definition_version,
        )
