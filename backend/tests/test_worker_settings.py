import asyncio
from uuid import uuid4

import pytest
from arq.worker import get_kwargs

from app.config import get_settings
from app.workers.jobs import process_task
from app.workers.main import WorkerSettings, on_shutdown, on_startup


def test_worker_settings_registers_process_task() -> None:
    settings = get_settings()

    assert process_task in WorkerSettings.functions
    assert WorkerSettings.on_startup is on_startup
    assert WorkerSettings.on_shutdown is on_shutdown
    assert WorkerSettings.max_tries == 3
    assert WorkerSettings.job_timeout == settings.arq_job_timeout_seconds
    assert WorkerSettings.redis_settings.host is not None

    kwargs = get_kwargs(WorkerSettings)
    assert kwargs["functions"] == [process_task]
    assert kwargs["job_timeout"] == settings.arq_job_timeout_seconds
    assert kwargs["max_tries"] == 3


def test_process_task_missing_task_is_noop() -> None:
    asyncio.run(process_task({}, str(uuid4())))


def test_startup_shutdown_hooks_run() -> None:
    asyncio.run(on_startup({}))
    asyncio.run(on_shutdown({}))
