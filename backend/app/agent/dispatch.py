from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from app.agent.types import ToolCallSummary
from app.tools.base import ToolContext, ToolResult
from app.tools.registry import ToolRegistry


@dataclass
class DispatchResult:
    output_items: list[dict[str, Any]]
    summaries: list[ToolCallSummary]


def extract_function_calls(output: list[Any]) -> list[Any]:
    """Pull function_call items from a Responses API output list."""
    return [item for item in output if getattr(item, "type", None) == "function_call"]


def dispatch_tool_calls(
    tool_calls: list[Any],
    *,
    registry: ToolRegistry,
    context: ToolContext,
) -> DispatchResult:
    """Execute model function calls and build function_call_output items.

    Tool failures (ok=False) and bad argument JSON are returned to the model
    as observations; they do not raise out of this function.
    """
    output_items: list[dict[str, Any]] = []
    summaries: list[ToolCallSummary] = []

    for call in tool_calls:
        name = getattr(call, "name", "unknown")
        call_id = getattr(call, "call_id", None) or getattr(call, "id", "")
        start = time.perf_counter()
        result = _execute_call(call, registry=registry, context=context)
        duration_ms = max(0, int((time.perf_counter() - start) * 1000))

        summaries.append(
            ToolCallSummary(
                name=name,
                args=getattr(call, "arguments", ""),
                ok=result.ok,
                duration_ms=duration_ms,
            )
        )
        output_items.append(
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": _serialize_tool_result(result),
            }
        )

    return DispatchResult(output_items=output_items, summaries=summaries)


def _execute_call(
    call: Any,
    *,
    registry: ToolRegistry,
    context: ToolContext,
) -> ToolResult:
    name = getattr(call, "name", "unknown")
    raw_args = getattr(call, "arguments", "") or ""
    try:
        arguments = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        return ToolResult(
            ok=False,
            data=None,
            error=f"invalid tool arguments JSON: {exc.msg}",
        )

    if not isinstance(arguments, dict):
        return ToolResult(
            ok=False,
            data=None,
            error="invalid tool arguments: expected a JSON object",
        )

    try:
        return registry.execute(name, context, arguments)
    except Exception as exc:  # noqa: BLE001 — keep the agent loop alive
        return ToolResult(ok=False, data=None, error=f"tool execution failed: {exc}")


def _serialize_tool_result(result: ToolResult) -> str:
    payload = {
        "ok": result.ok,
        "data": result.data,
        "truncated": result.truncated,
        "error": result.error,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
