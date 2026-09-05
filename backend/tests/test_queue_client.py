import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.queue.client import (
    PROCESS_TASK_JOB,
    QueueError,
    enqueue_process_task,
    enqueue_process_task_async,
    get_redis_pool,
)


def test_get_redis_pool_uses_settings_url(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, object] = {}

    async def fake_create_pool(settings: object) -> MagicMock:
        created["settings"] = settings
        return MagicMock()

    monkeypatch.setattr("app.queue.client.create_pool", fake_create_pool)
    monkeypatch.setattr(
        "app.queue.client.get_settings",
        lambda: SimpleNamespace(redis_url="redis://example:6379/2"),
    )

    pool = asyncio.run(get_redis_pool())

    assert pool is not None
    settings = created["settings"]
    assert settings.host == "example"
    assert settings.port == 6379
    assert settings.database == 2


def test_get_redis_pool_wraps_connection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(_settings: object) -> MagicMock:
        raise ConnectionError("refused")

    monkeypatch.setattr("app.queue.client.create_pool", boom)

    with pytest.raises(QueueError, match="Failed to connect to Redis"):
        asyncio.run(get_redis_pool(redis_url="redis://127.0.0.1:6379/0"))


def test_enqueue_process_task_async_enqueues_with_stable_job_id() -> None:
    task_id = uuid4()
    redis = AsyncMock()
    redis.enqueue_job = AsyncMock(
        return_value=SimpleNamespace(job_id=f"{PROCESS_TASK_JOB}:{task_id}")
    )
    redis.aclose = AsyncMock()

    asyncio.run(enqueue_process_task_async(task_id, redis=redis))

    redis.enqueue_job.assert_awaited_once_with(
        PROCESS_TASK_JOB,
        str(task_id),
        _job_id=f"{PROCESS_TASK_JOB}:{task_id}",
    )
    redis.aclose.assert_not_awaited()


def test_enqueue_process_task_async_opens_pool_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    redis = AsyncMock()
    redis.enqueue_job = AsyncMock(return_value=SimpleNamespace(job_id="job-1"))
    redis.aclose = AsyncMock()

    async def fake_pool(**_kwargs: object) -> AsyncMock:
        return redis

    monkeypatch.setattr("app.queue.client.get_redis_pool", fake_pool)

    asyncio.run(enqueue_process_task_async(task_id))

    redis.enqueue_job.assert_awaited_once()
    redis.aclose.assert_awaited_once_with(close_connection_pool=True)


def test_enqueue_process_task_async_duplicate_job_is_ok() -> None:
    redis = AsyncMock()
    redis.enqueue_job = AsyncMock(return_value=None)
    redis.aclose = AsyncMock()

    asyncio.run(enqueue_process_task_async(uuid4(), redis=redis))

    redis.enqueue_job.assert_awaited_once()


def test_enqueue_process_task_async_wraps_enqueue_errors() -> None:
    redis = AsyncMock()
    redis.enqueue_job = AsyncMock(side_effect=RuntimeError("boom"))
    redis.aclose = AsyncMock()

    with pytest.raises(QueueError, match="Failed to enqueue"):
        asyncio.run(enqueue_process_task_async(uuid4(), redis=redis))


def test_enqueue_process_task_sync_runs_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    called: list[UUID] = []

    async def fake_async(tid: object, *, redis: object = None) -> None:
        assert redis is None
        called.append(tid)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "app.queue.client.enqueue_process_task_async", fake_async
    )

    enqueue_process_task(task_id)

    assert called == [task_id]
