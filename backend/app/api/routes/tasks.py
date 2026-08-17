from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from app.schemas.task import TaskCreateRequest, TaskResponse
from app.services.task_service import Task, TaskService
from app.api.dependencies import get_task_service


router = APIRouter(tags=["tasks"])

@router.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(
    payload: TaskCreateRequest,
    service: TaskService = Depends(get_task_service)
) -> TaskResponse:
    task = service.create(str(payload.repository_url), payload.instruction)
    return _to_response(task)
    
    
@router.get("/tasks", response_model=list[TaskResponse])
def list_tasks(
    service: TaskService = Depends(get_task_service),
) -> list[TaskResponse]:
    return [_to_response(task) for task in service.list_all()]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: UUID,
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return _to_response(task)


def _to_response(task: Task) -> TaskResponse:
    return TaskResponse(
        task_id=task.id,
        status=task.status,
        repository_url=task.repository_url,
        instruction=task.instruction,
        created_at=task.created_at
    )