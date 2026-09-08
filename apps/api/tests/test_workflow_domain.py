from uuid import UUID

import pytest

from app.workflow_domain import (
    AnswerMultipleSteps,
    Cancel,
    Confirm,
    InvalidWorkflowAction,
    InvalidWorkflowInput,
    SubmitTasks,
    TerminalWorkflow,
    WorkflowCommand,
    WorkflowSnapshot,
    WorkflowState,
    create_initial_snapshot,
    create_submit_tasks,
    transition,
)

WORKFLOW_ID = UUID("6fc33b84-16a8-4d8e-ae94-fc50bb457d72")
TITLE = "Plan birthday party"


def assess_snapshot() -> WorkflowSnapshot:
    return create_initial_snapshot(WORKFLOW_ID, TITLE)


def offer_snapshot() -> WorkflowSnapshot:
    snapshot = assess_snapshot()
    decision = transition(snapshot, AnswerMultipleSteps(answer=True))
    return WorkflowSnapshot(
        id=snapshot.id,
        state=decision.state,
        title=snapshot.title,
        involves_multiple_steps=decision.involves_multiple_steps,
        proposed_todo_titles=decision.proposed_todo_titles,
        created_todos=None,
    )


def collect_snapshot() -> WorkflowSnapshot:
    snapshot = offer_snapshot()
    decision = transition(snapshot, AnswerMultipleSteps(answer=True))
    return WorkflowSnapshot(
        id=snapshot.id,
        state=decision.state,
        title=snapshot.title,
        involves_multiple_steps=decision.involves_multiple_steps,
        proposed_todo_titles=decision.proposed_todo_titles,
        created_todos=None,
    )


def review_snapshot(proposals: tuple[str, ...] = (TITLE,)) -> WorkflowSnapshot:
    return WorkflowSnapshot(
        id=WORKFLOW_ID,
        state=WorkflowState.REVIEW,
        title=TITLE,
        involves_multiple_steps=False,
        proposed_todo_titles=proposals,
        created_todos=None,
    )


def test_yes_in_assess_task_now_offers_breakdown() -> None:
    decision = transition(assess_snapshot(), AnswerMultipleSteps(answer=True))
    assert decision.state == WorkflowState.OFFER_BREAKDOWN
    assert decision.involves_multiple_steps is True
    assert decision.proposed_todo_titles == ()


def test_offer_yes_collects_and_offer_no_reviews_original() -> None:
    snapshot = offer_snapshot()
    assert snapshot.state == WorkflowState.OFFER_BREAKDOWN
    collect = transition(snapshot, AnswerMultipleSteps(answer=True))
    assert collect.state == WorkflowState.COLLECT_TASKS
    assert collect.involves_multiple_steps is True
    review = transition(snapshot, AnswerMultipleSteps(answer=False))
    assert review.state == WorkflowState.REVIEW
    assert review.involves_multiple_steps is True
    assert review.proposed_todo_titles == (TITLE,)


def test_create_initial_snapshot_canonicalizes_title() -> None:
    snapshot = create_initial_snapshot(WORKFLOW_ID, "  Plan birthday party  ")

    assert snapshot.id == WORKFLOW_ID
    assert snapshot.state == WorkflowState.ASSESS_TASK
    assert snapshot.title == "Plan birthday party"
    assert snapshot.involves_multiple_steps is None
    assert snapshot.proposed_todo_titles == ()
    assert snapshot.created_todos is None


def test_create_initial_snapshot_rejects_invalid_title() -> None:
    with pytest.raises(InvalidWorkflowInput):
        create_initial_snapshot(WORKFLOW_ID, "   ")


@pytest.mark.parametrize(
    ("answer", "state", "proposals"),
    [
        (True, WorkflowState.OFFER_BREAKDOWN, ()),
        (False, WorkflowState.REVIEW, ("Plan birthday party",)),
    ],
)
def test_assessment_branches(
    answer: bool, state: WorkflowState, proposals: tuple[str, ...]
) -> None:
    decision = transition(assess_snapshot(), AnswerMultipleSteps(answer=answer))

    assert decision.state == state
    assert decision.involves_multiple_steps is answer
    assert decision.proposed_todo_titles == proposals
    assert decision.todo_titles_to_create == ()


@pytest.mark.parametrize(
    "state",
    [
        WorkflowState.ASSESS_TASK,
        WorkflowState.OFFER_BREAKDOWN,
        WorkflowState.COLLECT_TASKS,
        WorkflowState.REVIEW,
    ],
)
def test_cancel_is_valid_from_every_active_state(state: WorkflowState) -> None:
    snapshot = {
        WorkflowState.ASSESS_TASK: assess_snapshot(),
        WorkflowState.OFFER_BREAKDOWN: offer_snapshot(),
        WorkflowState.COLLECT_TASKS: collect_snapshot(),
        WorkflowState.REVIEW: review_snapshot(),
    }[state]

    decision = transition(snapshot, Cancel())

    assert decision.state == WorkflowState.CANCELLED
    assert decision.todo_titles_to_create == ()


