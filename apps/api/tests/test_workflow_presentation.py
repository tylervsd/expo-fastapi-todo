from dataclasses import replace

import pytest

from app.workflow_domain import CreatedTodo, WorkflowSnapshot, WorkflowState
from app.workflow_presentation import present_workflow

WORKFLOW_ID = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72"
TODO_ID = "5f699d61-9449-407e-aa37-89e759b78df0"


def snapshot(state: WorkflowState) -> WorkflowSnapshot:
    return WorkflowSnapshot(
        id=WORKFLOW_ID,
        state=state,
        title="Plan birthday party",
        involves_multiple_steps=state != WorkflowState.ASSESS_TASK,
        proposed_todo_titles=(),
        created_todos=None,
    )


@pytest.mark.parametrize(
    ("state", "question"),
    [
        (WorkflowState.ASSESS_TASK, "Does this task involve multiple steps?"),
        (WorkflowState.OFFER_BREAKDOWN, "Would you like to split it into smaller todos?"),
    ],
)
def test_yes_no_views_are_exact(state: WorkflowState, question: str) -> None:
    assert present_workflow(snapshot(state)) == {
        "type": "yes_no",
        "step_id": f"{WORKFLOW_ID}:{state.value}",
        "title": "Plan birthday party",
        "question": question,
        "actions": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
    }


def test_breakdown_and_review_views_are_exact() -> None:
    assert present_workflow(snapshot(WorkflowState.COLLECT_TASKS)) == {
        "type": "task_breakdown",
        "step_id": f"{WORKFLOW_ID}:COLLECT_TASKS",
        "title": "Break it into smaller todos",
        "min_titles": 2,
        "max_titles": 10,
    }
    review = replace(
        snapshot(WorkflowState.REVIEW),
        proposed_todo_titles=("Send invitations", "Order birthday cake"),
    )
    assert present_workflow(review) == {
        "type": "review",
        "step_id": f"{WORKFLOW_ID}:REVIEW",
        "title": "Review your plan",
        "proposed_titles": ["Send invitations", "Order birthday cake"],
    }


def test_terminal_views_are_exact() -> None:
    todo = CreatedTodo(id=TODO_ID, title="Plan birthday party", completed=False)
    completed = replace(snapshot(WorkflowState.COMPLETED), created_todos=(todo,))
    assert present_workflow(completed) == {
        "type": "completion",
        "step_id": f"{WORKFLOW_ID}:COMPLETED",
        "title": "Plan complete",
        "outcome": "completed",
        "created_todos": [
            {"id": TODO_ID, "title": "Plan birthday party", "completed": False}
        ],
    }
    assert present_workflow(snapshot(WorkflowState.CANCELLED)) == {
        "type": "completion",
        "step_id": f"{WORKFLOW_ID}:CANCELLED",
        "title": "Plan cancelled",
        "outcome": "cancelled",
        "created_todos": [],
    }


def test_mapping_same_snapshot_is_stable() -> None:
    current = snapshot(WorkflowState.OFFER_BREAKDOWN)
    assert present_workflow(current) == present_workflow(current)
