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
from app.services.task_service import TaskService
from tests.conftest import ALLOWED_HOSTS, FakeGitClient, public_getaddrinfo

REQUESTS_URL = "https://github.com/psf/requests"
HTTPX_URL = "https://github.com/encode/httpx"
INSTRUCTION = "Explain how the retry logic works."


@pytest.fixture
def task_service(db_session: Session, repository_service: RepositoryService):
    return TaskService(db_session, repository_service)


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
    service = TaskService(db_session, repository_service)

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
