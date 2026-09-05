import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.database.models import RepositoryRecord, TaskRecord
from app.repositories.service import RepositoryService
from app.retrieval.vector_store import InMemoryVectorStore, namespace_for_task
from app.schemas.task import TaskStatus
from app.services.agent_run_service import AgentRunService
from app.services.task_service import TaskService
from app.tools.registry import build_read_only_registry
from app.workers.jobs import process_task
from tests.conftest import ALLOWED_HOSTS, FakeGitClient, public_getaddrinfo
from tests.llm_fakes import FakeLLMClient, text_response

REQUESTS_URL = "https://github.com/psf/requests"
INSTRUCTION = "Explain how the retry logic works."


def _pending_task(db_session: Session, *, url: str = REQUESTS_URL) -> TaskRecord:
    repo = RepositoryRecord(url=url)
    db_session.add(repo)
    db_session.flush()
    now = datetime.now(UTC)
    task = TaskRecord(
        repository_id=repo.id,
        instruction=INSTRUCTION,
        status=TaskStatus.PENDING.value,
        created_at=now,
        updated_at=now,
    )
    db_session.add(task)
    db_session.commit()
    return task


def _service(
    db_session: Session,
    repository_service: RepositoryService,
    *,
    embedder=None,
    store=None,
) -> TaskService:
    return TaskService(
        db_session,
        repository_service,
        AgentRunService(db_session),
        embedder=embedder,
        store=store,
    )


def test_process_pending_to_completed(
    db_session: Session, repository_service: RepositoryService
) -> None:
    task = _pending_task(db_session)
    service = _service(db_session, repository_service)

    result = service.process(
        task.id,
        FakeLLMClient([text_response("cookies live on Session")]),
        build_read_only_registry(),
    )

    assert result is not None
    assert result.answer == "cookies live on Session"
    record = db_session.get(TaskRecord, task.id)
    assert record is not None
    assert record.status == TaskStatus.COMPLETED.value
    assert record.result == "cookies live on Session"
    assert repository_service.workspace_path_for(task.id).is_dir()


def test_process_clone_failure_marks_failed(
    db_session: Session,
    tmp_path: Path,
    fixture_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("socket.getaddrinfo", public_getaddrinfo)
    repository_service = RepositoryService(
        FakeGitClient(fixture_repo, fail=True),
        tmp_path / "workspaces",
        ALLOWED_HOSTS,
        timeout=30,
        max_size_mb=200,
    )
    task = _pending_task(db_session)
    service = _service(db_session, repository_service)

    result = service.process(
        task.id,
        FakeLLMClient([text_response("should not run")]),
        build_read_only_registry(),
    )

    assert result is None
    record = db_session.get(TaskRecord, task.id)
    assert record is not None
    assert record.status == TaskStatus.FAILED.value
    assert record.error == "clone failed"


def test_process_indexing_failure_marks_failed(
    db_session: Session,
    repository_service: RepositoryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.retrieval.embeddings import EmbeddingError

    class FailingEmbedder:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingError("embedding unavailable")

    monkeypatch.setenv("RETRIEVAL_INDEX_ENABLED", "true")
    get_settings.cache_clear()
    try:
        task = _pending_task(db_session)
        service = _service(
            db_session,
            repository_service,
            embedder=FailingEmbedder(),
            store=InMemoryVectorStore(),
        )
        result = service.process(
            task.id,
            FakeLLMClient([text_response("should not run")]),
            build_read_only_registry(),
        )

        assert result is None
        record = db_session.get(TaskRecord, task.id)
        assert record is not None
        assert record.status == TaskStatus.FAILED.value
        assert record.error == "embedding unavailable"
    finally:
        monkeypatch.setenv("RETRIEVAL_INDEX_ENABLED", "false")
        get_settings.cache_clear()


def test_process_skips_non_pending(
    db_session: Session, repository_service: RepositoryService
) -> None:
    task = _pending_task(db_session)
    service = _service(db_session, repository_service)
    service.process(
        task.id,
        FakeLLMClient([text_response("done")]),
        build_read_only_registry(),
    )

    result = service.process(
        task.id,
        FakeLLMClient([text_response("again")]),
        build_read_only_registry(),
    )

    assert result is None
    record = db_session.get(TaskRecord, task.id)
    assert record is not None
    assert record.status == TaskStatus.COMPLETED.value
    assert record.result == "done"


def test_process_indexes_into_task_namespace(
    db_session: Session,
    repository_service: RepositoryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    class KeywordEmbedder:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setenv("RETRIEVAL_INDEX_ENABLED", "true")
    get_settings.cache_clear()
    store = InMemoryVectorStore()
    try:
        task = _pending_task(db_session)
        service = _service(
            db_session,
            repository_service,
            embedder=KeywordEmbedder(),
            store=store,
        )
        result = service.process(
            task.id,
            FakeLLMClient([text_response("ok")]),
            build_read_only_registry(),
        )

        assert result is not None
        matches = store.query(namespace_for_task(task.id), [1.0, 0.0], top_k=5)
        assert matches
    finally:
        monkeypatch.setenv("RETRIEVAL_INDEX_ENABLED", "false")
        get_settings.cache_clear()


def test_process_task_job_delegates(
    db_session: Session,
    repository_service: RepositoryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _pending_task(db_session)
    seen: list[object] = []

    def fake_process(self, task_id, llm, registry):  # noqa: ANN001
        seen.append(task_id)
        return None

    monkeypatch.setattr(TaskService, "process", fake_process)
    monkeypatch.setattr(
        "app.workers.jobs.get_repository_service", lambda: repository_service
    )
    monkeypatch.setattr(
        "app.workers.jobs.SessionLocal", lambda: db_session
    )
    monkeypatch.setattr(
        "app.workers.jobs.get_llm_client",
        lambda: FakeLLMClient([text_response("x")]),
    )
    monkeypatch.setattr(
        "app.workers.jobs.get_tool_registry", build_read_only_registry
    )

    # Avoid closing the shared test session.
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(db_session, "rollback", lambda: None)

    asyncio.run(process_task({}, str(task.id)))

    assert seen == [task.id]


def test_process_task_job_missing_task_is_noop() -> None:
    asyncio.run(process_task({}, str(uuid4())))
