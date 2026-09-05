"""ARQ job functions."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.api.dependencies import (
    get_llm_client,
    get_repository_service,
    get_tool_registry,
)
from app.database.session import SessionLocal
from app.services.agent_run_service import AgentRunService
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)


async def process_task(ctx: dict[str, Any], task_id: str) -> None:
    """Clone, index, and run the agent for ``task_id`` (ARQ worker only)."""
    logger.info("process_task start task_id=%s", task_id)
    await asyncio.to_thread(_process_task_sync, task_id)
    logger.info("process_task done task_id=%s", task_id)


def _process_task_sync(task_id: str) -> None:
    session = SessionLocal()
    try:
        service = TaskService(
            session,
            get_repository_service(),
            AgentRunService(session),
        )
        service.process(
            UUID(task_id),
            get_llm_client(),
            get_tool_registry(),
        )
    except Exception:
        session.rollback()
        logger.exception("process_task failed task_id=%s", task_id)
        raise
    finally:
        session.close()
