from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.repositories.errors import CloneError, InvalidRepositoryUrl
from app.repositories.service import RepositoryService
from tests.conftest import ALLOWED_HOSTS, FakeGitClient, public_getaddrinfo

CLONE_URL = "https://github.com/psf/requests"


def test_fake_prepare_creates_workspace(
    repository_service: RepositoryService, tmp_path: Path
):
    task_id = uuid4()
    result = repository_service.prepare(CLONE_URL, task_id)
    dest = tmp_path / "workspaces" / str(task_id)
    assert result.workspace_path == dest
    assert (dest / "README.md").is_file()
    assert (dest / "src" / "main.py").is_file()
    assert result.head_sha == "abc123def456"
    assert result.current_branch == "main"


def test_inspect_counts_and_languages(repository_service: RepositoryService):
    result = repository_service.prepare(CLONE_URL, uuid4())
    assert result.inspect.file_count == 3
    assert result.inspect.languages == ["Markdown", "Python"]
    assert result.inspect.entry_points == ["README.md"]


def test_prepare_failure_removes_workspace(
    tmp_path: Path, fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("socket.getaddrinfo", public_getaddrinfo)
    workspaces_root = tmp_path / "workspaces"
    service = RepositoryService(
        FakeGitClient(fixture_repo, fail=True),
        workspaces_root,
        ALLOWED_HOSTS,
        timeout=30,
        max_size_mb=200,
    )
    task_id = uuid4()
    with pytest.raises(CloneError):
        service.prepare(CLONE_URL, task_id)
    assert not (workspaces_root / str(task_id)).exists()


def test_size_cap_deletes_workspace(
    tmp_path: Path, fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    (fixture_repo / "blob.bin").write_bytes(b"x" * (2 * 1024 * 1024))
    monkeypatch.setattr("socket.getaddrinfo", public_getaddrinfo)
    workspaces_root = tmp_path / "workspaces"
    service = RepositoryService(
        FakeGitClient(fixture_repo),
        workspaces_root,
        ALLOWED_HOSTS,
        timeout=30,
        max_size_mb=1,
    )
    task_id = uuid4()
    with pytest.raises(CloneError, match="size limit"):
        service.prepare(CLONE_URL, task_id)
    assert not (workspaces_root / str(task_id)).exists()


def test_prepare_rejects_disallowed_url_without_workspace(
    repository_service: RepositoryService, tmp_path: Path
):
    task_id = uuid4()
    with pytest.raises(InvalidRepositoryUrl):
        repository_service.prepare("https://127.0.0.1/secret", task_id)
    assert not (tmp_path / "workspaces" / str(task_id)).exists()
