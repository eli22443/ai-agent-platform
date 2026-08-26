from dataclasses import dataclass


@dataclass
class ToolCallSummary:
    name: str
    args: str
    ok: bool
    duration_ms: int


@dataclass
class AgentResult:
    answer: str
    completed: bool  # True if model produced a final answer without hitting a limit
    halt_reason: str | None  # None if completed normally
    iterations: int
    tool_calls: list[ToolCallSummary]
    error: (
        str | None
    )  # infra failure message; mutually exclusive with a clean answer path
