"""Task 3: authenticated Python AG-UI agent stream.

RED-first contract tests for `app.agent` (`choose_clarification`,
`agent_events`, `agent_sse_body`) and the authenticated `POST /agent`
route. Deterministic fixtures only: no network, no paid calls, no secrets.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from ag_ui.core import (
    AssistantMessage,
    FunctionCall,
    RunAgentInput,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.agent import (
    AgentValidationError,
    agent_events,
    agent_sse_body,
    choose_clarification,
    validate_run_input,
)
from app.auth_repository import create_user
from app.main import create_app
from app.suggestion_provider import (
    InvalidSuggestionOutput,
    OpenRouterConfig,
    ProviderUnavailable,
    SuggestionsNotConfigured,
    SuggestionTimeout,
)
from app.suggestion_service import (
    SuggestionReservation,
    finish_suggestion,
    reserve_suggestion,
)
from app.todo_repository import list_todos as list_todo_rows
from app.workflow_domain import AnswerMultipleSteps, SubmitTasks, WorkflowState
from app.workflow_service import advance_workflow, start_workflow

READY_TITLES = ("Alpha one", "Beta two")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def setup_owner(session_factory: sessionmaker[Session], username: str = "owner") -> int:
    with session_factory() as session:
        owner = create_user(session, uuid4(), username, "hash")
        session.commit()
        return owner.id


def make_collecting(
    session_factory: sessionmaker[Session], owner_id: int
) -> tuple[UUID, int, str]:
    with session_factory() as session:
        initial = start_workflow(session, owner_id, "Plan birthday party", uuid4())
    with session_factory() as session:
        advance_workflow(
            session,
            owner_id,
            initial.id,
            AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=0,
            step_id=f"{initial.id}:ASSESS_TASK",
        )
    with session_factory() as session:
        collecting = advance_workflow(
            session,
            owner_id,
            initial.id,
            AnswerMultipleSteps(answer=True),
            request_id=uuid4(),
            expected_revision=1,
            step_id=f"{initial.id}:OFFER_BREAKDOWN",
        )
    assert collecting is not None
    assert collecting.state is WorkflowState.COLLECT_TASKS
    return initial.id, collecting.revision, f"{initial.id}:COLLECT_TASKS"


def make_ready(
    session_factory: sessionmaker[Session],
    owner_id: int,
    workflow_id: UUID,
    revision: int,
    step_id: str,
    titles: tuple[str, ...] = READY_TITLES,
) -> UUID:
    request_id = uuid4()
    with session_factory() as session:
        reservation = reserve_suggestion(
            session, owner_id, workflow_id, request_id, revision, step_id
        )
    assert isinstance(reservation, SuggestionReservation)
    with session_factory() as session:
        snapshot = finish_suggestion(
            session,
            owner_id,
            workflow_id,
            request_id,
            titles=tuple(titles),
            error_code=None,
        )
    assert snapshot is not None
    return request_id


def make_review(
    session_factory: sessionmaker[Session],
    owner_id: int,
    workflow_id: UUID,
    revision: int,
    step_id: str,
    titles: tuple[str, ...],
) -> Any:
    with session_factory() as session:
        snapshot = advance_workflow(
            session,
            owner_id,
            workflow_id,
            SubmitTasks(titles=tuple(titles)),
            request_id=uuid4(),
            expected_revision=revision,
            step_id=step_id,
        )
    assert snapshot is not None
    assert snapshot.state is WorkflowState.REVIEW
    return snapshot


def count_todos(session_factory: sessionmaker[Session], owner_id: int) -> int:
    with session_factory() as session:
        return len(list_todo_rows(session, owner_id))


def collect(gen: Any) -> list[Any]:
    async def _collect() -> list[Any]:
        return [event async for event in gen]

    return asyncio.run(_collect())


def agent_state(
    workflow_id: UUID,
    revision: int,
    step_id: str,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": 1,
        "expected_revision": revision,
        "step_id": step_id,
        "suggestion_request_id": str(request_id) if request_id is not None else None,
    }


def make_run(
    *,
    thread_id: UUID | str | None = None,
    run_id: UUID | str | None = None,
    messages: Any = (),
    state: Any = "omitted",
) -> RunAgentInput:
    payload: dict[str, Any] = {
        "threadId": str(thread_id) if thread_id is not None else str(uuid4()),
        "runId": str(run_id) if run_id is not None else str(uuid4()),
        "messages": [
            message.model_dump(by_alias=True)
            if hasattr(message, "model_dump")
            else message
            for message in messages
        ],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    if state != "omitted":
        payload["state"] = state
    return RunAgentInput.model_validate(payload)


def user_msg(mid: str, text: str) -> UserMessage:
    return UserMessage(id=mid, role="user", content=text)


def clarify_call_msg(
    mid: str,
    call_id: str,
    *,
    workflow_id: UUID,
    revision: int,
    step_id: str,
    field: str = "date",
    name: str = "clarify_plan",
    raw_arguments: str | None = None,
) -> AssistantMessage:
    arguments = (
        raw_arguments
        if raw_arguments is not None
        else json.dumps(
            {
                "contract_version": 1,
                "workflow_id": str(workflow_id),
                "expected_revision": revision,
                "step_id": step_id,
                "field": field,
            }
        )
    )
    return AssistantMessage(
        id=mid,
        tool_calls=[
            ToolCall(id=call_id, function=FunctionCall(name=name, arguments=arguments))
        ],
    )


def clarify_result_msg(mid: str, call_id: str, request_id: UUID) -> ToolMessage:
    return ToolMessage(
        id=mid,
        content=json.dumps(
            {"contract_version": 1, "suggestion_request_id": str(request_id)}
        ),
        tool_call_id=call_id,
    )


def review_call_msg(
    mid: str,
    call_id: str,
    *,
    workflow_id: UUID,
    revision: int,
    step_id: str,
    request_id: UUID,
    titles: tuple[str, ...],
) -> AssistantMessage:
    return AssistantMessage(
        id=mid,
        tool_calls=[
            ToolCall(
                id=call_id,
                function=FunctionCall(
                    name="review_todo_suggestions",
                    arguments=json.dumps(
                        {
                            "contract_version": 1,
                            "workflow_id": str(workflow_id),
                            "expected_revision": revision,
                            "step_id": step_id,
                            "suggestion_request_id": str(request_id),
                            "titles": list(titles),
                        }
                    ),
                ),
            )
        ],
    )


def review_result_msg(
    mid: str, call_id: str, request_id: UUID, accepted_revision: int
) -> ToolMessage:
    return ToolMessage(
        id=mid,
        content=json.dumps(
            {
                "contract_version": 1,
                "request_id": str(request_id),
                "accepted_revision": accepted_revision,
            }
        ),
        tool_call_id=call_id,
    )


def fake_choice(
    field: str = "location", calls: list[str] | None = None
) -> Any:
    async def choose(
        goal: str, config: object, *, transport: object = None
    ) -> str:
        if calls is not None:
            calls.append(goal)
        return field  # type: ignore[return-value]

    return choose


def openrouter_transport(
    content: dict[str, Any] | None,
    bodies: list[dict[str, Any]],
    *,
    status: int = 200,
    error_envelope: bool = False,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content.decode("utf-8")))
        if error_envelope:
            return httpx.Response(200, json={"error": {"message": "overloaded"}})
        inner = json.dumps(content)
        return httpx.Response(
            status,
            json={"choices": [{"message": {"content": inner}}]},
        )

    return httpx.MockTransport(handler)


def event_types(events: list[Any]) -> list[str]:
    return [event.type for event in events]


# ---------------------------------------------------------------------------
# choose_clarification: strict catalog-only OpenRouter decision
# ---------------------------------------------------------------------------


def test_choice_returns_catalog_field_and_sends_only_goal() -> None:
    bodies: list[dict[str, Any]] = []
    transport = openrouter_transport({"field": "location"}, bodies)

    async def _run() -> str:
        return await choose_clarification(
            "Plan birthday party",
            OpenRouterConfig(api_key="key", model="model"),
            transport=transport,
        )

    assert asyncio.run(_run()) == "location"
    assert len(bodies) == 1
    user_content = bodies[0]["messages"][1]["content"]
    assert user_content == "Plan birthday party"
    assert bodies[0]["max_tokens"] == 400
    schema = bodies[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["field"]["enum"] == [
        "date",
        "location",
        "people",
        "budget",
        "constraints",
    ]


def test_choice_rejects_non_catalog_field() -> None:
    bodies: list[dict[str, Any]] = []
    transport = openrouter_transport({"field": "music"}, bodies)

    async def _run() -> str:
        return await choose_clarification(
            "Plan birthday party",
            OpenRouterConfig(api_key="key", model="model"),
            transport=transport,
        )

    with pytest.raises(InvalidSuggestionOutput):
        asyncio.run(_run())


def test_choice_rejects_extra_keys_in_model_output() -> None:
    bodies: list[dict[str, Any]] = []
    transport = openrouter_transport({"field": "date", "question": "When?"}, bodies)

    async def _run() -> str:
        return await choose_clarification(
            "Plan birthday party",
            OpenRouterConfig(api_key="key", model="model"),
            transport=transport,
        )

    with pytest.raises(InvalidSuggestionOutput):
        asyncio.run(_run())


def test_choice_maps_provider_error_without_leak() -> None:
    bodies: list[dict[str, Any]] = []
    transport = openrouter_transport(None, bodies, error_envelope=True)

    async def _run() -> str:
        return await choose_clarification(
            "Plan birthday party",
            OpenRouterConfig(api_key="key", model="model"),
            transport=transport,
        )

    with pytest.raises(ProviderUnavailable):
        asyncio.run(_run())


def test_choice_checks_configuration_before_goal_validation() -> None:
    async def _run() -> str:
        return await choose_clarification(
            "",
            OpenRouterConfig(api_key="", model=""),
        )

    with pytest.raises(SuggestionsNotConfigured):
        asyncio.run(_run())


def test_choice_timeout_surfaces() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    async def _run() -> str:
        return await choose_clarification(
            "Plan birthday party",
            OpenRouterConfig(api_key="key", model="model"),
            transport=httpx.MockTransport(handler),
        )

    with pytest.raises(SuggestionTimeout):
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# agent_events: clarify path, exact order, zero writes
# ---------------------------------------------------------------------------


def test_clarify_path_emits_exact_event_order_without_todos(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    run_id = uuid4()
    run = make_run(
        thread_id=workflow_id,
        run_id=run_id,
        messages=[user_msg("u1", "Help me plan")],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice("location"))
        )

    assert event_types(events) == [
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "RUN_FINISHED",
    ]
    assert json.loads(events[2].delta)["field"] == "location"
    assert events[1].tool_call_id == f"{run_id}:clarify_plan:0"
    assert count_todos(session_factory, owner_id) == 0


def test_non_uuid_thread_id_fails_without_choice_call(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    calls: list[str] = []
    run = RunAgentInput.model_construct(
        threadId="not-a-uuid",
        runId=str(uuid4()),
        messages=[],
        tools=[],
        context=[],
        forwardedProps={},
        state={},
    )
    with session_factory() as session:
        events = collect(agent_events(run, owner_id, session, choose=fake_choice()))

    assert event_types(events)[0] == "RUN_STARTED"
    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_non_uuid_run_id_fails_without_choice_call(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    calls: list[str] = []
    run = RunAgentInput.model_construct(
        threadId=str(uuid4()),
        runId="nope",
        messages=[],
        tools=[],
        context=[],
        forwardedProps={},
        state={},
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_unknown_state_fields_fail_before_provider_call(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    state = agent_state(workflow_id, revision, step_id)
    state["forwarded"] = "nope"
    run = make_run(thread_id=workflow_id, messages=[], state=state)
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_missing_state_fails_without_choice_call(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    calls: list[str] = []
    run = make_run(thread_id=uuid4(), messages=[])
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_wrong_contract_version_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    state = agent_state(workflow_id, revision, step_id)
    state["contract_version"] = 2
    run = make_run(thread_id=workflow_id, messages=[], state=state)
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_too_many_messages_fail(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[user_msg(f"u{i}", "hi") for i in range(13)],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_oversize_text_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[user_msg("u1", "x" * 1001)],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_oversize_tool_result_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[ToolMessage(id="t1", content="x" * 4097, tool_call_id="c1")],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_tool_result_bound_counts_utf8_bytes(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    state = agent_state(workflow_id, revision, step_id)
    # "\u00e9" is 2 bytes in UTF-8: 2048 of them are exactly 4096 bytes.
    exact = make_run(
        thread_id=workflow_id,
        messages=[ToolMessage(id="t1", content="\u00e9" * 2048, tool_call_id="c1")],
        state=state,
    )
    validate_run_input(exact)
    over = make_run(
        thread_id=workflow_id,
        messages=[ToolMessage(id="t1", content="\u00e9" * 2049, tool_call_id="c1")],
        state=state,
    )
    with pytest.raises(AgentValidationError):
        validate_run_input(over)
    calls: list[str] = []
    with session_factory() as session:
        events = collect(
            agent_events(over, owner_id, session, choose=fake_choice(calls=calls))
        )
    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_tool_result_with_lone_surrogate_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    run = make_run(
        thread_id=workflow_id,
        messages=[ToolMessage(id="t1", content="\ud800", tool_call_id="c1")],
        state=agent_state(workflow_id, revision, step_id),
    )
    with pytest.raises(AgentValidationError):
        validate_run_input(run)


def test_owner_hidden_workflow_lookup_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory, "owner")
    other_id = setup_owner(session_factory, "other")
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, other_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_stale_revision_and_step_fail(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[],
        state=agent_state(workflow_id, revision + 1, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )
    assert event_types(events)[-1] == "RUN_ERROR"

    stale_step = agent_state(workflow_id, revision, f"{workflow_id}:REVIEW")
    run = make_run(thread_id=workflow_id, messages=[], state=stale_step)
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )
    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_non_collect_state_fails_closed(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    with session_factory() as session:
        initial = start_workflow(session, owner_id, "Another plan", uuid4())
    calls: list[str] = []
    run = make_run(
        thread_id=initial.id,
        messages=[],
        state=agent_state(initial.id, 0, f"{initial.id}:ASSESS_TASK"),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


# ---------------------------------------------------------------------------
# Ready-proposal precedence: state ID first, history second, choice last
# ---------------------------------------------------------------------------


def test_stale_supplied_suggestion_id_fails_without_choice_call(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[],
        state=agent_state(workflow_id, revision, step_id, request_id=uuid4()),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_current_ready_id_wins_over_history_without_choice_call(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    calls: list[str] = []
    # Contradictory history must not matter: the ready state ID takes precedence.
    bad_call = clarify_call_msg(
        "a9", "other-run:clarify_plan:0", workflow_id=workflow_id,
        revision=revision, step_id=step_id, name="unknown_tool",
        raw_arguments="{}",
    )
    bad_result = ToolMessage(id="t9", content="{}", tool_call_id="other-run:clarify_plan:0")
    run = make_run(
        thread_id=workflow_id,
        messages=[bad_call, bad_result],
        state=agent_state(workflow_id, revision, step_id, request_id=request_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events) == [
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "RUN_FINISHED",
    ]
    args = json.loads(events[2].delta)
    assert args["suggestion_request_id"] == str(request_id)
    assert tuple(args["titles"]) == READY_TITLES
    assert events[1].tool_call_name == "review_todo_suggestions"
    assert calls == []
    assert count_todos(session_factory, owner_id) == 0


def test_review_titles_reload_from_saved_suggestion(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    titles = ("First saved title", "Second saved title", "Third saved title")
    request_id = make_ready(
        session_factory, owner_id, workflow_id, revision, step_id, titles=titles
    )
    run = make_run(
        thread_id=workflow_id,
        messages=[],
        state=agent_state(workflow_id, revision, step_id, request_id=request_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice())
        )

    args = json.loads(events[2].delta)
    assert args["contract_version"] == 1
    assert args["workflow_id"] == str(workflow_id)
    assert args["expected_revision"] == revision
    assert args["step_id"] == step_id
    assert set(args) == {
        "contract_version",
        "workflow_id",
        "expected_revision",
        "step_id",
        "suggestion_request_id",
        "titles",
    }
    assert tuple(args["titles"]) == titles


def test_clarify_history_pair_continues_to_review(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    calls: list[str] = []
    run_id = uuid4()
    call_id = f"{run_id}:clarify_plan:0"
    run = make_run(
        thread_id=workflow_id,
        run_id=run_id,
        messages=[
            clarify_call_msg(
                "a1", call_id, workflow_id=workflow_id,
                revision=revision, step_id=step_id, field="budget",
            ),
            clarify_result_msg("t1", call_id, request_id),
        ],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[0] == "RUN_STARTED"
    assert event_types(events)[-1] == "RUN_FINISHED"
    assert events[1].tool_call_name == "review_todo_suggestions"
    assert calls == []


def test_mismatched_history_result_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    calls: list[str] = []
    run_id = uuid4()
    call_id = f"{run_id}:clarify_plan:0"
    run = make_run(
        thread_id=workflow_id,
        run_id=run_id,
        messages=[
            clarify_call_msg(
                "a1", call_id, workflow_id=workflow_id,
                revision=revision, step_id=step_id,
            ),
            clarify_result_msg("t1", call_id, uuid4()),
        ],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_unknown_tool_in_history_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[
            clarify_call_msg(
                "a1", "c1", workflow_id=workflow_id, revision=revision,
                step_id=step_id, name="evil_tool", raw_arguments="{}",
            ),
            ToolMessage(id="t1", content="{}", tool_call_id="c1"),
        ],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_duplicate_tool_id_in_history_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[
            clarify_call_msg(
                "a1", "dup", workflow_id=workflow_id,
                revision=revision, step_id=step_id,
            ),
            clarify_result_msg("t1", "dup", request_id),
            clarify_call_msg(
                "a2", "dup", workflow_id=workflow_id,
                revision=revision, step_id=step_id,
            ),
            clarify_result_msg("t2", "dup", request_id),
        ],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_malformed_history_arguments_fail(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[
            clarify_call_msg(
                "a1", "c1", workflow_id=workflow_id, revision=revision,
                step_id=step_id, raw_arguments="not json{",
            ),
            ToolMessage(id="t1", content="{}", tool_call_id="c1"),
        ],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_provider_failure_in_choice_ends_with_safe_error(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)

    async def failing_choose(
        goal: str, config: object, *, transport: object = None
    ) -> str:
        raise ProviderUnavailable("boom")

    run = make_run(
        thread_id=workflow_id,
        messages=[],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(agent_events(run, owner_id, session, choose=failing_choose))

    assert event_types(events)[0] == "RUN_STARTED"
    assert event_types(events)[-1] == "RUN_ERROR"
    assert "boom" not in events[-1].message
    assert count_todos(session_factory, owner_id) == 0


def test_malformed_choice_output_ends_with_safe_error(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    run = make_run(
        thread_id=workflow_id,
        messages=[],
        state=agent_state(workflow_id, revision, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice("karaoke"))
        )

    assert event_types(events)[-1] == "RUN_ERROR"


def test_same_run_id_retried_calls_model_again_without_journal(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    run_id = uuid4()

    def fresh_run() -> RunAgentInput:
        return make_run(
            thread_id=workflow_id,
            run_id=run_id,
            messages=[],
            state=agent_state(workflow_id, revision, step_id),
        )

    with session_factory() as session:
        first = collect(
            agent_events(fresh_run(), owner_id, session, choose=fake_choice(calls=calls))
        )
    with session_factory() as session:
        second = collect(
            agent_events(fresh_run(), owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(first)[-1] == "RUN_FINISHED"
    assert event_types(second)[-1] == "RUN_FINISHED"
    assert len(calls) == 2


def test_cancellation_during_choice_closes_provider_work(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    closed: list[str] = []

    async def slow_choose(
        goal: str, config: object, *, transport: object = None
    ) -> str:
        try:
            await asyncio.sleep(30)
        finally:
            closed.append("closed")
        return "date"

    run = make_run(
        thread_id=workflow_id,
        messages=[],
        state=agent_state(workflow_id, revision, step_id),
    )

    async def _scenario() -> list[Any]:
        seen: list[Any] = []
        with session_factory() as session:
            gen = agent_events(run, owner_id, session, choose=slow_choose)
            seen.append(await gen.__anext__())
            pending = asyncio.ensure_future(gen.__anext__())
            await asyncio.sleep(0.2)
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
            await gen.aclose()
            return seen

    seen = asyncio.run(_scenario())
    assert event_types(seen) == ["RUN_STARTED"]
    assert closed == ["closed"]


# ---------------------------------------------------------------------------
# REVIEW acknowledgement: valid result emits no-write start/finish
# ---------------------------------------------------------------------------


def test_valid_review_result_acknowledges_without_write(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    snapshot = make_review(
        session_factory, owner_id, workflow_id, revision, step_id, READY_TITLES
    )
    review_step = f"{workflow_id}:REVIEW"
    calls: list[str] = []
    call_id = "review-run:review_todo_suggestions:0"
    run = make_run(
        thread_id=workflow_id,
        run_id=uuid4(),
        messages=[
            review_call_msg(
                "a1", call_id, workflow_id=workflow_id, revision=revision,
                step_id=step_id, request_id=request_id, titles=READY_TITLES,
            ),
            review_result_msg("t1", call_id, request_id, snapshot.revision),
        ],
        state=agent_state(workflow_id, snapshot.revision, review_step),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events) == ["RUN_STARTED", "RUN_FINISHED"]
    assert calls == []
    assert count_todos(session_factory, owner_id) == 0


def test_review_result_with_stale_revision_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    snapshot = make_review(
        session_factory, owner_id, workflow_id, revision, step_id, READY_TITLES
    )
    calls: list[str] = []
    call_id = "review-run:review_todo_suggestions:0"
    run = make_run(
        thread_id=workflow_id,
        run_id=uuid4(),
        messages=[
            review_call_msg(
                "a1", call_id, workflow_id=workflow_id, revision=revision,
                step_id=step_id, request_id=request_id, titles=READY_TITLES,
            ),
            review_result_msg("t1", call_id, request_id, snapshot.revision + 1),
        ],
        state=agent_state(workflow_id, snapshot.revision, f"{workflow_id}:REVIEW"),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_review_state_without_valid_result_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    snapshot = make_review(
        session_factory, owner_id, workflow_id, revision, step_id, READY_TITLES
    )
    calls: list[str] = []
    run = make_run(
        thread_id=workflow_id,
        messages=[user_msg("u1", "hello")],
        state=agent_state(workflow_id, snapshot.revision, f"{workflow_id}:REVIEW"),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def _review_ack_run(
    workflow_id: UUID,
    revision: int,
    step_id: str,
    review_revision: int,
    request_id: UUID,
    titles: tuple[str, ...],
    call_step_id: str | None = None,
) -> RunAgentInput:
    call_id = "review-run:review_todo_suggestions:0"
    return make_run(
        thread_id=workflow_id,
        run_id=uuid4(),
        messages=[
            review_call_msg(
                "a1", call_id, workflow_id=workflow_id, revision=revision,
                step_id=call_step_id or step_id, request_id=request_id,
                titles=titles,
            ),
            review_result_msg("t1", call_id, request_id, review_revision),
        ],
        state=agent_state(workflow_id, review_revision, f"{workflow_id}:REVIEW"),
    )


def test_review_call_with_stale_revision_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    snapshot = make_review(
        session_factory, owner_id, workflow_id, revision, step_id, READY_TITLES
    )
    calls: list[str] = []
    run = _review_ack_run(
        workflow_id, snapshot.revision, step_id, snapshot.revision,
        request_id, READY_TITLES,
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_review_call_with_wrong_step_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    snapshot = make_review(
        session_factory, owner_id, workflow_id, revision, step_id, READY_TITLES
    )
    calls: list[str] = []
    run = _review_ack_run(
        workflow_id, revision, step_id, snapshot.revision,
        request_id, READY_TITLES, call_step_id=f"{workflow_id}:REVIEW",
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_review_call_with_mismatched_titles_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    request_id = make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    snapshot = make_review(
        session_factory, owner_id, workflow_id, revision, step_id, READY_TITLES
    )
    calls: list[str] = []
    run = _review_ack_run(
        workflow_id, revision, step_id, snapshot.revision,
        request_id, ("Fabricated title one", "Fabricated title two"),
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []


def test_review_ack_with_older_ready_request_fails(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    older_id = make_ready(
        session_factory, owner_id, workflow_id, revision, step_id,
        titles=("Older saved one", "Older saved two"),
    )
    newer_titles = ("Newer saved one", "Newer saved two")
    make_ready(
        session_factory, owner_id, workflow_id, revision, step_id,
        titles=newer_titles,
    )
    snapshot = make_review(
        session_factory, owner_id, workflow_id, revision, step_id, newer_titles
    )
    calls: list[str] = []
    run = _review_ack_run(
        workflow_id, revision, step_id, snapshot.revision,
        older_id, newer_titles,
    )
    with session_factory() as session:
        events = collect(
            agent_events(run, owner_id, session, choose=fake_choice(calls=calls))
        )

    assert event_types(events)[-1] == "RUN_ERROR"
    assert calls == []
    assert count_todos(session_factory, owner_id) == 0


def test_db_backed_error_paths_close_read_transaction(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    calls: list[str] = []
    stale_run = make_run(
        thread_id=workflow_id,
        messages=[],
        state=agent_state(workflow_id, revision + 1, step_id),
    )
    with session_factory() as session:
        events = collect(
            agent_events(stale_run, owner_id, session, choose=fake_choice(calls=calls))
        )
        assert event_types(events)[-1] == "RUN_ERROR"
        assert not session.in_transaction()

    make_ready(session_factory, owner_id, workflow_id, revision, step_id)
    snapshot = make_review(
        session_factory, owner_id, workflow_id, revision, step_id, READY_TITLES
    )
    invalid_review_run = make_run(
        thread_id=workflow_id,
        messages=[user_msg("u1", "hello")],
        state=agent_state(workflow_id, snapshot.revision, f"{workflow_id}:REVIEW"),
    )
    with session_factory() as session:
        events = collect(
            agent_events(
                invalid_review_run, owner_id, session,
                choose=fake_choice(calls=calls),
            )
        )
        assert event_types(events)[-1] == "RUN_ERROR"
        assert not session.in_transaction()

    with session_factory() as session:
        assessing = start_workflow(session, owner_id, "Another plan", uuid4())
    assessing_run = make_run(
        thread_id=assessing.id,
        messages=[],
        state=agent_state(assessing.id, 0, f"{assessing.id}:ASSESS_TASK"),
    )
    with session_factory() as session:
        events = collect(
            agent_events(
                assessing_run, owner_id, session, choose=fake_choice(calls=calls)
            )
        )
        assert event_types(events)[-1] == "RUN_ERROR"
        assert not session.in_transaction()
    assert calls == []


# ---------------------------------------------------------------------------
# Route boundary: auth, bounds, SSE media type, disconnect
# ---------------------------------------------------------------------------


@contextmanager
def route_client(
    session_factory: sessionmaker[Session],
    database_session: Session,
    agent_choice: Any,
) -> Any:
    del database_session
    with TestClient(create_app(session_factory, agent_choice=agent_choice)) as client:
        yield client


def route_auth_headers(client: TestClient, username: str = "alice") -> dict[str, str]:
    signup = client.post(
        "/auth/signup", json={"username": username, "password": "long-enough-password"}
    )
    assert signup.status_code == 201
    login = client.post(
        "/auth/login", json={"username": username, "password": "long-enough-password"}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def route_body(
    workflow_id: UUID,
    run_id: UUID,
    revision: int,
    step_id: str,
    request_id: UUID | None = None,
) -> dict[str, Any]:
    return {
        "threadId": str(workflow_id),
        "runId": str(run_id),
        "messages": [{"id": "u1", "role": "user", "content": "Help me plan"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
        "state": agent_state(workflow_id, revision, step_id, request_id),
    }


def decode_sse(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def test_route_requires_authentication(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    with route_client(session_factory, database_session, fake_choice()) as client:
        response = client.post(
            "/agent",
            json=route_body(uuid4(), uuid4(), 0, "step"),
        )
        assert response.status_code == 401


def test_route_rejects_malformed_envelope(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    with route_client(session_factory, database_session, fake_choice()) as client:
        headers = route_auth_headers(client)
        response = client.post("/agent", json={"runId": str(uuid4())}, headers=headers)
        assert response.status_code == 422


def test_route_rejects_oversize_body(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    with route_client(session_factory, database_session, fake_choice()) as client:
        headers = route_auth_headers(client)
        body = route_body(uuid4(), uuid4(), 0, "step")
        body["messages"] = [{"id": "u1", "role": "user", "content": "x" * (33 * 1024)}]
        response = client.post("/agent", json=body, headers=headers)
        assert response.status_code == 413


def test_route_rejects_too_many_messages(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    with route_client(session_factory, database_session, fake_choice()) as client:
        headers = route_auth_headers(client)
        body = route_body(uuid4(), uuid4(), 0, "step")
        body["messages"] = [
            {"id": f"u{i}", "role": "user", "content": "hi"} for i in range(13)
        ]
        response = client.post("/agent", json=body, headers=headers)
        assert response.status_code == 422


def test_route_rejects_oversize_text(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    with route_client(session_factory, database_session, fake_choice()) as client:
        headers = route_auth_headers(client)
        body = route_body(uuid4(), uuid4(), 0, "step")
        body["messages"] = [{"id": "u1", "role": "user", "content": "x" * 1001}]
        response = client.post("/agent", json=body, headers=headers)
        assert response.status_code == 422


def test_route_rejects_oversize_tool_result(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    with route_client(session_factory, database_session, fake_choice()) as client:
        headers = route_auth_headers(client)
        body = route_body(uuid4(), uuid4(), 0, "step")
        body["messages"] = [
            {"id": "t1", "role": "tool", "content": "x" * 4097, "toolCallId": "c1"}
        ]
        response = client.post("/agent", json=body, headers=headers)
        assert response.status_code == 422


def test_route_rejects_unknown_state_fields_before_provider_call(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    calls: list[str] = []
    with route_client(
        session_factory, database_session, fake_choice(calls=calls)
    ) as client:
        headers = route_auth_headers(client)
        body = route_body(uuid4(), uuid4(), 0, "step")
        assert isinstance(body["state"], dict)
        body["state"]["extra"] = "rejected"
        response = client.post("/agent", json=body, headers=headers)
        assert response.status_code == 422
        assert calls == []


def test_route_streams_clarify_events_with_streaming_media_type(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    calls: list[str] = []
    with route_client(
        session_factory, database_session, fake_choice("budget", calls)
    ) as client:
        headers = route_auth_headers(client)
        owner_workflows = client.post(
            "/todo-workflows",
            json={"request_id": str(uuid4()), "title": "Plan birthday party"},
            headers=headers,
        )
        assert owner_workflows.status_code == 201
        workflow_id = UUID(owner_workflows.json()["workflow_id"])
        for expected_revision, action in (
            (0, {"action": "answer_multiple_steps", "answer": True}),
            (1, {"action": "answer_multiple_steps", "answer": True}),
        ):
            current = client.get(f"/todo-workflows/{workflow_id}", headers=headers).json()
            advance = client.post(
                f"/todo-workflows/{workflow_id}/actions",
                json={
                    "request_id": str(uuid4()),
                    "expected_revision": expected_revision,
                    "step_id": current["view"]["step_id"],
                    "action": action,
                },
                headers=headers,
            )
            assert advance.status_code == 200
        current = client.get(f"/todo-workflows/{workflow_id}", headers=headers).json()
        run_id = uuid4()
        response = client.post(
            "/agent",
            json=route_body(
                workflow_id, run_id, current["revision"], current["view"]["step_id"]
            ),
            headers=headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        decoded = decode_sse(response.text)
        assert [item["type"] for item in decoded] == [
            "RUN_STARTED",
            "TOOL_CALL_START",
            "TOOL_CALL_ARGS",
            "TOOL_CALL_END",
            "RUN_FINISHED",
        ]
        assert decoded[1]["toolCallId"] == f"{run_id}:clarify_plan:0"
        assert json.loads(decoded[2]["delta"])["field"] == "budget"
        assert calls == ["Plan birthday party"]


def test_stream_generator_stops_and_cancels_on_disconnect(
    database_session: Session, session_factory: sessionmaker[Session]
) -> None:
    del database_session
    owner_id = setup_owner(session_factory)
    workflow_id, revision, step_id = make_collecting(session_factory, owner_id)
    closed: list[str] = []

    async def slow_choose(
        goal: str, config: object, *, transport: object = None
    ) -> str:
        try:
            await asyncio.sleep(30)
        finally:
            closed.append("closed")
        return "date"

    run = make_run(
        thread_id=workflow_id,
        messages=[],
        state=agent_state(workflow_id, revision, step_id),
    )
    disconnected = False

    async def is_disconnected() -> bool:
        return disconnected

    async def _scenario() -> str:
        nonlocal disconnected
        with session_factory() as session:
            gen = agent_sse_body(
                run, owner_id, session,
                choose=slow_choose, is_disconnected=is_disconnected,
            )
            first = await gen.__anext__()
            assert "RUN_STARTED" in first
            pending = asyncio.ensure_future(gen.__anext__())
            await asyncio.sleep(0.05)
            disconnected = True
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
            await gen.aclose()
            return first

    first_chunk = asyncio.run(_scenario())
    assert "RUN_STARTED" in first_chunk
    assert closed == ["closed"]
