from pathlib import Path
from uuid import uuid4

from app.tools.base import ToolContext
from app.tools.search import SearchCodeInput, SearchCodeTool, resolve_ripgrep_binary
from tests.conftest import write_repo_fixture


def _context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace.resolve(), task_id=uuid4())


def test_resolve_ripgrep_prefers_system_binary() -> None:
    binary = resolve_ripgrep_binary("rg")
    assert "cursor-server" not in binary
    assert Path(binary).is_file()


def test_search_finds_known_string(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    result = SearchCodeTool().execute(
        _context(workspace),
        SearchCodeInput(query="UNIQUE_FIXTURE_TOKEN"),
    )

    assert result.ok is True
    assert result.truncated is False
    assert len(result.data["matches"]) >= 1
    match = result.data["matches"][0]
    assert match["path"] == "src/main.py"
    assert match["line_number"] == 1
    assert "UNIQUE_FIXTURE_TOKEN" in match["line"]


def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    result = SearchCodeTool().execute(
        _context(workspace),
        SearchCodeInput(query="THIS_STRING_DOES_NOT_EXIST_ANYWHERE"),
    )

    assert result.ok is True
    assert result.data["matches"] == []


def test_search_path_scoped_to_subdirectory(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    (workspace / "other.py").write_text('print("UNIQUE_FIXTURE_TOKEN")\n')

    result = SearchCodeTool().execute(
        _context(workspace),
        SearchCodeInput(query="UNIQUE_FIXTURE_TOKEN", path="src"),
    )

    assert result.ok is True
    paths = {m["path"] for m in result.data["matches"]}
    assert paths == {"src/main.py"}


def test_search_respects_max_results(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    for i in range(5):
        (workspace / f"hit_{i}.txt").write_text(f"NEEDLE_ONLY line {i}\n")

    result = SearchCodeTool(max_results=50).execute(
        _context(workspace),
        SearchCodeInput(query="NEEDLE_ONLY", max_results=2),
    )

    assert result.ok is True
    assert len(result.data["matches"]) == 2
    assert result.truncated is True


def test_search_missing_path(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    result = SearchCodeTool().execute(
        _context(workspace),
        SearchCodeInput(query="x", path="missing"),
    )

    assert result.ok is False
    assert result.error
