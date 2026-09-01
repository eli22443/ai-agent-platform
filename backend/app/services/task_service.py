from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.limits import AgentLimits
from app.agent.loop import run_agent
from app.agent.types import AgentResult
from app.config import get_settings
from app.database.models import RepositoryRecord, TaskRecord
from app.llm import OpenAILLMClient
from app.repositories.errors import CloneError
from app.repositories.service import RepositoryService
from app.repositories.workspace import remove as remove_workspace
from app.schemas.task import TaskStatus
from app.services.agent_run_service import AgentRunService
from app.services.errors import TaskNotFound, TaskNotRunnable
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry


@dataclass
class Task:
    id: UUID
    repository_url: str
    instruction: str
    status: TaskStatus
    created_at: datetime
    result: str | None = None
    error: str | None = None


class TaskService:
    def __init__(
        self,
        session: Session,
        repository_service: RepositoryService,
        agent_run_service: AgentRunService,
    ) -> None:
        self._session = session
        self._repository_service = repository_service
        self._agent_run_service = agent_run_service

    def create(self, repository_url: str, instruction: str) -> Task:
        self._repository_service.validate_url(repository_url)

        repository_record = self._session.scalars(
            select(RepositoryRecord).where(RepositoryRecord.url == repository_url)
        ).first()
        if repository_record is None:
            repository_record = RepositoryRecord(url=repository_url)
            self._session.add(repository_record)
            self._session.flush()

        now = datetime.now(UTC)
        record = TaskRecord(
            repository_id=repository_record.id,
            instruction=instruction,
            status=TaskStatus.PENDING.value,
            created_at=now,
            updated_at=now,
        )
        self._session.add(record)
        self._session.flush()

        try:
            prepared = self._repository_service.prepare(repository_url, record.id)
        except CloneError as exc:
            record.status = TaskStatus.FAILED.value
            record.error = str(exc)
            record.updated_at = datetime.now(UTC)
            self._session.flush()
            remove_workspace(self._repository_service.workspace_path_for(record.id))
            self._session.commit()
            raise

        repository_record.default_branch = prepared.current_branch
        repository_record.last_commit_sha = prepared.head_sha
        self._session.flush()
        return _to_task(record, repository_record)

    def get(self, task_id: UUID) -> Task | None:
        row = self._session.execute(
            select(TaskRecord, RepositoryRecord)
            .join(RepositoryRecord, TaskRecord.repository_id == RepositoryRecord.id)
            .where(TaskRecord.id == task_id)
        ).first()
        if row is None:
            return None
        record, repository_record = row
        return _to_task(record, repository_record)

    def list_all(self) -> list[Task]:
        rows = self._session.execute(
            select(TaskRecord, RepositoryRecord).join(
                RepositoryRecord, TaskRecord.repository_id == RepositoryRecord.id
            )
        ).all()
        return [
            _to_task(record, repository_record) for record, repository_record in rows
        ]

    def run(
        self, task_id: UUID, llm: OpenAILLMClient, registry: ToolRegistry
    ) -> AgentResult:
        row = self._session.execute(
            select(TaskRecord, RepositoryRecord)
            .join(RepositoryRecord, TaskRecord.repository_id == RepositoryRecord.id)
            .where(TaskRecord.id == task_id)
        ).first()
        if row is None:
            raise TaskNotFound()

        task_record, repository_record = row

        if task_record.status != TaskStatus.PENDING.value:
            raise TaskNotRunnable(f"task is not runnable (status={task_record.status})")

        workspace_root = self._repository_service.workspace_path_for(task_id)
        if not workspace_root.is_dir():
            raise TaskNotRunnable("workspace missing or incomplete")

        settings = get_settings()
        now = datetime.now(UTC)
        task_record.status = TaskStatus.RUNNING.value
        task_record.updated_at = now
        run_record = self._agent_run_service.begin(task_id, model=settings.openai_model)
        # Commit early so other DB clients can observe running mid-flight.
        # Final completed/failed still commits via get_db after the route returns.
        self._session.commit()

        agent_result = run_agent(
            instruction=task_record.instruction,
            context=ToolContext(workspace_root=workspace_root.resolve()),
            registry=registry,
            llm=llm,
            limits=AgentLimits(
                max_iterations=settings.agent_max_iterations,
                timeout_seconds=settings.agent_timeout_seconds,
                token_budget=settings.agent_token_budget,
            ),
            model=settings.openai_model,
            repository_url=repository_record.url,
            branch=repository_record.default_branch,
            head_sha=repository_record.last_commit_sha,
        )

        now = datetime.now(UTC)
        if agent_result.error:
            task_record.status = TaskStatus.FAILED.value
            task_record.error = agent_result.error
            task_record.result = None
        else:
            # Success and limit-halt both land as completed.
            task_record.status = TaskStatus.COMPLETED.value
            answer = agent_result.answer
            if agent_result.halt_reason:
                answer = f"[halted: {agent_result.halt_reason}]\n{answer}"
            task_record.result = answer
            task_record.error = None

        task_record.updated_at = now
        self._agent_run_service.finish(run_record, agent_result)
        self._session.flush()
        agent_result.run_id = run_record.id
        return agent_result


def _to_task(record: TaskRecord, repository_record: RepositoryRecord) -> Task:
    return Task(
        id=record.id,
        repository_url=repository_record.url,
        instruction=record.instruction,
        status=TaskStatus(record.status),
        created_at=record.created_at,
        result=record.result,
        error=record.error,
    )
