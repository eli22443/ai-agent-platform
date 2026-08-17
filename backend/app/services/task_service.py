"""In-memory task store.

Storage is a process-local dictionary. It is lost on restart and is not
shared across workers. Phase 3 replaces this with PostgreSQL.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.schemas.task import TaskStatus


@dataclass
class Task:
    id: UUID
    repository_url: str
    instruction: str
    status: TaskStatus
    created_at: datetime
    
class TaskService:
    def __init__(self) -> None:
        self._tasks: dict[UUID, Task] = {}
        
    def create(self, repository_url: str, instruction: str) -> Task:
        task = Task(
            id=uuid4(),
            repository_url=repository_url,
            instruction=instruction,
            status=TaskStatus.PENDING,
            created_at=datetime.now(UTC)
        )
        self._tasks[task.id] = task
        return task
    
    def get(self, task_id: UUID) -> Task | None:
        return self._tasks.get(task_id)
    
    def list_all(self) -> list[Task]:
        return list(self._tasks.values())