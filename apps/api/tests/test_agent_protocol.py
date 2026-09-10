"""Task 1 compatibility: prove the pinned Python AG-UI protocol package.

Uses only the installed public surface: RunAgentInput, event classes,
EventEncoder, and the documented streaming media type consumed by Task 3.
No network, database, or model calls.
"""

from __future__ import annotations

import json
import uuid

from ag_ui.core import (
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    UserMessage,
)
from ag_ui.encoder import AGUI_MEDIA_TYPE, EventEncoder


def test_run_agent_input_round_trips_thread_and_run_ids() -> None:
    thread_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    run_input = RunAgentInput(
        threadId=thread_id,
        runId=run_id,
        messages=[UserMessage(id="u1", role="user", content="Plan birthday party")],
        tools=[],
        context=[],
        forwardedProps={},
    )

    assert run_input.thread_id == thread_id
    assert run_input.run_id == run_id
    wire = json.loads(run_input.model_dump_json(by_alias=True))
    assert wire["threadId"] == thread_id
    assert wire["runId"] == run_id
    assert wire["messages"][0]["content"] == "Plan birthday party"


def test_agent_event_stream_encodes_ordered_sse_with_streaming_media_type() -> None:
    thread_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    tool_call_id = f"{run_id}:clarify_plan:0"
    encoder = EventEncoder()

    assert encoder.get_content_type() == "text/event-stream"

    events = [
        RunStartedEvent(threadId=thread_id, runId=run_id),
        ToolCallStartEvent(toolCallId=tool_call_id, toolCallName="clarify_plan"),
        ToolCallArgsEvent(toolCallId=tool_call_id, delta='{"field":"date"}'),
        ToolCallEndEvent(toolCallId=tool_call_id),
        RunFinishedEvent(threadId=thread_id, runId=run_id),
    ]
    payload = "".join(encoder.encode(event) for event in events)

    lines = [line for line in payload.splitlines() if line.startswith("data: ")]
    assert len(lines) == 5
    decoded = [json.loads(line[len("data: ") :]) for line in lines]
    assert [item["type"] for item in decoded] == [
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "RUN_FINISHED",
    ]
    assert decoded[0]["threadId"] == thread_id
    assert decoded[0]["runId"] == run_id
    assert decoded[1]["toolCallId"] == tool_call_id
    assert decoded[1]["toolCallName"] == "clarify_plan"
    assert json.loads(decoded[2]["delta"]) == {"field": "date"}
    assert decoded[3]["toolCallId"] == tool_call_id
    assert decoded[4]["threadId"] == thread_id
    assert decoded[4]["runId"] == run_id


def test_ag_ui_media_type_constant_is_documented_proto_value() -> None:
    assert AGUI_MEDIA_TYPE == "application/vnd.ag-ui.event+proto"
