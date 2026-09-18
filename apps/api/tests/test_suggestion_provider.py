from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from app.suggestion_provider import (
    SYSTEM_INSTRUCTION,
    InvalidSuggestionOutput,
    OpenRouterConfig,
    ProviderUnavailable,
    SuggestionsNotConfigured,
    SuggestionTimeout,
    get_openrouter_config,
    request_todo_suggestions,
)

GOAL = "Plan a birthday party"
CONFIG = OpenRouterConfig(api_key="test-key", model="test/model")


def provider_response(titles: list[str]) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"titles": titles}),
                }
            }
        ]
    }


class SingleChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunk: bytes) -> None:
        self.chunk = chunk

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.chunk

    async def aclose(self) -> None:
        pass


def transport_for(
    response: httpx.Response | Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    if callable(response):
        return httpx.MockTransport(response)

    return httpx.MockTransport(lambda request: response)


@pytest.mark.anyio
async def test_request_sends_exact_structured_output_payload_and_auth() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=provider_response(["Choose a date", "Invite guests"]))

    result = await request_todo_suggestions(
        GOAL, CONFIG, transport=httpx.MockTransport(handler)
    )

    assert result == ("Choose a date", "Invite guests")
    assert captured["method"] == "POST"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    headers = captured["headers"]
    assert isinstance(headers, httpx.Headers)
    assert headers["authorization"] == "Bearer test-key"
    assert headers["content-type"] == "application/json"
    request_json = captured["json"]
    assert request_json == {
        "model": "test/model",
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_INSTRUCTION,
            },
            {"role": "user", "content": GOAL},
        ],
        "provider": {"require_parameters": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "todo_suggestions",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "titles": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 120,
                            },
                            "minItems": 2,
                            "maxItems": 10,
                        }
                    },
                    "required": ["titles"],
                    "additionalProperties": False,
                },
            },
        },
        "max_tokens": 400,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("count", [2, 10])
async def test_accepts_supported_title_count_boundaries(count: int) -> None:
    titles = [f"Task {index}" for index in range(count)]
    result = await request_todo_suggestions(
        GOAL, CONFIG, transport=transport_for(httpx.Response(200, json=provider_response(titles)))
    )
    assert result == tuple(titles)


@pytest.mark.anyio
@pytest.mark.parametrize("count", [1, 11])
async def test_rejects_unsupported_title_count(count: int) -> None:
    titles = [f"Task {index}" for index in range(count)]
    with pytest.raises(InvalidSuggestionOutput):
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            transport=transport_for(
                httpx.Response(200, json=provider_response(titles))
            ),
        )


@pytest.mark.anyio
@pytest.mark.parametrize("title", ["", "  \t", "x" * 121, "contains\x00nul"])
async def test_rejects_noncanonical_titles(title: str) -> None:
    with pytest.raises(InvalidSuggestionOutput):
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            transport=transport_for(
                httpx.Response(200, json=provider_response(["Valid", title]))
            ),
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response_body",
    [
        {"choices": []},
        {"choices": [{"message": {"content": "not-json"}}]},
        {"choices": [{"message": {"content": json.dumps({"titles": ["one"]})}}]},
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"titles": ["one", 2]}),
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"titles": ["one", "two"], "extra": 1}),
                    }
                }
            ]
        },
    ],
)
async def test_rejects_malformed_or_non_strict_provider_output(
    response_body: dict[str, object],
) -> None:
    with pytest.raises(InvalidSuggestionOutput) as error:
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            transport=transport_for(httpx.Response(200, json=response_body)),
        )
    assert "provider" not in str(error.value).lower()


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [400, 429, 500])
async def test_non_success_response_is_redacted_provider_error(status_code: int) -> None:
    secret_body = "provider body with secret title"
    with pytest.raises(ProviderUnavailable) as error:
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            transport=transport_for(
                httpx.Response(status_code, content=secret_body)
            ),
        )
    assert secret_body not in str(error.value)
    assert GOAL not in str(error.value)
    assert "test-key" not in str(error.value)


