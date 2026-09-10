import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.todo_repository import create_todo
from app.workflow_domain import (
    CURRENT_WORKFLOW_DEFINITION_VERSION,
    MAX_WORKFLOW_REVISION,
    AnswerMultipleSteps,
    Cancel,
    Confirm,
    CreatedTodo,
    SubmitTasks,
    TerminalWorkflow,
    UnsupportedWorkflowDefinition,
    WorkflowCommand,
    WorkflowSnapshot,
    WorkflowState,
    create_initial_snapshot,
    transition,
)
from app.workflow_repository import (
    WorkflowActionRequestRow,
    WorkflowRow,
    WorkflowStartRequestRow,
    create_workflow,
    find_workflow,
    lock_workflow,
    snapshot_from_record,
    snapshot_to_record,
)

ACTIVE_WORKFLOW_STATES = (
    WorkflowState.ASSESS_TASK,
    WorkflowState.OFFER_BREAKDOWN,
    WorkflowState.COLLECT_TASKS,
    WorkflowState.REVIEW,
)


class StaleWorkflowStep(ValueError):
    """The submitted step ID or revision no longer matches the saved workflow."""


class RequestIdReused(ValueError):
    """The scoped request ID was already used with a different payload."""


class RevisionExhausted(ValueError):
    """The workflow is at the maximum revision; no new action is possible."""


def fingerprint_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _start_fingerprint(canonical_title: str) -> str:
    return fingerprint_payload({"operation": "start", "title": canonical_title})


def _canonical_action(command: WorkflowCommand) -> dict[str, Any]:
    if isinstance(command, AnswerMultipleSteps):
        return {"action": "answer_multiple_steps", "answer": command.answer}
    if isinstance(command, SubmitTasks):
        return {"action": "submit_tasks", "titles": list(command.titles)}
    if isinstance(command, Confirm):
        return {"action": "confirm"}
    if isinstance(command, Cancel):
        return {"action": "cancel"}
    raise TypeError(f"unsupported workflow command {type(command).__name__}")


def _action_fingerprint(
    workflow_id: UUID, expected_revision: int, step_id: str, command: WorkflowCommand
) -> str:
    return fingerprint_payload(
        {
            "operation": "advance",
            "workflow_id": str(workflow_id),
            "expected_revision": expected_revision,
            "step_id": step_id,
            "action": _canonical_action(command),
        }
    )


def current_step_id(workflow_id: UUID, state: str) -> str:
    return f"{workflow_id}:{state}"


# Kept for existing internal callers while the helper becomes a shared seam.
_current_step_id = current_step_id


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
    session: Session, owner_id: int, title: str, request_id: UUID
) -> WorkflowSnapshot:
    snapshot = create_initial_snapshot(uuid4(), title)
    fingerprint = _start_fingerprint(snapshot.title)
    record = snapshot_to_record(snapshot)
    with session.begin():
        inserted = session.execute(
            pg_insert(WorkflowStartRequestRow)
            .values(
                owner_id=owner_id,
                request_id=request_id,
                request_fingerprint=fingerprint,
                workflow_id=snapshot.id,
                accepted_snapshot=record,
            )
            .on_conflict_do_nothing(index_elements=["owner_id", "request_id"])
            .returning(WorkflowStartRequestRow),
        ).scalar_one_or_none()
        if inserted is not None:
            create_workflow(session, snapshot.id, owner_id, snapshot.title)
            return snapshot
        existing = session.get(WorkflowStartRequestRow, (owner_id, request_id))
        assert existing is not None
        if existing.request_fingerprint != fingerprint:
            raise RequestIdReused(
                "request_id was already used with a different start payload"
            )
        return snapshot_from_record(existing.accepted_snapshot)


