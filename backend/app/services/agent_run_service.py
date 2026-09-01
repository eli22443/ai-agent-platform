"""Persistence for agent runs and ordered tool-call audit rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.agent.types import AgentResult
from app.database.models import AgentRunRecord, ToolCallRecord

# Cap stored argument JSON size (secret hygiene / row bloat).
_MAX_ARGUMENTS_BYTES = 8 * 1024


class AgentRunService:
    """Session-scoped; does not commit (caller / get_db owns the transaction)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def begin(self, task_id: UUID, *, model: str) -> AgentRunRecord:
        run = AgentRunRecord(
            task_id=task_id,
            status="running",
            model=model,
            started_at=datetime.now(UTC),
        )
        self._session.add(run)
        self._session.flush()
        return run

    def finish(self, run: AgentRunRecord, result: AgentResult) -> None:
        if result.error:
            status = "failed"
        elif result.halt_reason:
            status = "halted"
        else:
            status = "completed"

        run.status = status
        run.iterations = result.iterations
        run.prompt_tokens = result.prompt_tokens
        run.completion_tokens = result.completion_tokens
        run.total_tokens = result.total_tokens
        run.halt_reason = result.halt_reason
        run.result = result.answer
        run.error = result.error
        run.finished_at = datetime.now(UTC)

        records = [
            ToolCallRecord(
                agent_run_id=run.id,
                sequence=index,
                tool_name=summary.name,
                arguments=_parse_arguments(summary.args),
                ok=summary.ok,
                duration_ms=summary.duration_ms,
                error=summary.error,
                deduplicated=summary.deduplicated,
            )
            for index, summary in enumerate(result.tool_calls, start=1)
        ]
        self._session.add_all(records)
        self._session.flush()

    def list_for_task(self, task_id: UUID) -> list[AgentRunRecord]:
        return list(
            self._session.scalars(
                select(AgentRunRecord)
                .where(AgentRunRecord.task_id == task_id)
                .order_by(AgentRunRecord.started_at.desc())
            ).all()
        )

    def get_for_task(self, task_id: UUID, run_id: UUID) -> AgentRunRecord | None:
        return self._session.scalars(
            select(AgentRunRecord)
            .options(selectinload(AgentRunRecord.tool_calls))
            .where(
                AgentRunRecord.id == run_id,
                AgentRunRecord.task_id == task_id,
            )
        ).first()

    def tool_call_count(self, run_id: UUID) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(ToolCallRecord)
                .where(ToolCallRecord.agent_run_id == run_id)
            )
            or 0
        )


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    encoded = json.dumps(parsed, ensure_ascii=False, default=str)
    if len(encoded.encode("utf-8")) <= _MAX_ARGUMENTS_BYTES:
        return parsed
    return {
        "_truncated": True,
        "_original_bytes": len(encoded.encode("utf-8")),
        "_preview": encoded.encode("utf-8")[:_MAX_ARGUMENTS_BYTES].decode(
            "utf-8", errors="replace"
        ),
    }