@pytest.mark.anyio
async def test_http_200_top_level_error_is_provider_error() -> None:
    with pytest.raises(ProviderUnavailable) as error:
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            transport=transport_for(
                httpx.Response(
                    200,
                    json={"error": {"code": 429, "message": "secret provider detail"}},
                )
            ),
        )
    assert "secret provider detail" not in str(error.value)


@pytest.mark.anyio
async def test_oversized_single_chunk_is_rejected_before_buffering() -> None:
    oversized_chunk = b"{" + b"x" * (16 * 1024) + b"}"
    response = httpx.Response(200, stream=SingleChunkStream(oversized_chunk))
    with pytest.raises(InvalidSuggestionOutput, match="size"):
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            transport=transport_for(response),
        )


@pytest.mark.anyio
async def test_timeout_is_mapped_to_safe_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret timeout details", request=request)

    with pytest.raises(SuggestionTimeout) as error:
        await request_todo_suggestions(
            GOAL, CONFIG, transport=httpx.MockTransport(handler)
        )
    assert "secret timeout" not in str(error.value)


def test_missing_environment_configuration_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    with pytest.raises(SuggestionsNotConfigured):
        get_openrouter_config()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    with pytest.raises(SuggestionsNotConfigured):
        get_openrouter_config()


@pytest.mark.anyio
async def test_blank_supplied_configuration_is_not_used() -> None:
    with pytest.raises(SuggestionsNotConfigured):
        await request_todo_suggestions(
            GOAL,
            OpenRouterConfig(api_key="", model="test/model"),
            transport=transport_for(httpx.Response(200, json=provider_response([]))),
        )


@pytest.mark.anyio
async def test_transport_failure_is_redacted_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("key and prompt details", request=request)

    with pytest.raises(ProviderUnavailable) as error:
        await request_todo_suggestions(
            GOAL, CONFIG, transport=httpx.MockTransport(handler)
        )
    assert "key and prompt details" not in str(error.value)


@pytest.mark.anyio
async def test_outer_deadline_maps_async_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class ImmediateTimeout:
        async def __aenter__(self) -> None:
            raise TimeoutError

        async def __aexit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(asyncio, "timeout", lambda seconds: ImmediateTimeout())
    with pytest.raises(SuggestionTimeout):
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            transport=transport_for(httpx.Response(200, json=provider_response(["one", "two"]))),
        )


@pytest.mark.anyio
async def test_clarification_appends_single_labeled_line_to_prompt() -> None:
    from app.suggestion_service import Clarification

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=provider_response(["Choose a date", "Invite guests"]))

    result = await request_todo_suggestions(
        GOAL,
        CONFIG,
        clarification=Clarification(field="date", value="next Saturday"),
        transport=httpx.MockTransport(handler),
    )

    assert result == ("Choose a date", "Invite guests")
    request_json = captured["json"]
    assert isinstance(request_json, dict)
    messages = request_json["messages"]
    assert messages[0] == {"role": "system", "content": SYSTEM_INSTRUCTION}
    assert messages[1] == {
        "role": "user",
        "content": "Plan a birthday party\nClarification [date]: next Saturday",
    }


@pytest.mark.anyio
async def test_absent_clarification_preserves_exact_legacy_user_content() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json=provider_response(["Choose a date", "Invite guests"]))

    await request_todo_suggestions(GOAL, CONFIG, transport=httpx.MockTransport(handler))

    request_json = captured["json"]
    assert isinstance(request_json, dict)
    assert request_json["messages"][1] == {"role": "user", "content": GOAL}


@pytest.mark.anyio
@pytest.mark.parametrize("value", ["x", "y" * 200, "🎉" * 200, "  next Saturday  "])
async def test_clarification_value_bounds_accept(value: str) -> None:
    from app.suggestion_service import Clarification

    result = await request_todo_suggestions(
        GOAL,
        CONFIG,
        clarification=Clarification(field="people", value=value),
        transport=transport_for(
            httpx.Response(200, json=provider_response(["Choose a date", "Invite guests"]))
        ),
    )
    assert result == ("Choose a date", "Invite guests")


