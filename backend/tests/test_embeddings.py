from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError

from app.retrieval.embeddings import EmbeddingError, OpenAIEmbeddingClient


def test_embed_texts_empty_list_returns_empty() -> None:
    client = OpenAIEmbeddingClient(api_key="sk-test")
    assert client.embed_texts([]) == []


def test_embed_texts_missing_key_raises() -> None:
    client = OpenAIEmbeddingClient(api_key="")
    with pytest.raises(EmbeddingError, match="not configured"):
        client.embed_texts(["hi"])


def test_embed_texts_batches_and_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAIEmbeddingClient(
        api_key="sk-test",
        model="text-embedding-3-small",
        batch_size=2,
    )
    calls: list[list[str]] = []

    def fake_create(**kwargs):
        calls.append(list(kwargs["input"]))
        assert kwargs["model"] == "text-embedding-3-small"
        # Return items out of order to verify index sorting.
        items = [
            SimpleNamespace(index=i, embedding=[float(i), 1.0])
            for i in range(len(kwargs["input"]) - 1, -1, -1)
        ]
        return SimpleNamespace(data=items)

    mock_create = MagicMock(side_effect=fake_create)
    monkeypatch.setattr(client._client.embeddings, "create", mock_create)

    vectors = client.embed_texts(["a", "b", "c"])

    assert calls == [["a", "b"], ["c"]]
    assert vectors == [[0.0, 1.0], [1.0, 1.0], [0.0, 1.0]]
    assert mock_create.call_count == 2


def test_embed_texts_wraps_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAIEmbeddingClient(api_key="sk-test")
    mock_create = MagicMock(
        side_effect=AuthenticationError(
            message="bad key",
            response=MagicMock(),
            body=None,
        )
    )
    monkeypatch.setattr(client._client.embeddings, "create", mock_create)

    with pytest.raises(EmbeddingError, match="authentication"):
        client.embed_texts(["hi"])


def test_embed_texts_retries_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OpenAIEmbeddingClient(api_key="sk-test")
    monkeypatch.setattr("app.retrieval.embeddings.time.sleep", lambda _delay: None)

    success = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[0.1, 0.2])]
    )
    mock_create = MagicMock(
        side_effect=[
            RateLimitError(
                message="slow down",
                response=MagicMock(),
                body=None,
            ),
            success,
        ]
    )
    monkeypatch.setattr(client._client.embeddings, "create", mock_create)

    vectors = client.embed_texts(["hi"])

    assert vectors == [[0.1, 0.2]]
    assert mock_create.call_count == 2


def test_embed_texts_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OpenAIEmbeddingClient(api_key="sk-test")
    monkeypatch.setattr("app.retrieval.embeddings.time.sleep", lambda _delay: None)

    mock_create = MagicMock(
        side_effect=APIConnectionError(request=MagicMock())
    )
    monkeypatch.setattr(client._client.embeddings, "create", mock_create)

    with pytest.raises(EmbeddingError, match="embedding request failed"):
        client.embed_texts(["hi"])

    assert mock_create.call_count == 3


def test_embed_texts_wraps_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = OpenAIEmbeddingClient(api_key="sk-test")
    mock_create = MagicMock(
        side_effect=APIError(
            message="boom",
            request=MagicMock(),
            body=None,
        )
    )
    monkeypatch.setattr(client._client.embeddings, "create", mock_create)

    with pytest.raises(EmbeddingError, match="embedding request failed"):
        client.embed_texts(["hi"])

    assert mock_create.call_count == 1
