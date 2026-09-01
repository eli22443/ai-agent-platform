import json
from pathlib import Path
from types import SimpleNamespace

from app.agent.dispatch import (
    DispatchCache,
    dispatch_tool_calls,
    extract_function_calls,
)
from app.tools.base import ToolContext
from app.tools.registry import build_read_only_registry
from tests.conftest import write_repo_fixture


def _call(
    *,
    name: str,
    arguments: str,
    call_id: str = "call_1",
) -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=arguments,
    )


def test_extract_function_calls_filters_output() -> None:
    items = [
        SimpleNamespace(type="message"),
        _call(name="list_files", arguments="{}"),
        SimpleNamespace(type="reasoning"),
    ]
    calls = extract_function_calls(items)
    assert len(calls) == 1
    assert calls[0].name == "list_files"


def test_dispatch_valid_list_files(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    call = _call(name="list_files", arguments='{"path": "."}')

    result = dispatch_tool_calls(
        [call],
        registry=registry,
        context=ToolContext(workspace_root=workspace.resolve()),
    )

    assert len(result.output_items) == 1
    assert len(result.summaries) == 1
    item = result.output_items[0]
    assert item["type"] == "function_call_output"
    assert item["call_id"] == "call_1"
    payload = json.loads(item["output"])
    assert payload["ok"] is True
    assert result.summaries[0].name == "list_files"
    assert result.summaries[0].ok is True
    assert result.summaries[0].error is None
    assert result.summaries[0].deduplicated is False
    assert result.summaries[0].duration_ms >= 0


def test_dispatch_invalid_json_returns_error_output(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    call = _call(name="list_files", arguments="{not-json")

    result = dispatch_tool_calls(
        [call],
        registry=registry,
        context=ToolContext(workspace_root=workspace.resolve()),
    )

    payload = json.loads(result.output_items[0]["output"])
    assert payload["ok"] is False
    assert "invalid tool arguments JSON" in payload["error"]
    assert result.summaries[0].ok is False
    assert result.summaries[0].error is not None


def test_dispatch_unknown_tool_returns_error(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    call = _call(name="no_such_tool", arguments="{}")

    result = dispatch_tool_calls(
        [call],
        registry=registry,
        context=ToolContext(workspace_root=workspace.resolve()),
    )

    payload = json.loads(result.output_items[0]["output"])
    assert payload["ok"] is False
    assert "unknown tool" in payload["error"]
    assert result.summaries[0].ok is False


def test_dispatch_tool_ok_false_still_returns_output(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    call = _call(name="read_file", arguments="{}")  # path required

    result = dispatch_tool_calls(
        [call],
        registry=registry,
        context=ToolContext(workspace_root=workspace.resolve()),
    )

    payload = json.loads(result.output_items[0]["output"])
    assert payload["ok"] is False
    assert payload["error"]
    assert len(result.output_items) == 1


def test_dispatch_dedupes_exact_repeat(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    context = ToolContext(workspace_root=workspace.resolve())
    cache = DispatchCache()
    args = '{"path": "src/main.py", "start_line": 1}'

    first = dispatch_tool_calls(
        [_call(name="read_file", arguments=args, call_id="c1")],
        registry=registry,
        context=context,
        cache=cache,
    )
    second = dispatch_tool_calls(
        [_call(name="read_file", arguments=args, call_id="c2")],
        registry=registry,
        context=context,
        cache=cache,
    )

    first_payload = json.loads(first.output_items[0]["output"])
    second_payload = json.loads(second.output_items[0]["output"])
    assert first_payload["ok"] is True
    assert "UNIQUE_FIXTURE_TOKEN" in first_payload["data"]["content"]
    assert second_payload["ok"] is True
    assert second_payload["data"]["deduplicated"] is True
    assert "already ran" in second_payload["data"]["message"]
    assert first.summaries[0].deduplicated is False
    assert second.summaries[0].deduplicated is True


def test_dispatch_dedupes_near_duplicate_read_window(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    (workspace / "long.txt").write_text("\n".join(f"line-{i}" for i in range(100)))
    registry = build_read_only_registry()
    context = ToolContext(workspace_root=workspace.resolve())
    cache = DispatchCache()

    first = dispatch_tool_calls(
        [
            _call(
                name="read_file",
                arguments='{"path": "long.txt", "start_line": 1}',
                call_id="c1",
            )
        ],
        registry=registry,
        context=context,
        cache=cache,
    )
    near = dispatch_tool_calls(
        [
            _call(
                name="read_file",
                arguments='{"path": "long.txt", "start_line": 20}',
                call_id="c2",
            )
        ],
        registry=registry,
        context=context,
        cache=cache,
    )
    far = dispatch_tool_calls(
        [
            _call(
                name="read_file",
                arguments='{"path": "long.txt", "start_line": 80}',
                call_id="c3",
            )
        ],
        registry=registry,
        context=context,
        cache=cache,
    )

    assert json.loads(first.output_items[0]["output"])["ok"] is True
    near_payload = json.loads(near.output_items[0]["output"])
    assert near_payload["data"]["deduplicated"] is True
    far_payload = json.loads(far.output_items[0]["output"])
    assert far_payload["ok"] is True
    assert not far_payload["data"].get("deduplicated")
    assert "line-79" in far_payload["data"]["content"]


def test_dispatch_dedupes_failed_search_retry(tmp_path: Path) -> None:
    workspace = write_repo_fixture(tmp_path / "workspace")
    registry = build_read_only_registry()
    context = ToolContext(workspace_root=workspace.resolve())
    cache = DispatchCache()
    args = '{"query": "cookie", "path": "requests"}'

    first = dispatch_tool_calls(
        [_call(name="search_code", arguments=args, call_id="c1")],
        registry=registry,
        context=context,
        cache=cache,
    )
    second = dispatch_tool_calls(
        [_call(name="search_code", arguments=args, call_id="c2")],
        registry=registry,
        context=context,
        cache=cache,
    )

    first_payload = json.loads(first.output_items[0]["output"])
    second_payload = json.loads(second.output_items[0]["output"])
    assert first_payload["ok"] is False
    assert second_payload["data"]["deduplicated"] is True
    assert "Prior error" in second_payload["data"]["message"]
