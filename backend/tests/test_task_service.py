import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import RepositoryRecord, TaskRecord
from app.repositories.errors import InvalidRepositoryUrl
from app.repositories.service import RepositoryService
from app.schemas.task import TaskStatus
from app.services import task_service as task_service_module
from app.services.agent_run_service import AgentRunService
from app.services.task_service import TaskService
from app.tools.registry import build_read_only_registry
from tests.llm_fakes import FakeLLMClient, text_response, tool_call_response

REQUESTS_URL = "https://github.com/psf/requests"
HTTPX_URL = "https://github.com/encode/httpx"
INSTRUCTION = "Explain how the retry logic works."


@pytest.fixture
def task_service(db_session: Session, repository_service: RepositoryService):
    return TaskService(
        db_session, repository_service, AgentRunService(db_session)
    )


def test_service_create_assigns_pending_status(task_service: TaskService):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)

    assert isinstance(task.id, UUID)
    assert task.status is TaskStatus.PENDING
    assert task.created_at.tzinfo is not None
    assert task.created_at.tzinfo == UTC


def test_service_create_does_not_clone(
    task_service: TaskService, repository_service: RepositoryService
):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)

    assert not repository_service.workspace_path_for(task.id).exists()


def test_service_create_enqueues_process_task(
    task_service: TaskService, monkeypatch: pytest.MonkeyPatch
):
    enqueued: list[UUID] = []
    monkeypatch.setattr(
        "app.services.task_service.enqueue_process_task",
        lambda task_id: enqueued.append(task_id),
    )

    task = task_service.create(REQUESTS_URL, INSTRUCTION)

    assert enqueued == [task.id]


def test_service_get_returns_none_when_missing(task_service: TaskService):
    result = task_service.get(UUID("00000000-0000-0000-0000-000000000000"))

    assert result is None


def test_service_list_returns_all_created(task_service: TaskService):
    first = task_service.create(REQUESTS_URL, INSTRUCTION)
    second = task_service.create(
        HTTPX_URL,
        "Summarize the transport layer design.",
    )

    tasks = task_service.list_all()

    assert len(tasks) == 2
    assert {task.id for task in tasks} == {first.id, second.id}


def test_create_does_not_set_commit_metadata_until_process(
    db_session: Session, task_service: TaskService
):
    task_service.create(REQUESTS_URL, INSTRUCTION)

    repository_record = db_session.scalars(
        select(RepositoryRecord).where(RepositoryRecord.url == REQUESTS_URL)
    ).one()
    assert repository_record.last_commit_sha is None
    assert repository_record.default_branch is None


def test_invalid_url_does_not_create_rows(
    db_session: Session, task_service: TaskService
):
    with pytest.raises(InvalidRepositoryUrl):
        task_service.create("https://127.0.0.1/secret", INSTRUCTION)

    assert db_session.scalars(select(RepositoryRecord)).all() == []
    assert db_session.scalars(select(TaskRecord)).all() == []


def test_task_service_does_not_import_subprocess():
    assert "subprocess" not in inspect.getsource(task_service_module)


def test_subprocess_is_confined_to_allowed_modules():
    """Clone uses repositories/git_client; tools may use git.py and search.py only."""
    app_root = Path(__file__).resolve().parents[1] / "app"
    allowed = {
        "repositories/git_client.py",
        "tools/git.py",
        "tools/search.py",
    }
    offenders = [
        path
        for path in app_root.rglob("*.py")
        if "subprocess" in path.read_text()
        and path.relative_to(app_root).as_posix() not in allowed
    ]
    assert offenders == []


def test_process_success_persists_completed_result(
    db_session: Session, task_service: TaskService
):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    result = task_service.process(
        task.id,
        FakeLLMClient([text_response("Session handles cookies.")]),
        build_read_only_registry(),
    )

    assert result is not None
    assert result.completed is True
    assert result.answer == "Session handles cookies."
    record = db_session.get(TaskRecord, task.id)
    assert record is not None
    assert record.status == TaskStatus.COMPLETED.value
    assert record.result == "Session handles cookies."
    assert record.error is None


def test_process_sets_commit_metadata(
    db_session: Session, task_service: TaskService
):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    task_service.process(
        task.id,
        FakeLLMClient([text_response("ok")]),
        build_read_only_registry(),
    )

    repository_record = db_session.scalars(
        select(RepositoryRecord).where(RepositoryRecord.url == REQUESTS_URL)
    ).one()
    assert repository_record.last_commit_sha == "abc123def456"
    assert repository_record.default_branch == "main"


def test_process_second_time_is_noop(task_service: TaskService):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    registry = build_read_only_registry()
    task_service.process(task.id, FakeLLMClient([text_response("done")]), registry)

    assert (
        task_service.process(
            task.id, FakeLLMClient([text_response("again")]), registry
        )
        is None
    )


def test_fail_stuck_running_tasks(
    db_session: Session, task_service: TaskService
) -> None:
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    record = db_session.get(TaskRecord, task.id)
    assert record is not None
    record.status = TaskStatus.RUNNING.value
    record.updated_at = datetime.now(UTC) - timedelta(minutes=60)
    db_session.commit()

    n = task_service.fail_stuck_running_tasks(older_than_minutes=30)

    assert n == 1
    db_session.refresh(record)
    assert record.status == TaskStatus.FAILED.value
    assert record.error == "worker timeout"


