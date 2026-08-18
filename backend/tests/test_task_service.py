from datetime import UTC
from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas.task import TaskStatus
from app.services.task_service import TaskService


def test_service_create_assigns_pending_status(db_session: Session):
    service = TaskService(db_session)

    task = service.create(
        "https://github.com/psf/requests",
        "Explain how the retry logic works.",
    )

    assert isinstance(task.id, UUID)
    assert task.status is TaskStatus.PENDING
    assert task.created_at.tzinfo is not None
    assert task.created_at.tzinfo == UTC


def test_service_get_returns_none_when_missing(db_session: Session):
    service = TaskService(db_session)

    result = service.get(UUID("00000000-0000-0000-0000-000000000000"))

    assert result is None


def test_service_list_returns_all_created(db_session: Session):
    service = TaskService(db_session)
    first = service.create(
        "https://github.com/psf/requests",
        "Explain how the retry logic works.",
    )
    second = service.create(
        "https://github.com/encode/httpx",
        "Summarize the transport layer design.",
    )

    tasks = service.list_all()

    assert len(tasks) == 2
    assert {task.id for task in tasks} == {first.id, second.id}
