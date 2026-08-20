from pathlib import Path

import pytest

from app.tools.paths import WorkspacePathError, resolve_workspace_path
from tests.conftest import write_repo_fixture


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return write_repo_fixture(tmp_path / "workspace")


def test_resolves_valid_relative_path(workspace: Path) -> None:
    resolved = resolve_workspace_path(workspace, "src/main.py")

    assert resolved == (workspace / "src" / "main.py").resolve()
    assert resolved.is_file()


def test_rejects_empty_path(workspace: Path) -> None:
    with pytest.raises(WorkspacePathError, match="empty"):
        resolve_workspace_path(workspace, "")


def test_rejects_whitespace_only_path(workspace: Path) -> None:
    with pytest.raises(WorkspacePathError, match="empty"):
        resolve_workspace_path(workspace, "   ")


def test_rejects_parent_traversal(workspace: Path) -> None:
    with pytest.raises(WorkspacePathError, match="traversal"):
        resolve_workspace_path(workspace, "../outside.txt")


def test_rejects_absolute_unix_path(workspace: Path) -> None:
    with pytest.raises(WorkspacePathError, match="absolute"):
        resolve_workspace_path(workspace, "/etc/passwd")


def test_rejects_absolute_windows_path(workspace: Path) -> None:
    with pytest.raises(WorkspacePathError, match="absolute"):
        resolve_workspace_path(workspace, r"C:\Windows\System32")


def test_rejects_symlink_escaping_workspace(
    workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    evil_link = workspace / "evil_link"
    evil_link.symlink_to(outside)

    with pytest.raises(WorkspacePathError, match="escapes"):
        resolve_workspace_path(workspace, "evil_link")


def test_must_exist_rejects_missing_path(workspace: Path) -> None:
    with pytest.raises(WorkspacePathError, match="does not exist"):
        resolve_workspace_path(workspace, "src/missing.py", must_exist=True)


def test_missing_path_allowed_when_must_exist_false(workspace: Path) -> None:
    resolved = resolve_workspace_path(workspace, "src/missing.py")

    assert resolved == (workspace / "src" / "missing.py").resolve()
    assert not resolved.exists()
