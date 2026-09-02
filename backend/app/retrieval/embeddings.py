from __future__ import annotations

import logging
import time
from typing import Protocol

from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.5, 1.0, 2.0)


class EmbeddingError(Exception):
    """Embedding API failure. Message is safe to surface upstream."""


class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        batch_size: int = 64,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._api_key = api_key
        self._model = model
        self._batch_size = batch_size
        self._client = OpenAI(api_key=api_key) if api_key else None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._api_key or self._client is None:
            raise EmbeddingError("OpenAI API key is not configured.")

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        if self._client is None:
            raise EmbeddingError("OpenAI API key is not configured.")

        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = self._client.embeddings.create(
                    model=self._model,
                    input=batch,
                )
                # OpenAI may return items out of order — sort by index
                ordered = sorted(response.data, key=lambda item: item.index)
                return [list(item.embedding) for item in ordered]
            except AuthenticationError as exc:
                logger.exception("OpenAI embedding authentication failed")
                raise EmbeddingError("OpenAI authentication failed.") from exc
            except (RateLimitError, APIConnectionError) as exc:
                last_error = exc
                if attempt + 1 == _MAX_ATTEMPTS:
                    break
                delay = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "Transient embedding error; retrying in %.1fs (%d/%d)",
                    delay,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                )
                time.sleep(delay)
            except APIError as exc:
                logger.exception("OpenAI embedding API error")
                raise EmbeddingError("OpenAI embedding request failed.") from exc

        logger.exception("OpenAI embedding failed after retries")
        raise EmbeddingError("OpenAI embedding request failed.") from last_error
