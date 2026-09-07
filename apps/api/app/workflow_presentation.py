from typing import Literal, TypedDict
from uuid import UUID

from app.workflow_domain import (
    MAX_BREAKDOWN_TITLES,
    MIN_BREAKDOWN_TITLES,
    WorkflowSnapshot,
    WorkflowState,
)


class Choice(TypedDict):
    id: Literal["yes", "no"]
    label: str


class PresentedTodo(TypedDict):
    id: UUID | str
    title: str
    completed: bool


class YesNoView(TypedDict):
    type: Literal["yes_no"]
    step_id: str
    title: str
    question: str
    actions: list[Choice]


class TaskBreakdownView(TypedDict):
    type: Literal["task_breakdown"]
    step_id: str
    title: str
    min_titles: int
    max_titles: int


class ReviewView(TypedDict):
    type: Literal["review"]
    step_id: str
    title: str
    proposed_titles: list[str]


class CompletionView(TypedDict):
    type: Literal["completion"]
    step_id: str
    title: str
    outcome: Literal["completed", "cancelled"]
    created_todos: list[PresentedTodo]


WorkflowView = YesNoView | TaskBreakdownView | ReviewView | CompletionView


def present_workflow(snapshot: WorkflowSnapshot) -> WorkflowView:
    step_id = f"{snapshot.id}:{snapshot.state.value}"
    if snapshot.state in (WorkflowState.ASSESS_TASK, WorkflowState.OFFER_BREAKDOWN):
        question = (
            "Does this task involve multiple steps?"
            if snapshot.state == WorkflowState.ASSESS_TASK
            else "Would you like to split it into smaller todos?"
        )
        return {
            "type": "yes_no",
            "step_id": step_id,
            "title": snapshot.title,
            "question": question,
            "actions": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
        }
    if snapshot.state == WorkflowState.COLLECT_TASKS:
        return {
            "type": "task_breakdown",
            "step_id": step_id,
            "title": "Break it into smaller todos",
            "min_titles": MIN_BREAKDOWN_TITLES,
            "max_titles": MAX_BREAKDOWN_TITLES,
        }
    if snapshot.state == WorkflowState.REVIEW:
        return {
            "type": "review",
            "step_id": step_id,
            "title": "Review your plan",
            "proposed_titles": list(snapshot.proposed_todo_titles),
        }
    completed = snapshot.state == WorkflowState.COMPLETED
    return {
        "type": "completion",
        "step_id": step_id,
        "title": "Plan complete" if completed else "Plan cancelled",
        "outcome": "completed" if completed else "cancelled",
        "created_todos": (
            [
                {"id": item.id, "title": item.title, "completed": item.completed}
                for item in snapshot.created_todos or ()
            ]
            if completed
            else []
        ),
    }
