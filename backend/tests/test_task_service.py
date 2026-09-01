import inspect
from datetime import UTC
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import RepositoryRecord, TaskRecord
from app.repositories.errors import CloneError, InvalidRepositoryUrl
from app.repositories.service import RepositoryService
from app.schemas.task import TaskStatus
from app.services import task_service as task_service_module
from app.services.agent_run_service import AgentRunService
from app.services.task_service import TaskService
from tests.conftest import ALLOWED_HOSTS, FakeGitClient, public_getaddrinfo

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


def test_create_success_sets_commit_metadata(
    db_session: Session, task_service: TaskService
):
    task_service.create(REQUESTS_URL, INSTRUCTION)

    repository_record = db_session.scalars(
        select(RepositoryRecord).where(RepositoryRecord.url == REQUESTS_URL)
    ).one()
    assert repository_record.last_commit_sha == "abc123def456"
    assert repository_record.default_branch == "main"


def test_invalid_url_does_not_create_rows(
    db_session: Session, task_service: TaskService
):
    with pytest.raises(InvalidRepositoryUrl):
        task_service.create("https://127.0.0.1/secret", INSTRUCTION)

    assert db_session.scalars(select(RepositoryRecord)).all() == []
    assert db_session.scalars(select(TaskRecord)).all() == []


def test_clone_error_marks_task_failed(
    db_session: Session,
    tmp_path: Path,
    fixture_repo,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("socket.getaddrinfo", public_getaddrinfo)
    repository_service = RepositoryService(
        FakeGitClient(fixture_repo, fail=True),
        tmp_path / "workspaces",
        ALLOWED_HOSTS,
        timeout=30,
        max_size_mb=200,
    )
    service = TaskService(
        db_session, repository_service, AgentRunService(db_session)
    )

    with pytest.raises(CloneError):
        service.create(REQUESTS_URL, INSTRUCTION)

    record = db_session.scalars(select(TaskRecord)).one()
    assert record.status == TaskStatus.FAILED.value
    assert record.error
    assert not (tmp_path / "workspaces" / str(record.id)).exists()


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


def test_run_unknown_task_raises_not_found(task_service: TaskService):
    from app.services.errors import TaskNotFound
    from app.tools.registry import build_read_only_registry
    from tests.llm_fakes import FakeLLMClient, text_response

    with pytest.raises(TaskNotFound):
        task_service.run(
            UUID("00000000-0000-0000-0000-000000000000"),
            FakeLLMClient([text_response("x")]),
            build_read_only_registry(),
        )


def test_run_success_persists_completed_result(
    db_session: Session, task_service: TaskService
):
    from app.tools.registry import build_read_only_registry
    from tests.llm_fakes import FakeLLMClient, text_response

    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    llm = FakeLLMClient([text_response("Session handles cookies.")])

    result = task_service.run(task.id, llm, build_read_only_registry())

    assert result.completed is True
    assert result.answer == "Session handles cookies."
    record = db_session.get(TaskRecord, task.id)
    assert record is not None
    assert record.status == TaskStatus.COMPLETED.value
    assert record.result == "Session handles cookies."
    assert record.error is None


def test_run_second_time_raises_not_runnable(task_service: TaskService):
    from app.services.errors import TaskNotRunnable
    from app.tools.registry import build_read_only_registry
    from tests.llm_fakes import FakeLLMClient, text_response

    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    registry = build_read_only_registry()
    task_service.run(task.id, FakeLLMClient([text_response("done")]), registry)

    with pytest.raises(TaskNotRunnable, match="not runnable"):
        task_service.run(
            task.id, FakeLLMClient([text_response("again")]), registry
        )


def test_run_missing_workspace_raises_not_runnable(
    task_service: TaskService,
    repository_service: RepositoryService,
):
    from app.repositories.workspace import remove as remove_workspace
    from app.services.errors import TaskNotRunnable
    from app.tools.registry import build_read_only_registry
    from tests.llm_fakes import FakeLLMClient, text_response

    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    remove_workspace(repository_service.workspace_path_for(task.id))

    with pytest.raises(TaskNotRunnable, match="workspace"):
        task_service.run(
            task.id,
            FakeLLMClient([text_response("x")]),
            build_read_only_registry(),
        )


def test_run_llm_error_persists_failed(
    db_session: Session, task_service: TaskService
):
    from app.llm import LLMError
    from app.tools.registry import build_read_only_registry
    from tests.llm_fakes import FakeLLMClient

    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    result = task_service.run(
        task.id,
        FakeLLMClient([LLMError("OpenAI request failed.")]),
        build_read_only_registry(),
    )

    assert result.error == "OpenAI request failed."
    record = db_session.get(TaskRecord, task.id)
    assert record is not None
    assert record.status == TaskStatus.FAILED.value
    assert record.error == "OpenAI request failed."
    assert record.result is None


def test_run_commits_running_before_agent(
    session_factory, repository_service: RepositoryService
):
    from app.database.models import AgentRunRecord
    from app.tools.registry import build_read_only_registry
    from tests.llm_fakes import FakeLLMClient, text_response

    session = session_factory()
    try:
        service = TaskService(
            session, repository_service, AgentRunService(session)
        )
        task = service.create(REQUESTS_URL, INSTRUCTION)
        session.commit()
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

        result = service.run(
            task_id,
            SpyLLM([text_response("done")]),
            build_read_only_registry(),
        )
        session.commit()
    finally:
        session.close()

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


def test_run_halt_persists_completed_with_prefix(
    db_session: Session, task_service: TaskService, monkeypatch: pytest.MonkeyPatch
):
    from app.config import get_settings
    from app.tools.registry import build_read_only_registry
    from tests.llm_fakes import FakeLLMClient, tool_call_response

    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "1")
    get_settings.cache_clear()
    try:
        task = task_service.create(REQUESTS_URL, INSTRUCTION)
        result = task_service.run(
            task.id,
            FakeLLMClient([tool_call_response()]),
            build_read_only_registry(),
        )

        assert result.halt_reason == "max_iterations"
        record = db_session.get(TaskRecord, task.id)
        assert record is not None
        assert record.status == TaskStatus.COMPLETED.value
        assert record.result is not None
        assert record.result.startswith("[halted: max_iterations]")
        assert record.error is None
    finally:
        get_settings.cache_clear()
