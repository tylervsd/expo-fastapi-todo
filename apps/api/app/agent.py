"""Authenticated AG-UI agent stream (Phase 11).

One FastAPI route streams an OpenRouter-backed clarification-and-review flow
directly to assistant-ui: the server chooses one catalog clarification field,
emits exactly two allowlisted tools (`clarify_plan`,
`review_todo_suggestions`), and never performs workflow writes. PostgreSQL
workflow/suggestion rows stay authoritative; every tool argument is
server-constructed and every client tool result is validated against the
current owner-scoped snapshot before it can continue a run.

Each HTTP run ends before human input (`RUN_FINISHED`/`RUN_ERROR`); the
client's `addToolResult` starts a separate run that re-validates against the
database. There is deliberately no run journal: retrying a run ID may call
the model again.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from ag_ui.core import (
    AssistantMessage,
    BaseEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolMessage,
)
from ag_ui.encoder import EventEncoder
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session

from app.suggestion_provider import (
    MAX_OUTPUT_TOKENS,
    InvalidSuggestionOutput,
    OpenRouterConfig,
    ProviderUnavailable,
    SuggestionsNotConfigured,
    _post_openrouter_json,
    get_openrouter_config,
)
from app.suggestion_service import (
    ClarificationField,
    SuggestionStatus,
    get_current_suggestion,
    suggestion_snapshot_from_row,
)
from app.title_validation import canonicalize_title
from app.workflow_domain import (
    MAX_WORKFLOW_REVISION,
    WorkflowState,
    create_submit_tasks,
)
from app.workflow_repository import WorkflowSuggestionRequestRow
from app.workflow_service import current_step_id, get_workflow

CONTRACT_VERSION: Literal[1] = 1

CLARIFY_TOOL = "clarify_plan"
REVIEW_TOOL = "review_todo_suggestions"

MAX_AGENT_BODY_BYTES = 32 * 1024
MAX_AGENT_MESSAGES = 12
MAX_AGENT_TEXT_CODE_POINTS = 1_000
MAX_AGENT_TOOL_RESULT_BYTES = 4 * 1024

_CLARIFICATION_FIELDS: tuple[str, ...] = (
    "date",
    "location",
    "people",
    "budget",
    "constraints",
)

_CHOICE_SYSTEM_INSTRUCTION = (
    "Choose the single most useful clarification question for the user's goal. "
    "Consider only these fixed fields: date (when it must happen), "
    "location (where it happens), people (who is involved), "
    "budget (spending limits), constraints (other limits). "
    "Return only JSON matching the requested schema."
)

_SAFE_INVALID_MESSAGE = (
    "The agent request was invalid. Restart the conversation or continue manually."
)
_SAFE_PROVIDER_MESSAGE = (
    "The agent could not choose a question right now. Continue manually."
)


class AgentValidationError(ValueError):
    """A structurally or semantically invalid agent request (fail closed)."""


class ChoiceCallable(Protocol):
    async def __call__(
        self,
        goal: str,
        config: OpenRouterConfig | None,
        *,
        transport: Any = None,
    ) -> ClarificationField: ...


class AgentState(BaseModel):
    """Exact per-run client state; `threadId` carries the workflow UUID."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1]
    expected_revision: StrictInt = Field(ge=0, le=MAX_WORKFLOW_REVISION)
    step_id: StrictStr
    suggestion_request_id: UUID | None