@pytest.mark.anyio
@pytest.mark.parametrize("value", ["", "   ", "x" * 201, "has\x00nul"])
async def test_clarification_value_bounds_reject(value: str) -> None:
    from app.suggestion_service import Clarification

    with pytest.raises(InvalidSuggestionOutput):
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            clarification=Clarification(field="date", value=value),
            transport=transport_for(
                httpx.Response(200, json=provider_response(["Choose a date", "Invite guests"]))
            ),
        )


@pytest.mark.anyio
async def test_clarification_answer_never_leaks_into_errors_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from app.suggestion_service import Clarification

    caplog.set_level(logging.DEBUG, logger="app.suggestion_provider")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("transport boom", request=request)

    with pytest.raises(ProviderUnavailable) as error:
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            clarification=Clarification(field="budget", value="under $50"),
            transport=httpx.MockTransport(handler),
        )
    assert "under $50" not in str(error.value)
    assert "under $50" not in caplog.text


@pytest.mark.anyio
async def test_blank_configuration_checked_before_goal_validation() -> None:
    with pytest.raises(SuggestionsNotConfigured):
        await request_todo_suggestions(
            "",
            OpenRouterConfig(api_key="", model="test/model"),
            transport=transport_for(httpx.Response(200, json=provider_response(["a", "b"]))),
        )


# ---------------------------------------------------------------------------
# Phase 21 Task 3 (TDD red): shared provider transport semantics.
#
# `_post_openrouter_json` serves suggestions and clarification. Both paths
# must map success, timeout, HTTP failure, invalid output, and cancellation
# identically, preserve the deadline/size/token bounds, emit one
# `provider_call` event per transport attempt plus `ai_output_rejected`
# when content is rejected, and never retry or leak content.
# ---------------------------------------------------------------------------


def read_json_records(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    import json as _json

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines, "expected serialized log output"
    return [_json.loads(line) for line in lines]


def choice_response(field: str) -> dict[str, object]:
    import json as _json

    return {
        "choices": [{"message": {"content": _json.dumps({"field": field})}}]
    }


@pytest.mark.anyio
async def test_suggestions_cancellation_propagates_without_mapping() -> None:
    import asyncio as _asyncio

    def handler(request: httpx.Request) -> httpx.Response:
        raise _asyncio.CancelledError()

    with pytest.raises(_asyncio.CancelledError):
        await request_todo_suggestions(
            GOAL, CONFIG, transport=httpx.MockTransport(handler)
        )


@pytest.mark.anyio
async def test_clarification_cancellation_propagates_without_mapping() -> None:
    import asyncio as _asyncio

    from app.agent import choose_clarification

    def handler(request: httpx.Request) -> httpx.Response:
        raise _asyncio.CancelledError()

    with pytest.raises(_asyncio.CancelledError):
        await choose_clarification(
            GOAL, CONFIG, transport=httpx.MockTransport(handler)
        )


@pytest.mark.anyio
async def test_clarification_timeout_maps_to_safe_timeout() -> None:
    from app.agent import choose_clarification

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret timeout details", request=request)

    with pytest.raises(SuggestionTimeout) as error:
        await choose_clarification(
            GOAL, CONFIG, transport=httpx.MockTransport(handler)
        )
    assert "secret timeout" not in str(error.value)


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [400, 429, 500])
async def test_clarification_http_failure_maps_to_provider_unavailable(
    status_code: int,
) -> None:
    from app.agent import choose_clarification

    secret_body = "provider body with secret title"
    with pytest.raises(ProviderUnavailable) as error:
        await choose_clarification(
            GOAL,
            CONFIG,
            transport=transport_for(
                httpx.Response(status_code, content=secret_body)
            ),
        )
    assert secret_body not in str(error.value)
    assert GOAL not in str(error.value)
    assert "test-key" not in str(error.value)


@pytest.mark.anyio
async def test_clarification_invalid_output_maps_without_leak() -> None:
    from app.agent import choose_clarification

    with pytest.raises(InvalidSuggestionOutput) as error:
        await choose_clarification(
            GOAL,
            CONFIG,
            transport=transport_for(
                httpx.Response(200, json=choice_response("music"))
            ),
        )
    assert "music" not in str(error.value)


