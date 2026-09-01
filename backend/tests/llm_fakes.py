"""Shared fake LLM helpers for agent and API tests. Never hits the network."""

from __future__ import annotations

from types import SimpleNamespace


class FakeLLMClient:
    def __init__(self, scripts: list) -> None:
        self._scripts = list(scripts)
        self.calls = 0
        self.last_input: list | None = None
        self.inputs: list[list] = []

    def create_response(self, *, model, input, tools, instructions=None):
        self.calls += 1
        self.last_input = input
        self.inputs.append(list(input))
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
        usage=SimpleNamespace(total_tokens=10, input_tokens=6, output_tokens=4),
    )


def tool_call_response(
    *,
    name: str = "list_files",
    arguments: str = '{"path": "."}',
    call_id: str = "call_1",
    reasoning_id: str | None = None,
) -> SimpleNamespace:
    call = SimpleNamespace(
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=arguments,
        id=None,
    )
    output: list = []
    if reasoning_id is not None:
        output.append(
            SimpleNamespace(
                type="reasoning",
                id=reasoning_id,
                summary=[],
                encrypted_content=None,
                status=None,
            )
        )
    output.append(call)
    return SimpleNamespace(
        output=output,
        output_text="",
        usage=SimpleNamespace(total_tokens=20, input_tokens=12, output_tokens=8),
    )