def validate_run_input(run_input: RunAgentInput) -> AgentState:
    """Check wire identities, message bounds, and exact state shape.

    Runs before any provider call or database read. Raises
    AgentValidationError with a safe fixed message on any violation.
    """
    try:
        UUID(str(run_input.thread_id))
    except (TypeError, ValueError, AttributeError):
        raise AgentValidationError("agent thread id must be a UUID") from None
    try:
        UUID(str(run_input.run_id))
    except (TypeError, ValueError, AttributeError):
        raise AgentValidationError("agent run id must be a UUID") from None

    messages = run_input.messages or []
    if len(messages) > MAX_AGENT_MESSAGES:
        raise AgentValidationError("agent run has too many messages")
    for message in messages:
        content = getattr(message, "content", None)
        if getattr(message, "role", None) == "tool":
            if isinstance(content, str):
                try:
                    tool_result_size = len(content.encode("utf-8"))
                except UnicodeEncodeError:
                    raise AgentValidationError(
                        "agent tool result is too large"
                    ) from None
                if tool_result_size > MAX_AGENT_TOOL_RESULT_BYTES:
                    raise AgentValidationError("agent tool result is too large")
            continue
        if isinstance(content, str):
            if len(content) > MAX_AGENT_TEXT_CODE_POINTS:
                raise AgentValidationError("agent message text is too large")
        elif isinstance(content, list):
            for part in content:
                text = (
                    part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                )
                if isinstance(text, str) and len(text) > MAX_AGENT_TEXT_CODE_POINTS:
                    raise AgentValidationError("agent message text is too large")

    try:
        return AgentState.model_validate(run_input.state)
    except ValidationError as exc:
        raise AgentValidationError("agent state must match the exact contract") from exc


def _choice_payload(goal: str, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": _CHOICE_SYSTEM_INSTRUCTION},
            {"role": "user", "content": goal},
        ],
        "provider": {"require_parameters": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "clarification_choice",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": list(_CLARIFICATION_FIELDS),
                        }
                    },
                    "required": ["field"],
                    "additionalProperties": False,
                },
            },
        },
        "max_tokens": MAX_OUTPUT_TOKENS,
    }


def _extract_choice_field(response_body: bytes) -> ClarificationField:
    try:
        response_payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise InvalidSuggestionOutput("OpenRouter returned an invalid choice") from None
    if not isinstance(response_payload, dict):
        raise InvalidSuggestionOutput("OpenRouter returned an invalid choice")
    if "error" in response_payload:
        raise ProviderUnavailable("OpenRouter provider returned an error")
    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise InvalidSuggestionOutput("OpenRouter returned an invalid choice") from None
    if not isinstance(content, str):
        raise InvalidSuggestionOutput("OpenRouter returned an invalid choice")
    try:
        choice_payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        raise InvalidSuggestionOutput("OpenRouter returned an invalid choice") from None
    if (
        not isinstance(choice_payload, dict)
        or set(choice_payload) != {"field"}
        or choice_payload["field"] not in _CLARIFICATION_FIELDS
    ):
        raise InvalidSuggestionOutput("OpenRouter returned an invalid choice")
    return choice_payload["field"]


async def choose_clarification(
    goal: str,
    config: OpenRouterConfig | None,
    *,
    transport: Any = None,
) -> ClarificationField:
    """Choose one catalog clarification field for the canonical goal.

    Reuses the bounded, redacted Phase 10 OpenRouter transport; the strict
    response schema admits only the catalog field, so no model copy, schema,
    URL, or action name can flow into tool arguments. A None config resolves
    from the environment so `agent_events` never consults configuration
    unless a real model choice is about to happen.
    """
    if config is None:
        config = get_openrouter_config()
    if not config.api_key.strip() or not config.model.strip():
        raise SuggestionsNotConfigured("OpenRouter suggestions are not configured")
    try:
        canonical_goal = canonicalize_title(goal)
    except ValueError:
        raise InvalidSuggestionOutput("OpenRouter goal is invalid") from None
    response_body = await _post_openrouter_json(
        _choice_payload(canonical_goal, config.model.strip()),
        config,
        transport=transport,
    )
    return _extract_choice_field(response_body)


@dataclass(frozen=True)
class _ClarifyContinuation:
    call_id: str
    workflow_id: UUID
    expected_revision: int
    step_id: str
    field: str
    request_id: UUID


