from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.repositories.git_client import SubprocessGitClient
from app.repositories.service import RepositoryService
from app.services.task_service import TaskService


def get_repository_service() -> RepositoryService:
    settings = get_settings()
    git_client = SubprocessGitClient(
        timeout_seconds=settings.git_clone_timeout_seconds,
        max_repo_size_mb=settings.max_repo_size_mb,
    )
    return RepositoryService(
        git_client,
        settings.workspace_root,
        settings.git_allowed_hosts,
        timeout=settings.git_clone_timeout_seconds,
        max_size_mb=settings.max_repo_size_mb,
    )


def get_task_service(
    db: Session = Depends(get_db),
    repository_service: RepositoryService = Depends(get_repository_service),
) -> TaskService:
    return TaskService(db, repository_service)
