from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

from app.tools.base import ToolContext
from app.tools.git import (
    GetGitDiffInput,
    GetGitDiffTool,
    GetGitHistoryInput,
    GetGitHistoryTool,
)
from tests.conftest import init_git_repo


def _context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace.resolve(), task_id=uuid4())


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        check=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_get_git_history_returns_commits(tmp_path: Path) -> None:
    workspace = init_git_repo(tmp_path / "workspace")
    result = GetGitHistoryTool().execute(
        _context(workspace), GetGitHistoryInput()
    )

    assert result.ok is True
    assert len(result.data["commits"]) >= 1
    assert result.data["commits"][0]["commit"]
    assert "initial commit" in result.data["commits"][0]["message"]


def test_get_git_history_path_scoped(tmp_path: Path) -> None:
    workspace = init_git_repo(tmp_path / "workspace")
    (workspace / "src" / "main.py").write_text(
        'print("UNIQUE_FIXTURE_TOKEN")\n# touched\n'
    )
    _git(workspace, "add", "src/main.py")
    _git(workspace, "commit", "-m", "touch main only")

    result = GetGitHistoryTool().execute(
        _context(workspace),
        GetGitHistoryInput(path="src/main.py", limit=10),
    )

    assert result.ok is True
    messages = [c["message"] for c in result.data["commits"]]
    assert "touch main only" in messages
    assert "initial commit" in messages

    utils_only = GetGitHistoryTool().execute(
        _context(workspace),
        GetGitHistoryInput(path="src/utils.py", limit=10),
    )
    utils_messages = [c["message"] for c in utils_only.data["commits"]]
    assert "touch main only" not in utils_messages
    assert "initial commit" in utils_messages


def test_get_git_diff_returns_string(tmp_path: Path) -> None:
    workspace = init_git_repo(tmp_path / "workspace")
    result = GetGitDiffTool().execute(_context(workspace), GetGitDiffInput())

    assert result.ok is True
    assert isinstance(result.data["diff"], str)
    assert result.data["diff"] == ""

    (workspace / "README.md").write_text("# demo\nchanged\n")
    dirty = GetGitDiffTool().execute(_context(workspace), GetGitDiffInput())

    assert dirty.ok is True
    assert isinstance(dirty.data["diff"], str)
    assert dirty.data["diff"] != ""
    assert "changed" in dirty.data["diff"]


def test_get_git_diff_path_scoped(tmp_path: Path) -> None:
    workspace = init_git_repo(tmp_path / "workspace")
    (workspace / "README.md").write_text("# demo\nreadme change\n")
    (workspace / "src" / "utils.py").write_text(
        "def helper():\n    return 2\n"
    )

    result = GetGitDiffTool().execute(
        _context(workspace), GetGitDiffInput(path="README.md")
    )

    assert result.ok is True
    assert "readme change" in result.data["diff"]
    assert "return 2" not in result.data["diff"]


def test_get_git_diff_truncates(tmp_path: Path) -> None:
    workspace = init_git_repo(tmp_path / "workspace")
    (workspace / "big.txt").write_text("x" * 5000)
    _git(workspace, "add", "big.txt")
    # Untracked won't show in diff; commit then modify.
    _git(workspace, "commit", "-m", "add big")
    (workspace / "big.txt").write_text("y" * 5000)

    result = GetGitDiffTool(max_bytes=100).execute(
        _context(workspace), GetGitDiffInput(path="big.txt")
    )

    assert result.ok is True
    assert result.truncated is True
    assert len(result.data["diff"].encode("utf-8")) <= 100


def test_get_git_history_missing_path(tmp_path: Path) -> None:
    workspace = init_git_repo(tmp_path / "workspace")
    result = GetGitHistoryTool().execute(
        _context(workspace), GetGitHistoryInput(path="nope.py")
    )

    assert result.ok is False
    assert result.error