@dataclass(frozen=True)
class _ReviewContinuation:
    call_id: str
    workflow_id: UUID
    expected_revision: int
    step_id: str
    request_id: UUID
    accepted_revision: int
    titles: tuple[str, ...]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_uuid(value: Any) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _parse_clarify_arguments(arguments: Any) -> tuple[UUID, int, str, str]:
    try:
        args = json.loads(arguments)
    except (TypeError, ValueError):
        raise AgentValidationError("clarification call arguments are malformed") from None
    if (
        not isinstance(args, dict)
        or set(args) != {
            "contract_version",
            "workflow_id",
            "expected_revision",
            "step_id",
            "field",
        }
        or args["contract_version"] != CONTRACT_VERSION
    ):
        raise AgentValidationError("clarification call arguments are malformed")
    try:
        workflow_id = _parse_uuid(args["workflow_id"])
    except (TypeError, ValueError, AttributeError):
        raise AgentValidationError("clarification call arguments are malformed") from None
    if not _is_int(args["expected_revision"]) or not isinstance(args["step_id"], str):
        raise AgentValidationError("clarification call arguments are malformed")
    if args["field"] not in _CLARIFICATION_FIELDS:
        raise AgentValidationError("clarification call arguments are malformed")
    return workflow_id, args["expected_revision"], args["step_id"], args["field"]


def _parse_clarify_result(content: Any) -> UUID:
    try:
        result = json.loads(content) if isinstance(content, str) else None
    except (TypeError, ValueError):
        result = None
    if (
        not isinstance(result, dict)
        or set(result) != {"contract_version", "suggestion_request_id"}
        or result["contract_version"] != CONTRACT_VERSION
    ):
        raise AgentValidationError("clarification result is malformed")
    try:
        return _parse_uuid(result["suggestion_request_id"])
    except (TypeError, ValueError, AttributeError):
        raise AgentValidationError("clarification result is malformed") from None


def _parse_review_arguments(arguments: Any) -> tuple[UUID, int, str, UUID, tuple[str, ...]]:
    try:
        args = json.loads(arguments)
    except (TypeError, ValueError):
        raise AgentValidationError("review call arguments are malformed") from None
    if (
        not isinstance(args, dict)
        or set(args) != {
            "contract_version",
            "workflow_id",
            "expected_revision",
            "step_id",
            "suggestion_request_id",
            "titles",
        }
        or args["contract_version"] != CONTRACT_VERSION
    ):
        raise AgentValidationError("review call arguments are malformed")
    try:
        workflow_id = _parse_uuid(args["workflow_id"])
        request_id = _parse_uuid(args["suggestion_request_id"])
    except (TypeError, ValueError, AttributeError):
        raise AgentValidationError("review call arguments are malformed") from None
    if not _is_int(args["expected_revision"]) or not isinstance(args["step_id"], str):
        raise AgentValidationError("review call arguments are malformed")
    titles = args["titles"]
    if not isinstance(titles, list) or not all(isinstance(item, str) for item in titles):
        raise AgentValidationError("review call arguments are malformed")
    try:
        canonical = create_submit_tasks(titles).titles
    except (TypeError, ValueError):
        raise AgentValidationError("review call arguments are malformed") from None
    return workflow_id, args["expected_revision"], args["step_id"], request_id, canonical


def _parse_review_result(content: Any) -> tuple[UUID, int]:
    try:
        result = json.loads(content) if isinstance(content, str) else None
    except (TypeError, ValueError):
        result = None
    if (
        not isinstance(result, dict)
        or set(result) != {"contract_version", "request_id", "accepted_revision"}
        or result["contract_version"] != CONTRACT_VERSION
    ):
        raise AgentValidationError("review result is malformed")
    try:
        request_id = _parse_uuid(result["request_id"])
    except (TypeError, ValueError, AttributeError):
        raise AgentValidationError("review result is malformed") from None
    if not _is_int(result["accepted_revision"]):
        raise AgentValidationError("review result is malformed")
    return request_id, result["accepted_revision"]


