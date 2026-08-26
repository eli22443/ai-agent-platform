from pathlib import Path

from app.tools.base import ToolContext
from app.tools.registry import build_read_only_registry
from tests.conftest import write_repo_fixture

_EXPECTED_TOOLS = {
    "list_files",
    "read_file",
    "get_file_info",
    "search_code",
    "get_git_diff",
    "get_git_history",
}


def test_list_schemas_has_six_tools() -> None:
    registry = build_read_only_registry()
    schemas = registry.list_schemas()

    assert len(schemas) == 6
    names = {schema["name"] for schema in schemas}
    assert names == _EXPECTED_TOOLS
    for schema in schemas:
        assert schema["type"] == "function"
        assert isinstance(schema["description"], str)
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"
        assert schema["parameters"]["additionalProperties"] is False


def test_get_known_and_unknown_tool() -> None:
    registry = build_read_only_registry()

    assert registry.get("read_file") is not None
    assert registry.get("read_file").name == "read_file"
    assert registry.get("no_such_tool") is None


def test_execute_unknown_tool_returns_error(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    result = registry.execute(
        "no_such_tool",
        ToolContext(workspace_root=workspace.resolve()),
        {},
    )

    assert result.ok is False
    assert "unknown tool" in (result.error or "")


def test_execute_invalid_args_returns_error_without_raise(
    tmp_path: Path,
) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    result = registry.execute(
        "read_file",
        ToolContext(workspace_root=workspace.resolve()),
        {},  # path is required
    )

    assert result.ok is False
    assert result.error
    assert "invalid arguments" in result.error


def test_execute_empty_path_returns_validation_error(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    context = ToolContext(workspace_root=workspace.resolve())

    for name, arguments in (
        ("list_files", {"path": ""}),
        ("search_code", {"query": "cookie", "path": ""}),
        ("read_file", {"path": ""}),
        ("get_file_info", {"path": ""}),
    ):
        result = registry.execute(name, context, arguments)
        assert result.ok is False, name
        assert "invalid arguments" in (result.error or ""), name


def test_execute_valid_read_file(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    result = registry.execute(
        "read_file",
        ToolContext(workspace_root=workspace.resolve()),
        {"path": "src/main.py"},
    )

    assert result.ok is True
    assert "UNIQUE_FIXTURE_TOKEN" in result.data["content"]
