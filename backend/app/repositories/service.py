from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.repositories.errors import CloneError, InvalidRepositoryUrl
from app.repositories.git_client import GitClient
from app.repositories.inspector import InspectResult, inspect_workspace
from app.repositories.url_validation import validate_clone_url
from app.repositories.workspace import directory_size_bytes, path_for
from app.repositories.workspace import prepare as prepare_workspace
from app.repositories.workspace import remove as remove_workspace

_BYTES_PER_MB = 1024 * 1024


@dataclass(frozen=True)
class PreparedRepository:
    workspace_path: Path
    inspect: InspectResult
    head_sha: str
    current_branch: str | None


class RepositoryService:
    def __init__(
        self,
        git_client: GitClient,
        workspace_root: Path,
        allowed_hosts: tuple[str, ...],
        timeout: int,
        max_size_mb: int,
    ) -> None:
        self._git_client = git_client
        self._workspace_root = workspace_root
        self._allowed_hosts = allowed_hosts
        self._timeout = timeout
        self._max_size_bytes = max_size_mb * _BYTES_PER_MB

    def validate_url(self, url: str) -> None:
        validate_clone_url(url, allowed_hosts=self._allowed_hosts)

    def workspace_path_for(self, task_id: UUID) -> Path:
        return path_for(task_id, self._workspace_root)

    def prepare(self, url: str, task_id: UUID) -> PreparedRepository:
        self.validate_url(url)
        dest = path_for(task_id, self._workspace_root)
        try:
            prepare_workspace(dest)
            self._git_client.clone(url, dest)
            if directory_size_bytes(dest) > self._max_size_bytes:
                raise CloneError("cloned repository exceeds size limit")
            inspect = inspect_workspace(dest)
            return PreparedRepository(
                workspace_path=dest,
                inspect=inspect,
                head_sha=self._git_client.head_sha(dest),
                current_branch=self._git_client.current_branch(dest),
            )
        except InvalidRepositoryUrl:
            remove_workspace(dest)
            raise
        except CloneError:
            remove_workspace(dest)
            raise
        except Exception as exc:
            remove_workspace(dest)
            raise CloneError("failed to prepare repository") from exc