def _parse_history(
    messages: Any,
) -> _ClarifyContinuation | _ReviewContinuation | None:
    """Parse only the structurally matching trailing tool call/result pair.

    Returns None for a fresh run (including one with only unresolved calls),
    which proceeds to a new model choice. Any completed tool history that
    does not match exactly fails closed: client history never authorizes a
    write and cannot carry a run across requests by itself.
    """
    items = list(messages or [])
    call_ids: list[str] = []
    for message in items:
        if isinstance(message, AssistantMessage) and message.tool_calls:
            call_ids.extend(call.id for call in message.tool_calls)
    if len(set(call_ids)) != len(call_ids):
        raise AgentValidationError("agent run has a duplicate tool id")

    last_tool_index: int | None = None
    for index, message in enumerate(items):
        if isinstance(message, ToolMessage):
            last_tool_index = index
    if last_tool_index is None:
        return None
    if last_tool_index == 0:
        raise AgentValidationError("agent tool result has no matching call")
    previous = items[last_tool_index - 1]
    result = items[last_tool_index]
    previous_calls = (
        previous.tool_calls
        if isinstance(previous, AssistantMessage) and previous.tool_calls
        else []
    )
    if len(previous_calls) != 1 or previous_calls[0].id != result.tool_call_id:
        raise AgentValidationError("agent tool result has no matching call")

    call = previous_calls[0]
    name = call.function.name if call.function is not None else None
    if name == CLARIFY_TOOL:
        workflow_id, revision, step_id, field = _parse_clarify_arguments(
            call.function.arguments
        )
        request_id = _parse_clarify_result(result.content)
        return _ClarifyContinuation(
            call_id=call.id,
            workflow_id=workflow_id,
            expected_revision=revision,
            step_id=step_id,
            field=field,
            request_id=request_id,
        )
    if name == REVIEW_TOOL:
        workflow_id, revision, step_id, request_id, titles = _parse_review_arguments(
            call.function.arguments
        )
        result_id, accepted_revision = _parse_review_result(result.content)
        if result_id != request_id:
            raise AgentValidationError("review result does not match its call")
        return _ReviewContinuation(
            call_id=call.id,
            workflow_id=workflow_id,
            expected_revision=revision,
            step_id=step_id,
            request_id=request_id,
            accepted_revision=accepted_revision,
            titles=titles,
        )
    raise AgentValidationError("agent tool is not allowlisted")


def _clarify_tool_events(
    run_id: str, workflow_id: UUID, revision: int, step_id: str, field: str
) -> list[BaseEvent]:
    tool_call_id = f"{run_id}:{CLARIFY_TOOL}:0"
    arguments = json.dumps(
        {
            "contract_version": CONTRACT_VERSION,
            "workflow_id": str(workflow_id),
            "expected_revision": revision,
            "step_id": step_id,
            "field": field,
        }
    )
    return [
        ToolCallStartEvent(toolCallId=tool_call_id, toolCallName=CLARIFY_TOOL),
        ToolCallArgsEvent(toolCallId=tool_call_id, delta=arguments),
        ToolCallEndEvent(toolCallId=tool_call_id),
    ]


def _review_tool_events(
    run_id: str,
    workflow_id: UUID,
    revision: int,
    step_id: str,
    request_id: UUID,
    titles: tuple[str, ...],
) -> list[BaseEvent]:
    tool_call_id = f"{run_id}:{REVIEW_TOOL}:0"
    arguments = json.dumps(
        {
            "contract_version": CONTRACT_VERSION,
            "workflow_id": str(workflow_id),
            "expected_revision": revision,
            "step_id": step_id,
            "suggestion_request_id": str(request_id),
            "titles": list(titles),
        }
    )
    return [
        ToolCallStartEvent(toolCallId=tool_call_id, toolCallName=REVIEW_TOOL),
        ToolCallArgsEvent(toolCallId=tool_call_id, delta=arguments),
        ToolCallEndEvent(toolCallId=tool_call_id),
    ]


