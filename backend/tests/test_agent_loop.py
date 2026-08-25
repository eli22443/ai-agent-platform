from pathlib import Path

import pytest

from app.agent.limits import AgentLimits
from app.agent.loop import run_agent
from app.llm import LLMError
from app.tools.base import ToolContext
from app.tools.registry import build_read_only_registry
from tests.conftest import write_repo_fixture
from tests.llm_fakes import FakeLLMClient, text_response, tool_call_response


def _run(
    *,
    llm: FakeLLMClient,
    workspace: Path,
    limits: AgentLimits | None = None,
):
    return run_agent(
        instruction="Explain the project structure.",
        context=ToolContext(workspace_root=workspace.resolve()),
        registry=build_read_only_registry(),
        llm=llm,
        limits=limits
        or AgentLimits(max_iterations=10, timeout_seconds=60, token_budget=0),
        model="gpt-4.1-mini",
        repository_url="https://github.com/example/repo",
        branch="main",
        head_sha="abc123",
    )


def test_final_text_no_tools(tmp_path: Path):
    workspace = write_repo_fixture(tmp_path / "workspace")
    llm = FakeLLMClient([text_response("The repo has a README.")])

    result = _run(llm=llm, workspace=workspace)

    assert result.completed is True
    assert result.halt_reason is None
    assert result.error is None
    assert result.answer == "The repo has a README."
    assert result.iterations == 1
    assert result.tool_calls == []
    assert llm.calls == 1


def test_one_tool_call_then_final_answer(tmp_path: Path):
    workspace = write_repo_fixture(tmp_path / "workspace")
    llm = FakeLLMClient(
        [
            tool_call_response(),
            text_response("Found README.md and src/."),
        ]
    )

    result = _run(llm=llm, workspace=workspace)

    assert result.completed is True
    assert result.answer == "Found README.md and src/."
    assert result.iterations == 2
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "list_files"
    assert result.tool_calls[0].ok is True
    assert llm.calls == 2
    types = [item.get("type") for item in llm.last_input if isinstance(item, dict)]
    assert "function_call" in types
    assert "function_call_output" in types


def test_tool_ok_false_still_completes(tmp_path: Path):
    workspace = write_repo_fixture(tmp_path / "workspace")
    llm = FakeLLMClient(
        [
            tool_call_response(name="read_file", arguments="{}"),
            text_response("Could not read; path required."),
        ]
    )

    result = _run(llm=llm, workspace=workspace)

    assert result.completed is True
    assert result.tool_calls[0].ok is False
    assert result.error is None


def test_max_iterations_halt(tmp_path: Path):
    workspace = write_repo_fixture(tmp_path / "workspace")
    llm = FakeLLMClient(
        [
            tool_call_response(call_id="c1"),
            tool_call_response(call_id="c2"),
        ]
    )

    result = _run(
        llm=llm,
        workspace=workspace,
        limits=AgentLimits(max_iterations=2, timeout_seconds=60, token_budget=0),
    )

    assert result.completed is False
    assert result.halt_reason == "max_iterations"
    assert result.error is None
    assert result.answer
    assert result.iterations == 2
    assert len(result.tool_calls) == 1


def test_timeout_halt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = write_repo_fixture(tmp_path / "workspace")
    start = 1000.0
    times = iter([start, start + 100])

    def fake_monotonic():
        try:
            return next(times)
        except StopIteration:
            return start + 100

    monkeypatch.setattr("app.agent.limits.time.monotonic", fake_monotonic)
    llm = FakeLLMClient([tool_call_response()])

    result = _run(
        llm=llm,
        workspace=workspace,
        limits=AgentLimits(max_iterations=20, timeout_seconds=10, token_budget=0),
    )

    assert result.completed is False
    assert result.halt_reason == "timeout"
    assert result.error is None


def test_llm_error_sets_error(tmp_path: Path):
    workspace = write_repo_fixture(tmp_path / "workspace")
    llm = FakeLLMClient([LLMError("OpenAI request failed.")])

    result = _run(llm=llm, workspace=workspace)

    assert result.completed is False
    assert result.halt_reason is None
    assert result.error == "OpenAI request failed."
    assert result.iterations == 0
