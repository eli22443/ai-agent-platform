from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AgentRunToolCallResponse(BaseModel):
    sequence: int
    name: str
    args: str
    ok: bool
    duration_ms: int
    error: str | None = None
    deduplicated: bool = False


class AgentRunSummaryResponse(BaseModel):
    run_id: UUID
    status: str
    model: str | None
    iterations: int | None
    halt_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    started_at: datetime | None
    finished_at: datetime | None
    tool_call_count: int


class AgentRunDetailResponse(AgentRunSummaryResponse):
    result: str | None
    error: str | None
    tool_calls: list[AgentRunToolCallResponse]
