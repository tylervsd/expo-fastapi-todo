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
