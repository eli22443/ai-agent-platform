from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_llm_client, get_task_service, get_tool_registry
from app.repositories.errors import CloneError, InvalidRepositoryUrl
from app.schemas.task import (
    TaskCreateRequest,
    TaskResponse,
    TaskRunResponse,
    TaskStatus,
)
from app.services.task_service import Task, TaskService

from app.agent.types import AgentResult
from app.llm.client import OpenAILLMClient
from app.tools.registry import ToolRegistry

router = APIRouter(tags=["tasks"])


@router.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(
    payload: TaskCreateRequest, service: TaskService = Depends(get_task_service)
) -> TaskResponse:
    try:
        task = service.create(str(payload.repository_url), payload.instruction)
    except InvalidRepositoryUrl:
        raise HTTPException(status_code=400, detail="Repository URL is not allowed.")
    except CloneError:
        raise HTTPException(status_code=502, detail="Failed to clone repository.")
    return _to_task_response(task)


@router.post("/tasks/{task_id}/run", response_model=TaskRunResponse)
def run_task(
    task_id: UUID,
    service: TaskService = Depends(get_task_service),
    llm: OpenAILLMClient = Depends(get_llm_client),
    registry: ToolRegistry = Depends(get_tool_registry),
) -> TaskRunResponse:
    agent_result = service.run(task_id, llm, registry)

    return _to_task_run_response(task_id, agent_result)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: UUID,
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return _to_task_response(task)


@router.get("/tasks", response_model=list[TaskResponse])
def list_tasks(
    service: TaskService = Depends(get_task_service),
) -> list[TaskResponse]:
    return [_to_task_response(task) for task in service.list_all()]


def _to_task_response(task: Task) -> TaskResponse:
    return TaskResponse(
        task_id=task.id,
        status=task.status,
        repository_url=task.repository_url,
        instruction=task.instruction,
        created_at=task.created_at,
    )


def _to_task_run_response(task_id: UUID, agent_result: AgentResult) -> TaskRunResponse:
    return TaskRunResponse(
        task_id=task_id,
        status=TaskStatus.COMPLETED if agent_result.completed else TaskStatus.FAILED,
        answer=agent_result.answer,
        halt_reason=agent_result.halt_reason,
        iterations=agent_result.iterations,
        tool_calls=agent_result.tool_calls,
        error=agent_result.error,
    )
