"""ARQ worker entrypoint.

Run locally::

    cd backend
    uv run arq app.workers.main.WorkerSettings
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.logging import configure_logging
from app.queue.client import redis_settings as build_redis_settings
from app.workers.jobs import process_task

logger = logging.getLogger(__name__)

_settings = get_settings()


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging(_settings.log_level)
    logger.info(
        "arq worker starting job_timeout=%ss",
        _settings.arq_job_timeout_seconds,
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    logger.info("arq worker shutting down")


class WorkerSettings:
    """Discovered by ``arq app.workers.main.WorkerSettings``."""

    functions = [process_task]
    redis_settings = build_redis_settings(redis_url=_settings.redis_url)
    job_timeout = _settings.arq_job_timeout_seconds
    max_tries = 3
    on_startup = on_startup
    on_shutdown = on_shutdown
