from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.agent.types import ToolCallSummary
from app.tools.base import ToolContext, ToolResult
from app.tools.registry import ToolRegistry

# Same path + start_line within this many lines of a prior read → soft dedupe.
_READ_NEAR_DUP_DELTA = 50


@dataclass
class DispatchCache:
    """Per-run memory of tool calls so the loop can skip redundant work."""

    exact: dict[str, ToolResult] = field(default_factory=dict)
    read_starts: list[tuple[str, int]] = field(default_factory=list)


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
    cache: DispatchCache | None = None,
) -> DispatchResult:
    """Execute model function calls and build function_call_output items.

    Tool failures (ok=False) and bad argument JSON are returned to the model
    as observations; they do not raise out of this function.

    When ``cache`` is provided, identical calls (and near-duplicate read_file
    windows) return a short dedupe observation instead of re-executing.
    """
    if cache is None:
        cache = DispatchCache()

    output_items: list[dict[str, Any]] = []
    summaries: list[ToolCallSummary] = []

    for call in tool_calls:
        name = getattr(call, "name", "unknown")
        raw_args = getattr(call, "arguments", "") or ""
        call_id = getattr(call, "call_id", None) or getattr(call, "id", "")
        start = time.perf_counter()
        result = _execute_call(
            call,
            registry=registry,
            context=context,
            cache=cache,
            name=name,
            raw_args=raw_args,
        )
        duration_ms = max(0, int((time.perf_counter() - start) * 1000))

        summaries.append(
            ToolCallSummary(
                name=name,
                args=raw_args,
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
    cache: DispatchCache,
    name: str,
    raw_args: str,
) -> ToolResult:
    try:
        arguments = json.loads(raw_args) if raw_args else {}
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

    cache_key = _exact_cache_key(name, arguments)
    if cache_key in cache.exact:
        prior = cache.exact[cache_key]
        message = (
            "This exact tool call already ran earlier in this run. "
            "Use the previous tool result; do not assume new content."
        )
        if not prior.ok and prior.error:
            message = f"{message} Prior error was: {prior.error}"
        return _deduped_result(message)

    near = _near_duplicate_read(name, arguments, cache)
    if near is not None:
        return near

    try:
        result = registry.execute(name, context, arguments)
    except Exception as exc:  # noqa: BLE001 — keep the agent loop alive
        return ToolResult(ok=False, data=None, error=f"tool execution failed: {exc}")

    # Cache successes and tool-level failures so the model cannot burn turns
    # retrying the identical call (e.g. the same bad path).
    cache.exact[cache_key] = result
    if result.ok:
        _record_read_start(name, arguments, cache)

    return result


def _exact_cache_key(name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    return f"{name}:{canonical}"


def _near_duplicate_read(
    name: str,
    arguments: dict[str, Any],
    cache: DispatchCache,
) -> ToolResult | None:
    if name != "read_file":
        return None
    path = arguments.get("path")
    if not isinstance(path, str) or not path:
        return None
    start_line = arguments.get("start_line", 1)
    if not isinstance(start_line, int):
        return None

    for prior_path, prior_start in cache.read_starts:
        if prior_path != path:
            continue
        if abs(start_line - prior_start) < _READ_NEAR_DUP_DELTA:
            return _deduped_result(
                f"A prior read_file of {path!r} near start_line={prior_start} "
                f"already ran in this run (requested start_line={start_line}). "
                "Use that result, or continue with start_line=end_line+1 from a "
                "truncated read."
            )
    return None


def _record_read_start(
    name: str,
    arguments: dict[str, Any],
    cache: DispatchCache,
) -> None:
    if name != "read_file":
        return
    path = arguments.get("path")
    if not isinstance(path, str) or not path:
        return
    start_line = arguments.get("start_line", 1)
    if not isinstance(start_line, int):
        start_line = 1
    cache.read_starts.append((path, start_line))


def _deduped_result(message: str) -> ToolResult:
    return ToolResult(
        ok=True,
        data={"deduplicated": True, "message": message},
        truncated=False,
        error=None,
    )


def _serialize_tool_result(result: ToolResult) -> str:
    payload = {
        "ok": result.ok,
        "data": result.data,
        "truncated": result.truncated,
        "error": result.error,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