def _ready_snapshot(
    session: Session, owner_id: int, workflow_id: UUID
) -> Any | None:
    try:
        snapshot = get_current_suggestion(session, owner_id, workflow_id)
    except ValueError:
        raise AgentValidationError("agent suggestion lookup failed") from None
    if snapshot is None or snapshot.status is not SuggestionStatus.READY:
        return None
    return snapshot


def _current_suggestion(
    session: Session, owner_id: int, workflow_id: UUID
) -> Any | None:
    """Latest saved suggestion snapshot regardless of workflow state.

    Returns None when no row exists or the stored row fails closed
    validation, so callers treat either case as "no current proposal".
    """
    row = session.scalar(
        select(WorkflowSuggestionRequestRow)
        .where(
            WorkflowSuggestionRequestRow.owner_id == owner_id,
            WorkflowSuggestionRequestRow.workflow_id == workflow_id,
        )
        .order_by(WorkflowSuggestionRequestRow.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    try:
        return suggestion_snapshot_from_row(row)
    except ValueError:
        return None


async def agent_events(
    run_input: RunAgentInput,
    owner_id: int,
    session: Session,
    choose: ChoiceCallable = choose_clarification,
) -> AsyncIterator[BaseEvent]:
    """Stream one authenticated agent run as AG-UI events.

    Emits `RUN_STARTED`, balanced tool-call events, then exactly one
    `RUN_FINISHED` or `RUN_ERROR`. Reads the owner-scoped workflow and
    suggestion rows, closes the read transaction before any provider call or
    further event, and never calls `advance_workflow` or creates todos.
    Cancellation (disconnect) propagates: provider work unwinds with the run.
    """
    raw_thread = getattr(run_input, "thread_id", "") or ""
    raw_run = getattr(run_input, "run_id", "") or ""
    yield RunStartedEvent(threadId=str(raw_thread), runId=str(raw_run))
    try:
        state = validate_run_input(run_input)
        run_id = str(run_input.run_id)
        workflow_id = UUID(str(run_input.thread_id))
        try:
            snapshot = get_workflow(session, owner_id, workflow_id)
        except (OperationalError, SQLAlchemyTimeoutError, ValueError):
            raise AgentValidationError("agent workflow is unavailable") from None
        if snapshot is None:
            raise AgentValidationError("agent workflow is unavailable")
        if snapshot.revision != state.expected_revision:
            raise AgentValidationError("agent workflow changed; reload and retry")
        if state.step_id != current_step_id(workflow_id, snapshot.state.value):
            raise AgentValidationError("agent workflow changed; reload and retry")

        if snapshot.state is WorkflowState.REVIEW:
            continuation = _parse_history(run_input.messages)
            if not isinstance(continuation, _ReviewContinuation):
                raise AgentValidationError("agent review needs a valid tool result")
            collect_step = current_step_id(workflow_id, WorkflowState.COLLECT_TASKS.value)
            if continuation.accepted_revision != snapshot.revision:
                raise AgentValidationError("agent review is stale")
            if continuation.workflow_id != workflow_id:
                raise AgentValidationError("agent review is stale")
            if (
                continuation.expected_revision != snapshot.revision - 1
                or continuation.step_id != collect_step
            ):
                raise AgentValidationError("agent review is stale")
            current = _current_suggestion(session, owner_id, workflow_id)
            session.rollback()
            if (
                current is None
                or current.status is not SuggestionStatus.READY
                or current.request_id != continuation.request_id
                or current.base_revision != snapshot.revision - 1
                or current.step_id != collect_step
            ):
                raise AgentValidationError("agent review is stale")
            # The call titles must replay the saved pre-submit proposal, not
            # the edited REVIEW snapshot: submit_tasks legitimately rewrites
            # the snapshot titles, and the ack only confirms what was shown.
            if tuple(continuation.titles) != tuple(current.proposed_titles):
                raise AgentValidationError("agent review is stale")
            yield RunFinishedEvent(threadId=str(raw_thread), runId=str(raw_run))
            return

        if snapshot.state is not WorkflowState.COLLECT_TASKS:
            raise AgentValidationError("agent help is only available while collecting")

        if state.suggestion_request_id is not None:
            ready = _ready_snapshot(session, owner_id, workflow_id)
            session.rollback()
            if (
                ready is None
                or ready.request_id != state.suggestion_request_id
                or ready.base_revision != snapshot.revision
                or ready.step_id != state.step_id
            ):
                raise AgentValidationError("agent suggestion is stale; start over")
            for event in _review_tool_events(
                run_id,
                workflow_id,
                snapshot.revision,
                state.step_id,
                ready.request_id,
                ready.proposed_titles,
            ):
                yield event
            yield RunFinishedEvent(threadId=str(raw_thread), runId=str(raw_run))
            return

        continuation = _parse_history(run_input.messages)
        if isinstance(continuation, _ReviewContinuation):
            raise AgentValidationError("agent review needs a valid workflow state")
        if isinstance(continuation, _ClarifyContinuation):
            if (
                continuation.workflow_id != workflow_id
                or continuation.expected_revision != snapshot.revision
                or continuation.step_id != state.step_id
            ):
                raise AgentValidationError("agent history is stale; start over")
            ready = _ready_snapshot(session, owner_id, workflow_id)
            session.rollback()
            if (
                ready is None
                or ready.request_id != continuation.request_id
                or ready.base_revision != snapshot.revision
                or ready.step_id != state.step_id
            ):
                raise AgentValidationError("agent suggestion is stale; start over")
            for event in _review_tool_events(
                run_id,
                workflow_id,
                snapshot.revision,
                state.step_id,
                ready.request_id,
                ready.proposed_titles,
            ):
                yield event
            yield RunFinishedEvent(threadId=str(raw_thread), runId=str(raw_run))
            return

        session.rollback()
        try:
            # Config stays unresolved until a real choice runs: injected test
            # doubles receive None and no provider call happens on other paths.
            field = await choose(snapshot.title, None)
        except AgentValidationError:
            raise
        except Exception as exc:
            raise AgentValidationError("agent choice failed") from exc
        if field not in _CLARIFICATION_FIELDS:
            raise AgentValidationError("agent choice failed")
        for event in _clarify_tool_events(
            run_id, workflow_id, snapshot.revision, state.step_id, field
        ):
            yield event
        yield RunFinishedEvent(threadId=str(raw_thread), runId=str(raw_run))
    except AgentValidationError:
        session.rollback()
        yield RunErrorEvent(message=_SAFE_INVALID_MESSAGE, code="invalid_request")
    except (OperationalError, SQLAlchemyTimeoutError):
        session.rollback()
        yield RunErrorEvent(message=_SAFE_INVALID_MESSAGE, code="invalid_request")
    except Exception:  # noqa: BLE001 - map unexpected failures to a safe error event
        session.rollback()
        yield RunErrorEvent(message=_SAFE_PROVIDER_MESSAGE, code="agent_failed")


async def agent_sse_body(
    run_input: RunAgentInput,
    owner_id: int,
    session: Session,
    *,
    choose: ChoiceCallable = choose_clarification,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Encode one run as SSE chunks, stopping promptly on disconnect.

    This is the exact generator the `POST /agent` route streams: closing it
    (client disconnect) unwinds the underlying run, cancelling pending
    provider work instead of leaking it.
    """
    encoder = EventEncoder()
    events = agent_events(run_input, owner_id, session, choose=choose)
    try:
        async for event in events:
            if await is_disconnected():
                break
            yield encoder.encode(event)
    finally:
        await events.aclose()
