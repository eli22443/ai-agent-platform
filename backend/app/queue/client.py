from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings

logger = logging.getLogger(__name__)

PROCESS_TASK_JOB = "process_task"


class QueueError(Exception):
    """Failed to talk to Redis / enqueue a job. Message is safe to surface."""


def redis_settings(*, redis_url: str | None = None) -> RedisSettings:
    return RedisSettings.from_dsn(redis_url or get_settings().redis_url)


async def get_redis_pool(*, redis_url: str | None = None) -> ArqRedis:
    try:
        return await create_pool(redis_settings(redis_url=redis_url))
    except Exception as exc:
        logger.exception("redis pool create failed")
        raise QueueError("Failed to connect to Redis.") from exc


async def enqueue_process_task_async(
    task_id: UUID,
    *,
    redis: ArqRedis | None = None,
) -> None:
    """Enqueue ``process_task``. Opens a short-lived pool when ``redis`` is omitted."""
    owns_pool = redis is None
    pool = redis or await get_redis_pool()
    try:
        job = await pool.enqueue_job(
            PROCESS_TASK_JOB,
            str(task_id),
            _job_id=f"{PROCESS_TASK_JOB}:{task_id}",
        )
    except Exception as exc:
        logger.exception("enqueue process_task failed task_id=%s", task_id)
        raise QueueError("Failed to enqueue background job.") from exc
    finally:
        if owns_pool:
            await pool.aclose(close_connection_pool=True)

    if job is None:
        logger.info("process_task already queued task_id=%s", task_id)
    else:
        logger.info("enqueued process_task task_id=%s job_id=%s", task_id, job.job_id)


def enqueue_process_task(task_id: UUID) -> None:
    """Sync entry point for ``TaskService.create`` (FastAPI sync routes)."""
    asyncio.run(enqueue_process_task_async(task_id))
