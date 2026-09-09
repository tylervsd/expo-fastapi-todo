from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.title_validation import canonicalize_title


class WorkflowState(StrEnum):
    ASSESS_TASK = "ASSESS_TASK"
    OFFER_BREAKDOWN = "OFFER_BREAKDOWN"
    COLLECT_TASKS = "COLLECT_TASKS"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvalidWorkflowAction(ValueError):
    """A well-formed command used in the wrong active state."""


class TerminalWorkflow(ValueError):
    """Any command issued against a COMPLETED or CANCELLED workflow."""


class InvalidWorkflowInput(ValueError):
    """Titles or title lists that fail shared canonical validation."""


class UnsupportedWorkflowDefinition(ValueError):
    """A saved workflow uses definition rules this server does not support."""


MAX_WORKFLOW_REVISION = 2147483647
CURRENT_WORKFLOW_DEFINITION_VERSION = 1


@dataclass(frozen=True)
class CreatedTodo:
    id: UUID
    title: str
    completed: bool


@dataclass(frozen=True)
class WorkflowSnapshot:
    id: UUID
    state: WorkflowState
    title: str
    involves_multiple_steps: bool | None
    proposed_todo_titles: tuple[str, ...]
    created_todos: tuple[CreatedTodo, ...] | None
    revision: int
    definition_version: int


@dataclass(frozen=True)
class AnswerMultipleSteps:
    answer: bool


@dataclass(frozen=True)
class SubmitTasks:
    titles: tuple[str, ...]


@dataclass(frozen=True)
class Confirm:
    pass


@dataclass(frozen=True)
class Cancel:
    pass


WorkflowCommand = AnswerMultipleSteps | SubmitTasks | Confirm | Cancel


@dataclass(frozen=True)
class TransitionDecision:
    state: WorkflowState
    involves_multiple_steps: bool | None
    proposed_todo_titles: tuple[str, ...]
    todo_titles_to_create: tuple[str, ...]


MIN_BREAKDOWN_TITLES = 2
MAX_BREAKDOWN_TITLES = 10


def create_initial_snapshot(workflow_id: UUID, title: str) -> WorkflowSnapshot:
    try:
        canonical = canonicalize_title(title)
    except ValueError as exc:
        raise InvalidWorkflowInput(str(exc)) from exc
    return WorkflowSnapshot(
        id=workflow_id,
        state=WorkflowState.ASSESS_TASK,
        title=canonical,
        involves_multiple_steps=None,
        proposed_todo_titles=(),
        created_todos=None,
        revision=0,
        definition_version=CURRENT_WORKFLOW_DEFINITION_VERSION,
    )


def create_submit_tasks(titles: Sequence[str]) -> SubmitTasks:
    canonical: list[str] = []
    for title in titles:
        try:
            canonical.append(canonicalize_title(title))
        except ValueError as exc:
            raise InvalidWorkflowInput(str(exc)) from exc
    if not MIN_BREAKDOWN_TITLES <= len(canonical) <= MAX_BREAKDOWN_TITLES:
        raise InvalidWorkflowInput(
            "breakdown requires 2 to 10 todo titles, "
            f"received {len(canonical)}"
        )
    return SubmitTasks(titles=tuple(canonical))


def _cancelled_from(snapshot: WorkflowSnapshot) -> TransitionDecision:
    return TransitionDecision(
        state=WorkflowState.CANCELLED,
        involves_multiple_steps=snapshot.involves_multiple_steps,
        proposed_todo_titles=snapshot.proposed_todo_titles,
        todo_titles_to_create=(),
    )


def transition(
    snapshot: WorkflowSnapshot, command: WorkflowCommand
) -> TransitionDecision:
    if snapshot.definition_version != CURRENT_WORKFLOW_DEFINITION_VERSION:
        raise UnsupportedWorkflowDefinition(
            f"unsupported workflow definition version "
            f"{snapshot.definition_version}"
        )
    if snapshot.state in (WorkflowState.COMPLETED, WorkflowState.CANCELLED):
        raise TerminalWorkflow(f"workflow is already {snapshot.state.value}")
    if isinstance(command, Cancel):
        return _cancelled_from(snapshot)
    match snapshot.state:
        case WorkflowState.ASSESS_TASK:
            if isinstance(command, AnswerMultipleSteps):
                if command.answer:
                    return TransitionDecision(
                        state=WorkflowState.OFFER_BREAKDOWN,
                        involves_multiple_steps=True,
                        proposed_todo_titles=(),
                        todo_titles_to_create=(),
                    )
                return TransitionDecision(
                    state=WorkflowState.REVIEW,
                    involves_multiple_steps=False,
                    proposed_todo_titles=(snapshot.title,),
                    todo_titles_to_create=(),
                )
            raise InvalidWorkflowAction(
                f"{type(command).__name__} is not valid in ASSESS_TASK"
            )
        case WorkflowState.OFFER_BREAKDOWN:
            if isinstance(command, AnswerMultipleSteps):
                if command.answer:
                    return TransitionDecision(
                        state=WorkflowState.COLLECT_TASKS,
                        involves_multiple_steps=snapshot.involves_multiple_steps,
                        proposed_todo_titles=(),
                        todo_titles_to_create=(),
                    )
                return TransitionDecision(
                    state=WorkflowState.REVIEW,
                    involves_multiple_steps=snapshot.involves_multiple_steps,
                    proposed_todo_titles=(snapshot.title,),
                    todo_titles_to_create=(),
                )
            raise InvalidWorkflowAction(
                f"{type(command).__name__} is not valid in OFFER_BREAKDOWN"
            )
        case WorkflowState.COLLECT_TASKS:
            if isinstance(command, SubmitTasks):
                return TransitionDecision(
                    state=WorkflowState.REVIEW,
                    involves_multiple_steps=snapshot.involves_multiple_steps,
                    proposed_todo_titles=command.titles,
                    todo_titles_to_create=(),
                )
            raise InvalidWorkflowAction(
                f"{type(command).__name__} is not valid in COLLECT_TASKS"
            )
        case WorkflowState.REVIEW:
            if isinstance(command, Confirm):
                return TransitionDecision(
                    state=WorkflowState.COMPLETED,
                    involves_multiple_steps=snapshot.involves_multiple_steps,
                    proposed_todo_titles=snapshot.proposed_todo_titles,
                    todo_titles_to_create=snapshot.proposed_todo_titles,
                )
            raise InvalidWorkflowAction(
                f"{type(command).__name__} is not valid in REVIEW"
            )
        case _:
            raise TerminalWorkflow(f"workflow is already {snapshot.state.value}")
