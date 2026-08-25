"""Shared fake LLM helpers for agent and API tests. Never hits the network."""

from __future__ import annotations

from types import SimpleNamespace


class FakeLLMClient:
    def __init__(self, scripts: list) -> None:
        self._scripts = list(scripts)
        self.calls = 0
        self.last_input: list | None = None

    def create_response(self, *, model, input, tools, instructions=None):
        self.calls += 1
        self.last_input = input
        if not self._scripts:
            raise AssertionError("unexpected LLM call")
        item = self._scripts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def text_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        output=[],
        output_text=text,
        usage=SimpleNamespace(total_tokens=10),
    )


def tool_call_response(
    *,
    name: str = "list_files",
    arguments: str = '{"path": "."}',
    call_id: str = "call_1",
) -> SimpleNamespace:
    call = SimpleNamespace(
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=arguments,
        id=None,
    )
    return SimpleNamespace(
        output=[call],
        output_text="",
        usage=SimpleNamespace(total_tokens=20),
    )
