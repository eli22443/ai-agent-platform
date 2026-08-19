"""Optional live clone. Not part of CI.

    RUN_LIVE_GIT=1 uv run pytest tests/test_live_clone.py -v
"""

import os
from uuid import uuid4

import pytest

from app.repositories.git_client import SubprocessGitClient
from app.repositories.service import RepositoryService

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_GIT") != "1",
    reason="optional live clone; set RUN_LIVE_GIT=1 to run",
)


def test_live_clone_public_https_repo(tmp_path):
    dest_root = tmp_path / "workspaces"
    service = RepositoryService(
        SubprocessGitClient(timeout_seconds=120, max_repo_size_mb=200),
        dest_root,
        ("github.com", "gitlab.com", "bitbucket.org"),
        timeout=120,
        max_size_mb=200,
    )
    task_id = uuid4()
    result = service.prepare("https://github.com/psf/requests", task_id)
    workspace = dest_root / str(task_id)
    assert workspace.is_dir()
    assert result.head_sha
    assert (workspace / "README.md").is_file() or (workspace / "README.rst").is_file()