def test_fail_stuck_running_tasks_ignores_fresh(
    db_session: Session, task_service: TaskService
) -> None:
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    record = db_session.get(TaskRecord, task.id)
    assert record is not None
    record.status = TaskStatus.RUNNING.value
    record.updated_at = datetime.now(UTC)
    db_session.commit()

    assert task_service.fail_stuck_running_tasks(older_than_minutes=30) == 0
    db_session.refresh(record)
    assert record.status == TaskStatus.RUNNING.value


def test_process_llm_error_persists_failed(
    db_session: Session, task_service: TaskService
):
    from app.llm import LLMError

    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    result = task_service.process(
        task.id,
        FakeLLMClient([LLMError("OpenAI request failed.")]),
        build_read_only_registry(),
    )

    assert result is not None
    assert result.error == "OpenAI request failed."
    record = db_session.get(TaskRecord, task.id)
    assert record is not None
    assert record.status == TaskStatus.FAILED.value
    assert record.error == "OpenAI request failed."
    assert record.result is None


def test_process_commits_running_before_agent(
    session_factory, repository_service: RepositoryService, monkeypatch: pytest.MonkeyPatch
):
    from app.database.models import AgentRunRecord

    monkeypatch.setattr(
        "app.services.task_service.enqueue_process_task",
        lambda _task_id: None,
    )

    session = session_factory()
    try:
        service = TaskService(
            session, repository_service, AgentRunService(session)
        )
        task = service.create(REQUESTS_URL, INSTRUCTION)
        task_id = task.id

        seen: dict[str, str | None] = {"task_status": None, "run_status": None}

        class SpyLLM(FakeLLMClient):
            def create_response(self, *, model, input, tools, instructions=None):
                other = session_factory()
                try:
                    record = other.get(TaskRecord, task_id)
                    seen["task_status"] = None if record is None else record.status
                    run = other.scalars(
                        select(AgentRunRecord).where(AgentRunRecord.task_id == task_id)
                    ).first()
                    seen["run_status"] = None if run is None else run.status
                finally:
                    other.close()
                return super().create_response(
                    model=model,
                    input=input,
                    tools=tools,
                    instructions=instructions,
                )

        result = service.process(
            task_id,
            SpyLLM([text_response("done")]),
            build_read_only_registry(),
        )
    finally:
        session.close()

    assert result is not None
    assert seen["task_status"] == TaskStatus.RUNNING.value
    assert seen["run_status"] == "running"
    assert result.answer == "done"
    assert result.run_id is not None

    session = session_factory()
    try:
        record = session.get(TaskRecord, task_id)
        assert record is not None
        assert record.status == TaskStatus.COMPLETED.value
        run = session.get(AgentRunRecord, result.run_id)
        assert run is not None
        assert run.status == "completed"
    finally:
        session.close()


def test_process_halt_persists_completed_with_prefix(
    db_session: Session, task_service: TaskService, monkeypatch: pytest.MonkeyPatch
):
    from app.config import get_settings

    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "1")
    get_settings.cache_clear()
    try:
        task = task_service.create(REQUESTS_URL, INSTRUCTION)
        result = task_service.process(
            task.id,
            FakeLLMClient([tool_call_response()]),
            build_read_only_registry(),
        )

        assert result is not None
        assert result.halt_reason == "max_iterations"
        record = db_session.get(TaskRecord, task.id)
        assert record is not None
        assert record.status == TaskStatus.COMPLETED.value
        assert record.result is not None
        assert record.result.startswith("[halted: max_iterations]")
        assert record.error is None
    finally:
        get_settings.cache_clear()


def test_process_indexes_when_retrieval_enabled(
    db_session: Session,
    repository_service: RepositoryService,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.config import get_settings
    from app.retrieval.vector_store import InMemoryVectorStore, namespace_for_task

    class KeywordEmbedder:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setenv("RETRIEVAL_INDEX_ENABLED", "true")
    get_settings.cache_clear()
    store = InMemoryVectorStore()
    try:
        service = TaskService(
            db_session,
            repository_service,
            AgentRunService(db_session),
            embedder=KeywordEmbedder(),
            store=store,
        )
        task = service.create(REQUESTS_URL, INSTRUCTION)
        result = service.process(
            task.id,
            FakeLLMClient([text_response("ok")]),
            build_read_only_registry(),
        )

        assert result is not None
        assert result.answer == "ok"
        matches = store.query(namespace_for_task(task.id), [1.0, 0.0], top_k=5)
        assert matches
        assert any(m.metadata.get("file_path") for m in matches)
    finally:
        monkeypatch.setenv("RETRIEVAL_INDEX_ENABLED", "false")
        get_settings.cache_clear()


def test_process_retrieval_error_marks_failed(
    db_session: Session,
    repository_service: RepositoryService,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.config import get_settings
    from app.retrieval.embeddings import EmbeddingError
    from app.retrieval.vector_store import InMemoryVectorStore

    class FailingEmbedder:
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingError("embedding unavailable")

    monkeypatch.setenv("RETRIEVAL_INDEX_ENABLED", "true")
    get_settings.cache_clear()
    try:
        service = TaskService(
            db_session,
            repository_service,
            AgentRunService(db_session),
            embedder=FailingEmbedder(),
            store=InMemoryVectorStore(),
        )
        task = service.create(REQUESTS_URL, INSTRUCTION)
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