@pytest.mark.anyio
async def test_provider_call_event_emitted_for_suggestions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.observability import configure_logging as _configure

    _configure("test-service")
    capsys.readouterr()
    result = await request_todo_suggestions(
        GOAL,
        CONFIG,
        transport=transport_for(
            httpx.Response(200, json=provider_response(["Choose a date", "Invite guests"]))
        ),
    )
    assert result == ("Choose a date", "Invite guests")
    records = read_json_records(capsys)
    calls = [record for record in records if record.get("event") == "provider_call"]
    assert len(calls) == 1, "one provider_call per transport attempt"
    call = calls[0]
    assert call["outcome"] == "ok"
    assert call["operation"] == "suggestions"
    assert isinstance(call["duration_ms"], int)
    assert call["attempt_id"]
    text = __import__("json").dumps(records)
    assert GOAL not in text
    assert "test-key" not in text


@pytest.mark.anyio
async def test_provider_call_event_emitted_for_clarification(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.agent import choose_clarification
    from app.observability import configure_logging as _configure

    _configure("test-service")
    capsys.readouterr()
    field = await choose_clarification(
        GOAL,
        CONFIG,
        transport=transport_for(httpx.Response(200, json=choice_response("date"))),
    )
    assert field == "date"
    records = read_json_records(capsys)
    calls = [record for record in records if record.get("event") == "provider_call"]
    assert len(calls) == 1, "one provider_call per transport attempt"
    assert calls[0]["outcome"] == "ok"
    assert calls[0]["operation"] == "clarification"


@pytest.mark.anyio
async def test_ai_output_rejected_event_on_invalid_suggestions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.observability import configure_logging as _configure

    _configure("test-service")
    capsys.readouterr()
    with pytest.raises(InvalidSuggestionOutput):
        await request_todo_suggestions(
            GOAL,
            CONFIG,
            transport=transport_for(
                httpx.Response(200, json=provider_response(["only-one"]))
            ),
        )
    records = read_json_records(capsys)
    rejected = [
        record for record in records if record.get("event") == "ai_output_rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0]["operation"] == "suggestions"
    assert "only-one" not in __import__("json").dumps(records)


# Phase 21 Task 3 fix round 1 (TDD red): cancellation must still emit one
# bounded `provider_call` (interrupted transport, no exception text, no
# retry), and oversized HTTP 200 bodies must read as transport completion
# plus content rejection, never a transport error.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cancellation_emits_bounded_provider_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import asyncio as _asyncio

    from app.observability import configure_logging as _configure

    _configure("test-service")
    capsys.readouterr()

    def handler(request: httpx.Request) -> httpx.Response:
        raise _asyncio.CancelledError()

    with pytest.raises(_asyncio.CancelledError):
        await request_todo_suggestions(
            GOAL, CONFIG, transport=httpx.MockTransport(handler)
        )
    records = read_json_records(capsys)
    calls = [record for record in records if record.get("event") == "provider_call"]
    assert len(calls) == 1, "cancelled transport still reports one attempt"
    assert calls[0]["outcome"] in ("cancelled", "interrupted")
    assert calls[0]["operation"] == "suggestions"
    assert isinstance(calls[0]["duration_ms"], int)
    assert calls[0]["attempt_id"]


@pytest.mark.anyio
async def test_oversized_success_is_completed_plus_output_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.observability import configure_logging as _configure

    _configure("test-service")
    capsys.readouterr()
    oversized_chunk = b"{" + b"x" * (16 * 1024) + b"}"
    response = httpx.Response(200, stream=SingleChunkStream(oversized_chunk))
    with pytest.raises(InvalidSuggestionOutput):
        await request_todo_suggestions(
            GOAL, CONFIG, transport=transport_for(response)
        )
    records = read_json_records(capsys)
    calls = [record for record in records if record.get("event") == "provider_call"]
    assert len(calls) == 1
    assert calls[0]["outcome"] != "transport_error", (
        "oversized HTTP 200 is transport completion, not a transport error"
    )
    rejected = [
        record for record in records if record.get("event") == "ai_output_rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0]["operation"] == "suggestions"
