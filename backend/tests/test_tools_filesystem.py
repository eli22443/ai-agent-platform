from pathlib import Path

from app.tools.base import ToolContext
from app.tools.filesystem import (
    GetFileInfoInput,
    GetFileInfoTool,
    ListFilesInput,
    ListFilesTool,
    ReadFileInput,
    ReadFileTool,
)
from tests.conftest import write_repo_fixture


def _context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace.resolve())


def test_list_files_on_fixture(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    result = ListFilesTool().execute(
        _context(workspace), ListFilesInput(path=".", max_depth=3)
    )

    assert result.ok is True
    assert result.truncated is False
    entries = {(e["path"], e["type"]) for e in result.data["entries"]}
    assert ("README.md", "file") in entries
    assert ("src", "dir") in entries
    assert ("src/main.py", "file") in entries


def test_list_files_respects_ignore_dirs(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("x")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "pkg.js").write_text("x")

    result = ListFilesTool().execute(
        _context(workspace), ListFilesInput(path=".", max_depth=3)
    )

    paths = {e["path"] for e in result.data["entries"]}
    assert ".git" not in paths
    assert "node_modules" not in paths
    assert "node_modules/pkg.js" not in paths


def test_list_files_truncates(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    for i in range(10):
        (workspace / f"f{i}.txt").write_text("x")

    result = ListFilesTool(max_entries=3).execute(
        _context(workspace), ListFilesInput(path=".", max_depth=1)
    )

    assert result.ok is True
    assert result.truncated is True
    assert len(result.data["entries"]) == 3


def test_list_files_missing_path(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    result = ListFilesTool().execute(
        _context(workspace), ListFilesInput(path="missing")
    )

    assert result.ok is False
    assert result.error


def test_read_file_on_fixture(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    result = ReadFileTool().execute(
        _context(workspace), ReadFileInput(path="src/main.py")
    )

    assert result.ok is True
    assert result.truncated is False
    assert "UNIQUE_FIXTURE_TOKEN" in result.data["content"]
    assert result.data["start_line"] == 1
    assert result.data["end_line"] >= 1


def test_read_file_truncation(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    (workspace / "long.txt").write_text("\n".join(f"line-{i}" for i in range(20)))

    result = ReadFileTool(max_bytes=10_000, max_lines=5).execute(
        _context(workspace), ReadFileInput(path="long.txt")
    )

    assert result.ok is True
    assert result.truncated is True
    assert result.data["end_line"] == 5
    assert "line-0" in result.data["content"]
    assert "line-19" not in result.data["content"]


def test_read_file_missing(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    result = ReadFileTool().execute(
        _context(workspace), ReadFileInput(path="nope.py")
    )

    assert result.ok is False
    assert "does not exist" in (result.error or "")


def test_get_file_info_on_fixture(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    result = GetFileInfoTool().execute(
        _context(workspace), GetFileInfoInput(path="src/main.py")
    )

    assert result.ok is True
    assert result.data["exists"] is True
    assert result.data["language"] == "Python"
    assert result.data["size_bytes"] > 0
    assert result.data["line_count"] >= 1
    assert result.data["type"] == "file"


def test_get_file_info_missing(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    result = GetFileInfoTool().execute(
        _context(workspace), GetFileInfoInput(path="missing.py")
    )

    assert result.ok is True
    assert result.data["exists"] is False