def get_workflow(
    session: Session, owner_id: int, workflow_id: UUID
) -> WorkflowSnapshot | None:
    row = find_workflow(session, workflow_id, owner_id)
    if row is None:
        return None
    if row.definition_version != CURRENT_WORKFLOW_DEFINITION_VERSION:
        raise UnsupportedWorkflowDefinition(
            f"unsupported workflow definition version {row.definition_version}"
        )
    snapshot = _snapshot_from_row(row)
    return snapshot


def advance_workflow(
    session: Session,
    owner_id: int,
    workflow_id: UUID,
    command: WorkflowCommand,
    *,
    request_id: UUID,
    expected_revision: int,
    step_id: str,
) -> WorkflowSnapshot | None:
    fingerprint = _action_fingerprint(workflow_id, expected_revision, step_id, command)
    with session.begin():
        row = lock_workflow(session, workflow_id, owner_id)
        if row is None:
            return None
        existing = session.get(
            WorkflowActionRequestRow, (owner_id, workflow_id, request_id)
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise RequestIdReused(
                    "request_id was already used with a different action payload"
                )
            return snapshot_from_record(existing.accepted_snapshot)
        if row.definition_version != CURRENT_WORKFLOW_DEFINITION_VERSION:
            raise UnsupportedWorkflowDefinition(
                f"unsupported workflow definition version {row.definition_version}"
            )
        if step_id != current_step_id(workflow_id, row.state):
            raise StaleWorkflowStep(
                "submitted step does not match the current workflow step"
            )
        if expected_revision != row.revision:
            raise StaleWorkflowStep(
                "submitted revision does not match the current workflow revision"
            )
        if row.state in (
            WorkflowState.COMPLETED.value,
            WorkflowState.CANCELLED.value,
        ):
            raise TerminalWorkflow(f"workflow is already {row.state}")
        if row.revision >= MAX_WORKFLOW_REVISION:
            raise RevisionExhausted(
                "workflow revision is exhausted; no further action is possible"
            )
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
        updated = (
            session.execute(
                update(WorkflowRow)
                .where(
                    WorkflowRow.public_id == workflow_id,
                    WorkflowRow.owner_id == owner_id,
                    WorkflowRow.revision == expected_revision,
                )
                .values(
                    revision=WorkflowRow.revision + 1,
                    state=decision.state.value,
                    involves_multiple_steps=decision.involves_multiple_steps,
                    proposed_todo_titles=list(decision.proposed_todo_titles),
                    completion_result=completion_result,
                )
                .returning(WorkflowRow),
                execution_options={"synchronize_session": False},
            )
            .scalars()
            .all()
        )
        if len(updated) != 1:
            raise StaleWorkflowStep(
                "submitted revision does not match the current workflow revision"
            )
        session.refresh(row)
        accepted = _snapshot_from_row(row)
        session.add(
            WorkflowActionRequestRow(
                owner_id=owner_id,
                workflow_id=workflow_id,
                request_id=request_id,
                request_fingerprint=fingerprint,
                accepted_snapshot=snapshot_to_record(accepted),
            )
        )
        session.flush()
        return accepted


def list_active_workflows(session: Session, owner_id: int) -> list[WorkflowSnapshot]:
    rows = (
        session.scalars(
            select(WorkflowRow)
            .where(
                WorkflowRow.owner_id == owner_id,
                or_(
                    WorkflowRow.definition_version
                    != CURRENT_WORKFLOW_DEFINITION_VERSION,
                    WorkflowRow.state.in_(
                        [state.value for state in ACTIVE_WORKFLOW_STATES]
                    ),
                ),
            )
            .order_by(WorkflowRow.id.desc())
        )
    ).all()
    snapshots: list[WorkflowSnapshot] = []
    for row in rows:
        if row.definition_version != CURRENT_WORKFLOW_DEFINITION_VERSION:
            raise UnsupportedWorkflowDefinition(
                f"unsupported workflow definition version {row.definition_version}"
            )
        snapshots.append(_snapshot_from_row(row))
    return snapshots
