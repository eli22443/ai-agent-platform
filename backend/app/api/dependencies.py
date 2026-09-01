from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.repositories.git_client import SubprocessGitClient
from app.repositories.service import RepositoryService
from app.services.agent_run_service import AgentRunService
from app.services.task_service import TaskService

from app.agent.limits import AgentLimits
from app.llm.client import OpenAILLMClient
from app.tools.registry import ToolRegistry, build_read_only_registry


def get_repository_service() -> RepositoryService:
    settings = get_settings()
    git_client = SubprocessGitClient(
        timeout_seconds=settings.git_clone_timeout_seconds,
        max_repo_size_mb=settings.max_repo_size_mb,
    )
    return RepositoryService(
        git_client,
        settings.workspaces_root,
        settings.git_allowed_hosts,
        timeout=settings.git_clone_timeout_seconds,
        max_size_mb=settings.max_repo_size_mb,
    )


def get_agent_run_service(db: Session = Depends(get_db)) -> AgentRunService:
    return AgentRunService(db)


def get_task_service(
    db: Session = Depends(get_db),
    repository_service: RepositoryService = Depends(get_repository_service),
    agent_run_service: AgentRunService = Depends(get_agent_run_service),
) -> TaskService:
    return TaskService(db, repository_service, agent_run_service)


def get_llm_client() -> OpenAILLMClient:
    settings = get_settings()
    return OpenAILLMClient(
        api_key=settings.openai_api_key,
        max_output_tokens=settings.agent_max_output_tokens or None,
    )


def get_tool_registry() -> ToolRegistry:
    return build_read_only_registry()


def get_agent_limits() -> AgentLimits:
    settings = get_settings()
    return AgentLimits(
        max_iterations=settings.agent_max_iterations,
        timeout_seconds=settings.agent_timeout_seconds,
        token_budget=settings.agent_token_budget,
    )
