from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from app.observability import log_event
from app.suggestion_service import Clarification, normalize_clarification
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


def _request_payload(
    goal: str, model: str, clarification: Clarification | None = None
) -> dict[str, Any]:
    if clarification is None:
        user_content = goal
    else:
        user_content = (
            f"{goal}\nClarification [{clarification.field}]: {clarification.value}"
        )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": user_content},
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


def _emit_provider_call(operation: str, outcome: str, started: float) -> None:
    # One log per transport attempt with only safe scalars: the bounded
    # operation, outcome, latency, and a random attempt ID. Goals, prompts,
    # response bodies, and exception text never travel. Emitted regardless
    # of trace sampling so transport failures stay visible in logs.
    log_event(
        "provider_call",
        outcome=outcome,
        operation=operation,
        duration_ms=int((time.monotonic() - started) * 1000),
        attempt_id=uuid4().hex,
    )


def emit_output_rejected(operation: str) -> None:
    # Model output failed validation: safe operation tag only, never the
    # rejected content.
    log_event("ai_output_rejected", outcome="invalid_output", operation=operation)


async def _post_openrouter_json(
    payload: dict[str, Any],
    config: OpenRouterConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    operation: str = "suggestions",
) -> bytes:
    """Send one bounded, redacted OpenRouter JSON request.

    Shared by todo suggestions and the Task 3 agent choice so both use the
    same output cap, deadline, timeouts, and error mapping. Exactly one
    attempt runs: no retries. Cancellation is never mapped: it propagates
    so disconnects unwind instead of persisting as provider results.
    """
    started = time.monotonic()
    api_key = config.api_key.strip()
    if not api_key or not config.model.strip():
        raise SuggestionsNotConfigured("OpenRouter suggestions are not configured")

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
                    json=payload,
                ) as response:
                    if not response.is_success:
                        _emit_provider_call(operation, "transport_error", started)
                        raise ProviderUnavailable(
                            "OpenRouter provider was unavailable"
                        )
                    response_body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(response_body) + len(chunk) > MAX_RESPONSE_BYTES:
                            # HTTP 200 transport completed; the application
                            # rejects the over-cap body as invalid content.
                            # Never a transport error, never a retry.
                            _emit_provider_call(operation, "ok", started)
                            emit_output_rejected(operation)
                            raise InvalidSuggestionOutput(
                                "OpenRouter response exceeded the size limit"
                            )
                        response_body.extend(chunk)
    except asyncio.CancelledError:
        # Disconnects unwind: never mapped to a provider error, never
        # retried. One bounded interrupted-transport outcome is still
        # emitted so Task 3 call counts stay truthful; no exception text.
        _emit_provider_call(operation, "cancelled", started)
        raise
    except (TimeoutError, httpx.TimeoutException):
        _emit_provider_call(operation, "timeout", started)
        raise SuggestionTimeout("OpenRouter request timed out") from None
    except (ProviderUnavailable, InvalidSuggestionOutput):
        raise
    except httpx.HTTPError:
        _emit_provider_call(operation, "transport_error", started)
        raise ProviderUnavailable("OpenRouter provider was unavailable") from None

    _emit_provider_call(operation, "ok", started)
    return bytes(response_body)


async def request_todo_suggestions(
    goal: str,
    config: OpenRouterConfig,
    *,
    clarification: Clarification | None = None,
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
    try:
        canonical_clarification = (
            normalize_clarification(clarification) if clarification is not None else None
        )
    except (TypeError, ValueError):
        raise InvalidSuggestionOutput("OpenRouter clarification is invalid") from None

    response_body = await _post_openrouter_json(
        _request_payload(canonical_goal, model, canonical_clarification),
        config,
        transport=transport,
        operation="suggestions",
    )
    try:
        return _extract_titles(response_body)
    except InvalidSuggestionOutput:
        emit_output_rejected("suggestions")
        raise