@pytest.mark.parametrize(
    ("state", "command"),
    [
        (WorkflowState.ASSESS_TASK, Confirm()),
        (
            WorkflowState.ASSESS_TASK,
            SubmitTasks(("Send invitations", "Buy decorations")),
        ),
        (WorkflowState.COLLECT_TASKS, AnswerMultipleSteps(False)),
        (WorkflowState.COLLECT_TASKS, Confirm()),
        (WorkflowState.REVIEW, AnswerMultipleSteps(True)),
        (
            WorkflowState.REVIEW,
            SubmitTasks(("Send invitations", "Buy decorations")),
        ),
    ],
)
def test_wrong_state_action_rejects_without_mutating_snapshot(
    state: WorkflowState, command: WorkflowCommand
) -> None:
    snapshot = {
        WorkflowState.ASSESS_TASK: assess_snapshot(),
        WorkflowState.COLLECT_TASKS: collect_snapshot(),
        WorkflowState.REVIEW: review_snapshot(),
    }[state]
    before = snapshot

    with pytest.raises(InvalidWorkflowAction):
        transition(snapshot, command)

    assert snapshot == before


def test_collection_enters_review() -> None:
    decision = transition(
        collect_snapshot(),
        SubmitTasks(("Send invitations", "Buy decorations")),
    )

    assert decision.state == WorkflowState.REVIEW
    assert decision.proposed_todo_titles == ("Send invitations", "Buy decorations")
    assert decision.todo_titles_to_create == ()


def test_confirm_returns_exact_stored_proposals() -> None:
    proposals = ("Send invitations", "Buy decorations", "Send invitations")
    decision = transition(review_snapshot(proposals), Confirm())

    assert decision.state == WorkflowState.COMPLETED
    assert decision.todo_titles_to_create == proposals


@pytest.mark.parametrize(
    "state",
    [WorkflowState.COMPLETED, WorkflowState.CANCELLED],
)
@pytest.mark.parametrize(
    "command",
    [
        AnswerMultipleSteps(True),
        SubmitTasks(("Send invitations", "Buy decorations")),
        Confirm(),
        Cancel(),
    ],
)
def test_terminal_states_reject_every_command(
    state: WorkflowState, command: WorkflowCommand
) -> None:
    snapshot = WorkflowSnapshot(
        id=WORKFLOW_ID,
        state=state,
        title=TITLE,
        involves_multiple_steps=False,
        proposed_todo_titles=(TITLE,),
        created_todos=None,
    )

    with pytest.raises(TerminalWorkflow):
        transition(snapshot, command)


@pytest.mark.parametrize("count", [2, 10])
def test_submit_tasks_accepts_two_through_ten(count: int) -> None:
    titles = tuple(f"Task {index}" for index in range(count))

    assert create_submit_tasks(titles).titles == titles


@pytest.mark.parametrize("count", [0, 1, 11])
def test_submit_tasks_rejects_outside_two_through_ten(count: int) -> None:
    with pytest.raises(InvalidWorkflowInput):
        create_submit_tasks(tuple(f"Task {index}" for index in range(count)))


def test_submit_tasks_canonicalizes_and_preserves_order_and_duplicates() -> None:
    command = create_submit_tasks(
        ("  Send invitations  ", "Buy decorations", "Send invitations")
    )

    assert command.titles == ("Send invitations", "Buy decorations", "Send invitations")


def test_submit_tasks_rejects_invalid_individual_title() -> None:
    with pytest.raises(InvalidWorkflowInput):
        create_submit_tasks(("Send invitations", "   "))


def test_transition_does_not_mutate_supplied_snapshot() -> None:
    snapshot = collect_snapshot()
    before = snapshot

    transition(snapshot, SubmitTasks(("Send invitations", "Buy decorations")))

    assert snapshot == before


def test_valid_paths_never_repeat_a_state() -> None:
    commands: tuple[WorkflowCommand, ...] = (
        AnswerMultipleSteps(False),
        AnswerMultipleSteps(True),
        create_submit_tasks(("Send invitations", "Order birthday cake")),
        Confirm(),
        Cancel(),
    )

    def walk(snapshot: WorkflowSnapshot, seen: frozenset[WorkflowState]) -> None:
        assert snapshot.state not in seen
        if snapshot.state in (WorkflowState.COMPLETED, WorkflowState.CANCELLED):
            return
        for command in commands:
            try:
                decision = transition(snapshot, command)
            except InvalidWorkflowAction:
                continue
            walk(
                WorkflowSnapshot(
                    id=snapshot.id,
                    state=decision.state,
                    title=snapshot.title,
                    involves_multiple_steps=decision.involves_multiple_steps,
                    proposed_todo_titles=decision.proposed_todo_titles,
                    created_todos=() if decision.state == WorkflowState.COMPLETED else None,
                ),
                seen | {snapshot.state},
            )

    walk(assess_snapshot(), frozenset())


def test_submit_tasks_or_confirm_in_offer_is_wrong_state() -> None:
    snapshot = offer_snapshot()
    with pytest.raises(InvalidWorkflowAction):
        transition(snapshot, create_submit_tasks(("Send invitations", "Order birthday cake")))
    with pytest.raises(InvalidWorkflowAction):
        transition(snapshot, Confirm())
