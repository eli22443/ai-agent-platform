from __future__ import annotations

import logging
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from openai.types.responses import Response

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM API failure. Message is safe to surface upstream."""


class LLMClient(Protocol):
    def create_response(
        self,
        *,
        model: str,
        input: list[dict[str, Any]] | str,
        tools: list[dict[str, Any]],
        instructions: str | None = None,
    ) -> Response: ...


class OpenAILLMClient:
    """Thin wrapper around the OpenAI Responses API. No agent logic."""

    def __init__(
        self,
        *,
        api_key: str,
        max_output_tokens: int | None = None,
    ) -> None:
        self._api_key = api_key
        self._max_output_tokens = max_output_tokens
        self._client = OpenAI(api_key=api_key) if api_key else None

    def create_response(
        self,
        *,
        model: str,
        input: list[dict[str, Any]] | str,
        tools: list[dict[str, Any]],
        instructions: str | None = None,
    ) -> Response:
        if not self._api_key or self._client is None:
            raise LLMError("OpenAI API key is not configured.")

        kwargs: dict[str, Any] = {
            "model": model,
            "input": input,
            "tools": tools,
        }
        if instructions is not None:
            kwargs["instructions"] = instructions
        if self._max_output_tokens is not None:
            kwargs["max_output_tokens"] = self._max_output_tokens

        try:
            return self._client.responses.create(**kwargs)
        except AuthenticationError as exc:
            logger.exception("OpenAI authentication failed")
            raise LLMError("OpenAI authentication failed.") from exc
        except RateLimitError as exc:
            logger.exception("OpenAI rate limit exceeded")
            raise LLMError("OpenAI rate limit exceeded.") from exc
        except APIConnectionError as exc:
            logger.exception("OpenAI connection failed")
            raise LLMError("Failed to connect to OpenAI.") from exc
        except APIError as exc:
            logger.exception("OpenAI API error")
            raise LLMError("OpenAI request failed.") from exc
