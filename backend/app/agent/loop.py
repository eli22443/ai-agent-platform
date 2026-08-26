from __future__ import annotations

from typing import Any

from app.agent.dispatch import (
    DispatchCache,
    dispatch_tool_calls,
    extract_function_calls,
)
from app.agent.limits import AgentLimits, LimitTracker
from app.agent.prompts import build_system_prompt, build_user_message
from app.agent.types import AgentResult, ToolCallSummary
from app.llm import LLMClient, LLMError
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry

_BUDGET_NUDGE = (
    "You are near the tool-call budget. Prefer a final plain-text answer now "
    "using evidence already gathered. Only call a tool if strictly necessary."
)


def run_agent(
    *,
    instruction: str,
    context: ToolContext,
    registry: ToolRegistry,
    llm: LLMClient,
    limits: AgentLimits,
    model: str,
    repository_url: str,
    branch: str | None = None,
    head_sha: str | None = None,
) -> AgentResult:
    """Own the Responses API tool loop. No DB or HTTP.

    Conversation state is an explicit input list (not previous_response_id).
    Model function_call items are appended before function_call_output items
    so the next turn has a valid call_id chain.
    """
    system = build_system_prompt()
    input_list: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": build_user_message(
                instruction=instruction,
                repository_url=repository_url,
                branch=branch,
                head_sha=head_sha,
            ),
        }
    ]
    tools = registry.list_schemas()
    tracker = LimitTracker(limits)
    summaries: list[ToolCallSummary] = []
    partial = ""
    cache = DispatchCache()
    budget_nudge_sent = False

    while True:
        reason = tracker.check()
        if reason:
            return _halt(partial, reason, tracker, summaries)

        if (
            not budget_nudge_sent
            and tracker.iterations > 0
            and limits.max_iterations - tracker.iterations <= 2
        ):
            input_list.append({"role": "user", "content": _BUDGET_NUDGE})
            budget_nudge_sent = True

        try:
            response = llm.create_response(
                model=model,
                instructions=system,
                input=input_list,
                tools=tools,
            )
        except LLMError as exc:
            return AgentResult(
                answer=partial,
                completed=False,
                halt_reason=None,
                iterations=tracker.iterations,
                tool_calls=summaries,
                error=str(exc),
            )

        tracker.record_iteration()
        if response.usage is not None:
            tracker.add_tokens(getattr(response.usage, "total_tokens", None))

        text = _output_text(response)
        if text:
            partial = text

        tool_calls = extract_function_calls(response.output)
        if not tool_calls:
            return AgentResult(
                answer=partial,
                completed=True,
                halt_reason=None,
                iterations=tracker.iterations,
                tool_calls=summaries,
                error=None,
            )

        reason = tracker.check()
        if reason:
            return _halt(partial, reason, tracker, summaries)

        # Reasoning models (gpt-5*) require paired reasoning items when
        # replaying function_call items on the next turn.
        input_list.extend(_model_output_as_input(response.output))
        dispatched = dispatch_tool_calls(
            tool_calls,
            registry=registry,
            context=context,
            cache=cache,
        )
        input_list.extend(dispatched.output_items)
        summaries.extend(dispatched.summaries)


def _halt(
    partial: str,
    reason: str,
    tracker: LimitTracker,
    summaries: list[ToolCallSummary],
) -> AgentResult:
    return AgentResult(
        answer=partial or f"Stopped: {reason}",
        completed=False,
        halt_reason=reason,
        iterations=tracker.iterations,
        tool_calls=summaries,
        error=None,
    )


def _output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text

    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", None) or []:
            if getattr(content, "type", None) == "output_text":
                parts.append(getattr(content, "text", "") or "")
    return "".join(parts)


def _model_output_as_input(output: list[Any] | None) -> list[dict[str, Any]]:
    """Echo model output items needed for the next Responses API turn.

    Preserve order: reasoning items must accompany their function_call items.
    All function_calls are collected before function_call_outputs (caller).
    """
    items: list[dict[str, Any]] = []
    for item in output or []:
        item_type = getattr(item, "type", None)
        if item_type == "reasoning":
            items.append(_reasoning_as_input(item))
        elif item_type == "function_call":
            items.append(_function_call_as_input(item))
    return items


def _reasoning_as_input(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        dumped = item.model_dump(exclude_none=True)
        # Keep opaque reasoning payload fields the API expects on replay.
        keep = {"type", "id", "summary", "encrypted_content", "status"}
        return {key: dumped[key] for key in keep if key in dumped}

    result: dict[str, Any] = {"type": "reasoning"}
    for key in ("id", "summary", "encrypted_content", "status"):
        value = getattr(item, key, None)
        if value is not None:
            result[key] = value
    return result


def _function_call_as_input(call: Any) -> dict[str, Any]:
    if hasattr(call, "model_dump"):
        dumped = call.model_dump(exclude_none=True)
        item = {
            "type": "function_call",
            "call_id": dumped["call_id"],
            "name": dumped["name"],
            "arguments": dumped["arguments"],
        }
        if dumped.get("id"):
            item["id"] = dumped["id"]
        return item

    item = {
        "type": "function_call",
        "call_id": getattr(call, "call_id"),
        "name": getattr(call, "name"),
        "arguments": getattr(call, "arguments"),
    }
    call_id = getattr(call, "id", None)
    if call_id:
        item["id"] = call_id
    return item
