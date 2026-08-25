from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import APIError, AuthenticationError

from app.llm.client import LLMError, OpenAILLMClient


def test_create_response_returns_sdk_response(monkeypatch: pytest.MonkeyPatch):
    fake_response = SimpleNamespace(id="resp_1", output=[], output_text="hello")
    mock_create = MagicMock(return_value=fake_response)

    client = OpenAILLMClient(api_key="sk-test", max_output_tokens=1024)
    monkeypatch.setattr(client._client.responses, "create", mock_create)

    result = client.create_response(
        model="gpt-4.1-mini",
        input="Explain Session",
        tools=[],
        instructions="You are a coding assistant.",
    )

    assert result is fake_response
    kwargs = mock_create.call_args.kwargs
    assert kwargs["model"] == "gpt-4.1-mini"
    assert kwargs["input"] == "Explain Session"
    assert kwargs["tools"] == []
    assert kwargs["instructions"] == "You are a coding assistant."
    assert kwargs["max_output_tokens"] == 1024


def test_create_response_wraps_auth_error(monkeypatch: pytest.MonkeyPatch):
    mock_create = MagicMock(
        side_effect=AuthenticationError(
            message="bad key",
            response=MagicMock(),
            body=None,
        )
    )
    client = OpenAILLMClient(api_key="sk-test")
    monkeypatch.setattr(client._client.responses, "create", mock_create)

    with pytest.raises(LLMError, match="authentication"):
        client.create_response(model="gpt-4.1-mini", input="hi", tools=[])


def test_create_response_wraps_api_error(monkeypatch: pytest.MonkeyPatch):
    mock_create = MagicMock(
        side_effect=APIError(
            message="boom",
            request=MagicMock(),
            body=None,
        )
    )
    client = OpenAILLMClient(api_key="sk-test")
    monkeypatch.setattr(client._client.responses, "create", mock_create)

    with pytest.raises(LLMError, match="request failed"):
        client.create_response(model="gpt-4.1-mini", input="hi", tools=[])


def test_create_response_rejects_empty_api_key():
    client = OpenAILLMClient(api_key="")

    with pytest.raises(LLMError, match="not configured"):
        client.create_response(model="gpt-4.1-mini", input="hi", tools=[])
