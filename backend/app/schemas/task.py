from datetime import datetime
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class TaskCreateRequest(BaseModel):
    repository_url: HttpUrl
    instruction: str = Field(min_length=10, max_length=2000)
    
class TaskResponse(BaseModel):
    task_id: UUID
    status: TaskStatus
    repository_url: str
    instruction: str
    created_at: datetime    
    
class TaskRunResponse(BaseModel):
    task_id: UUID
    status: TaskStatus
    answer: str
    halt_reason: str | None
    iterations: int
    tool_calls: list
    error: str | None