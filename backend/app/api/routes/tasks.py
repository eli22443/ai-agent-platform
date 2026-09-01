import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.agent.types import AgentResult
from app.api.dependencies import (
    get_agent_run_service,
    get_llm_client,
    get_task_service,
    get_tool_registry,
)
from app.database.models import AgentRunRecord, ToolCallRecord
from app.llm.client import OpenAILLMClient
from app.repositories.errors import CloneError, InvalidRepositoryUrl
from app.schemas.agent_run import (
    AgentRunDetailResponse,
    AgentRunSummaryResponse,
    AgentRunToolCallResponse,
)
from app.schemas.task import (
    TaskCreateRequest,
    TaskResponse,
    TaskRunResponse,
    TaskStatus,
    ToolCallSummaryResponse,
)
from app.services.agent_run_service import AgentRunService
from app.services.errors import TaskNotFound, TaskNotRunnable
from app.services.task_service import Task, TaskService
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
    try:
        agent_result = service.run(task_id, llm, registry)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="Task not found.")
    except TaskNotRunnable as exc:
        raise HTTPException(status_code=409, detail=exc.message)

    return _to_task_run_response(task_id, agent_result)


@router.get("/tasks/{task_id}/runs", response_model=list[AgentRunSummaryResponse])
def list_task_runs(
    task_id: UUID,
    task_service: TaskService = Depends(get_task_service),
    agent_run_service: AgentRunService = Depends(get_agent_run_service),
) -> list[AgentRunSummaryResponse]:
    if task_service.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    runs = agent_run_service.list_for_task(task_id)
    return [
        _to_run_summary(run, agent_run_service.tool_call_count(run.id)) for run in runs
    ]


@router.get(
    "/tasks/{task_id}/runs/{run_id}",
    response_model=AgentRunDetailResponse,
)
def get_task_run(
    task_id: UUID,
    run_id: UUID,
    task_service: TaskService = Depends(get_task_service),
    agent_run_service: AgentRunService = Depends(get_agent_run_service),
) -> AgentRunDetailResponse:
    if task_service.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    run = agent_run_service.get_for_task(task_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return _to_run_detail(run)


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
        result=task.result,
        error=task.error,
    )


def _to_task_run_response(task_id: UUID, agent_result: AgentResult) -> TaskRunResponse:
    if agent_result.error:
        status = TaskStatus.FAILED
    else:
        status = TaskStatus.COMPLETED
    return TaskRunResponse(
        task_id=task_id,
        status=status,
        answer=agent_result.answer,
        halt_reason=agent_result.halt_reason,
        iterations=agent_result.iterations,
        tool_calls=[
            ToolCallSummaryResponse(
                name=call.name, args=call.args, ok=call.ok, duration_ms=call.duration_ms
            )
            for call in agent_result.tool_calls
        ],
        error=agent_result.error,
        run_id=agent_result.run_id,
    )


def _to_run_summary(run: AgentRunRecord, tool_call_count: int) -> AgentRunSummaryResponse:
    return AgentRunSummaryResponse(
        run_id=run.id,
        status=run.status,
        model=run.model,
        iterations=run.iterations,
        halt_reason=run.halt_reason,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        total_tokens=run.total_tokens,
        started_at=run.started_at,
        finished_at=run.finished_at,
        tool_call_count=tool_call_count,
    )


def _to_run_detail(run: AgentRunRecord) -> AgentRunDetailResponse:
    tool_calls = list(run.tool_calls)
    return AgentRunDetailResponse(
        run_id=run.id,
        status=run.status,
        model=run.model,
        iterations=run.iterations,
        halt_reason=run.halt_reason,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        total_tokens=run.total_tokens,
        started_at=run.started_at,
        finished_at=run.finished_at,
        tool_call_count=len(tool_calls),
        result=run.result,
        error=run.error,
        tool_calls=[_to_tool_call_response(call) for call in tool_calls],
    )


def _to_tool_call_response(call: ToolCallRecord) -> AgentRunToolCallResponse:
    return AgentRunToolCallResponse(
        sequence=call.sequence,
        name=call.tool_name,
        args=json.dumps(call.arguments, ensure_ascii=False, default=str),
        ok=call.ok,
        duration_ms=call.duration_ms,
        error=call.error,
        deduplicated=call.deduplicated,
    )
