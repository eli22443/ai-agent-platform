"""Task persistence against PostgreSQL.

The service maps database rows to the domain Task dataclass. It does not
commit: the request-scoped session in get_db() owns the transaction.
The CloneError path is the exception: the failed task row is committed
before re-raise so a 502 can still leave a `failed` record.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Repository, TaskRecord
from app.repositories.errors import CloneError
from app.repositories.service import RepositoryService
from app.repositories.workspace import remove as remove_workspace
from app.schemas.task import TaskStatus


@dataclass
class Task:
    id: UUID
    repository_url: str
    instruction: str
    status: TaskStatus
    created_at: datetime


class TaskService:
    def __init__(
        self, session: Session, repository_service: RepositoryService
    ) -> None:
        self._session = session
        self._repository_service = repository_service

    def create(self, repository_url: str, instruction: str) -> Task:
        self._repository_service.validate_url(repository_url)

        repository = self._session.scalars(
            select(Repository).where(Repository.url == repository_url)
        ).first()
        if repository is None:
            repository = Repository(url=repository_url)
            self._session.add(repository)
            self._session.flush()

        now = datetime.now(UTC)
        record = TaskRecord(
            repository_id=repository.id,
            instruction=instruction,
            status=TaskStatus.PENDING.value,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        self._session.flush()

        try:
            prepared = self._repository_service.prepare(
                repository_url, record.id
            )
        except CloneError as exc:
            record.status = TaskStatus.FAILED.value
            record.error = str(exc)
            record.updated_at = datetime.now(UTC)
            self._session.flush()
            remove_workspace(
                self._repository_service.workspace_path_for(record.id)
            )
            self._session.commit()
            raise

        repository.default_branch = prepared.current_branch
        repository.last_commit_sha = prepared.head_sha
        self._session.flush()
        return _to_task(record, repository)

    def get(self, task_id: UUID) -> Task | None:
        row = self._session.execute(
            select(TaskRecord, Repository)
            .join(Repository, TaskRecord.repository_id == Repository.id)
            .where(TaskRecord.id == task_id)
        ).first()
        if row is None:
            return None
        record, repository = row
        return _to_task(record, repository)

    def list_all(self) -> list[Task]:
        rows = self._session.execute(
            select(TaskRecord, Repository).join(
                Repository, TaskRecord.repository_id == Repository.id
            )
        ).all()
        return [_to_task(record, repository) for record, repository in rows]


def _to_task(record: TaskRecord, repository: Repository) -> Task:
    return Task(
        id=record.id,
        repository_url=repository.url,
        instruction=record.instruction,
        status=TaskStatus(record.status),
        created_at=record.created_at,
    )
