from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from app.title_validation import canonicalize_title
from app.workflow_domain import InvalidWorkflowInput, create_submit_tasks

OPENROUTER_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_RESPONSE_BYTES = 16 * 1024
REQUEST_DEADLINE_SECONDS = 30
HTTP_CONNECT_TIMEOUT_SECONDS = 5
HTTP_READ_TIMEOUT_SECONDS = 25
HTTP_WRITE_TIMEOUT_SECONDS = 5
HTTP_POOL_TIMEOUT_SECONDS = 5
MAX_OUTPUT_TOKENS = 400

SYSTEM_INSTRUCTION = (
    "Suggest 2 to 10 concise, actionable todo titles for the user's goal. "
    "Return only JSON matching the requested schema."
)


class SuggestionsNotConfigured(RuntimeError):
    """OpenRouter credentials or model configuration is missing."""


class SuggestionTimeout(RuntimeError):
    """The OpenRouter request exceeded its deadline."""


class ProviderUnavailable(RuntimeError):
    """OpenRouter could not provide a response."""


class InvalidSuggestionOutput(RuntimeError):
    """OpenRouter returned output that does not satisfy the contract."""


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str


class _SuggestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titles: list[StrictStr] = Field(min_length=2, max_length=10)


def get_openrouter_config() -> OpenRouterConfig:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    model = os.environ.get("OPENROUTER_MODEL", "").strip()
    if not api_key or not model:
        raise SuggestionsNotConfigured("OpenRouter suggestions are not configured")
    return OpenRouterConfig(api_key=api_key, model=model)


def _request_payload(goal: str, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": goal},
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
        "max_tokens": MAX_OUTPUT_TOKENS,
    }


def _invalid_output() -> InvalidSuggestionOutput:
    return InvalidSuggestionOutput("OpenRouter returned invalid suggestions")


def _extract_titles(response_body: bytes) -> tuple[str, ...]:
    try:
        response_payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise _invalid_output() from None

    if not isinstance(response_payload, dict):
        raise _invalid_output()
    if "error" in response_payload:
        raise ProviderUnavailable("OpenRouter provider returned an error")

    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise _invalid_output() from None
    if not isinstance(content, str):
        raise _invalid_output()

    try:
        output_payload = json.loads(content)
        output = _SuggestionOutput.model_validate(output_payload)
        return create_submit_tasks(output.titles).titles
    except (json.JSONDecodeError, TypeError, ValidationError, InvalidWorkflowInput):
        raise _invalid_output() from None


async def request_todo_suggestions(
    goal: str,
    config: OpenRouterConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[str, ...]:
    api_key = config.api_key.strip()
    model = config.model.strip()
    if not api_key or not model:
        raise SuggestionsNotConfigured("OpenRouter suggestions are not configured")
    try:
        canonical_goal = canonicalize_title(goal)
    except ValueError:
        raise InvalidSuggestionOutput("OpenRouter goal is invalid") from None

    timeout = httpx.Timeout(
        HTTP_READ_TIMEOUT_SECONDS,
        connect=HTTP_CONNECT_TIMEOUT_SECONDS,
        write=HTTP_WRITE_TIMEOUT_SECONDS,
        pool=HTTP_POOL_TIMEOUT_SECONDS,
    )
    try:
        async with asyncio.timeout(REQUEST_DEADLINE_SECONDS):
            async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
                async with client.stream(
                    "POST",
                    OPENROUTER_COMPLETIONS_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=_request_payload(canonical_goal, model),
                ) as response:
                    if not response.is_success:
                        raise ProviderUnavailable(
                            "OpenRouter provider was unavailable"
                        )
                    response_body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(response_body) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise InvalidSuggestionOutput(
                                "OpenRouter response exceeded the size limit"
                            )
                        response_body.extend(chunk)
    except (TimeoutError, httpx.TimeoutException):
        raise SuggestionTimeout("OpenRouter request timed out") from None
    except (ProviderUnavailable, InvalidSuggestionOutput):
        raise
    except httpx.HTTPError:
        raise ProviderUnavailable("OpenRouter provider was unavailable") from None

    return _extract_titles(bytes(response_body))
