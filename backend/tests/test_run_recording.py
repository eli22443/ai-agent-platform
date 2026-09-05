"""Integration tests for agent run and tool call persistence."""

from __future__ import annotations

import pytest
from uuid import uuid4
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.models import AgentRunRecord, ToolCallRecord
from app.llm import LLMError
from app.repositories.service import RepositoryService
from app.services.agent_run_service import AgentRunService
from app.services.task_service import TaskService
from app.tools.registry import build_read_only_registry
from tests.llm_fakes import FakeLLMClient, text_response, tool_call_response

REQUESTS_URL = "https://github.com/psf/requests"
INSTRUCTION = "Explain how the Session object is used for HTTP requests."


@pytest.fixture
def task_service(db_session: Session, repository_service: RepositoryService):
    return TaskService(
        db_session, repository_service, AgentRunService(db_session)
    )


def test_truncate_includes_tool_calls(engine: Engine):
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'tool_calls'"
            )
        ).all()
    assert rows


def test_completed_run_persists_tokens_and_no_tool_calls(
    db_session: Session, task_service: TaskService
):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    result = task_service.process(
        task.id,
        FakeLLMClient([text_response("Session handles cookies.")]),
        build_read_only_registry(),
    )

    assert result.run_id is not None
    run = db_session.get(AgentRunRecord, result.run_id)
    assert run is not None
    assert run.task_id == task.id
    assert run.status == "completed"
    assert run.model == get_settings().openai_model
    assert run.iterations == 1
    assert run.halt_reason is None
    assert run.error is None
    assert run.result == "Session handles cookies."
    assert run.started_at is not None
    assert run.finished_at is not None
    assert run.prompt_tokens == 6
    assert run.completion_tokens == 4
    assert run.total_tokens == 10

    tool_calls = db_session.scalars(
        select(ToolCallRecord).where(ToolCallRecord.agent_run_id == run.id)
    ).all()
    assert tool_calls == []


def test_tool_calls_persisted_in_order(
    db_session: Session, task_service: TaskService
):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    result = task_service.process(
        task.id,
        FakeLLMClient(
            [
                tool_call_response(),
                text_response("Found README."),
            ]
        ),
        build_read_only_registry(),
    )

    run = db_session.get(AgentRunRecord, result.run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.total_tokens == 30  # 20 + 10

    calls = list(
        db_session.scalars(
            select(ToolCallRecord)
            .where(ToolCallRecord.agent_run_id == run.id)
            .order_by(ToolCallRecord.sequence)
        ).all()
    )
    assert len(calls) == 1
    assert calls[0].sequence == 1
    assert calls[0].tool_name == "list_files"
    assert calls[0].arguments == {"path": "."}
    assert calls[0].ok is True
    assert calls[0].error is None
    assert calls[0].deduplicated is False
    assert calls[0].duration_ms >= 0


def test_halted_run_persists_status_and_tool_calls(
    db_session: Session, task_service: TaskService, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "2")
    get_settings.cache_clear()
    try:
        task = task_service.create(REQUESTS_URL, INSTRUCTION)
        result = task_service.process(
            task.id,
            FakeLLMClient(
                [
                    tool_call_response(call_id="c1"),
                    tool_call_response(call_id="c2"),
                ]
            ),
            build_read_only_registry(),
        )

        assert result.halt_reason == "max_iterations"
        run = db_session.get(AgentRunRecord, result.run_id)
        assert run is not None
        assert run.status == "halted"
        assert run.halt_reason == "max_iterations"
        assert run.error is None

        calls = db_session.scalars(
            select(ToolCallRecord).where(ToolCallRecord.agent_run_id == run.id)
        ).all()
        # First tool call dispatches; second response hits the iteration cap first.
        assert len(calls) == 1
    finally:
        get_settings.cache_clear()


def test_failed_run_persists_error(
    db_session: Session, task_service: TaskService
):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    result = task_service.process(
        task.id,
        FakeLLMClient([LLMError("OpenAI request failed.")]),
        build_read_only_registry(),
    )

    assert result.error == "OpenAI request failed."
    run = db_session.get(AgentRunRecord, result.run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.error == "OpenAI request failed."
    assert run.halt_reason is None
    assert run.finished_at is not None


def test_deduplicated_tool_call_flag(
    db_session: Session, task_service: TaskService
):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    args = '{"path": "."}'
    result = task_service.process(
        task.id,
        FakeLLMClient(
            [
                tool_call_response(call_id="c1", arguments=args),
                tool_call_response(call_id="c2", arguments=args),
                text_response("Listed once."),
            ]
        ),
        build_read_only_registry(),
    )

    calls = list(
        db_session.scalars(
            select(ToolCallRecord)
            .where(ToolCallRecord.agent_run_id == result.run_id)
            .order_by(ToolCallRecord.sequence)
        ).all()
    )
    assert len(calls) == 2
    assert calls[0].deduplicated is False
    assert calls[0].ok is True
    assert calls[1].deduplicated is True
    assert calls[1].ok is True


def test_failed_tool_call_stores_error(
    db_session: Session, task_service: TaskService
):
    task = task_service.create(REQUESTS_URL, INSTRUCTION)
    result = task_service.process(
        task.id,
        FakeLLMClient(
            [
                tool_call_response(name="read_file", arguments="{}"),
                text_response("Path required."),
            ]
        ),
        build_read_only_registry(),
    )

    call = db_session.scalars(
        select(ToolCallRecord).where(ToolCallRecord.agent_run_id == result.run_id)
    ).one()
    assert call.ok is False
    assert call.error


def test_get_runs_api(client):
    from app.api.dependencies import get_llm_client
    from tests.test_tasks_run_api import _prepare_workspace

    fake = FakeLLMClient(
        [
            tool_call_response(),
            text_response("Done."),
        ]
    )
    client.app.dependency_overrides[get_llm_client] = lambda: fake
    try:
        task_id = client.post(
            "/tasks",
            json={"repository_url": REQUESTS_URL, "instruction": INSTRUCTION},
        ).json()["task_id"]
        _prepare_workspace(client, task_id, REQUESTS_URL)

        empty = client.get(f"/tasks/{task_id}/runs")
        assert empty.status_code == 200
        assert empty.json() == []

        run_body = client.post(f"/tasks/{task_id}/run").json()
        run_id = run_body["run_id"]

        listed = client.get(f"/tasks/{task_id}/runs")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        summary = listed.json()[0]
        assert summary["run_id"] == run_id
        assert summary["status"] == "completed"
        assert summary["tool_call_count"] == 1

        detail = client.get(f"/tasks/{task_id}/runs/{run_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["result"] == "Done."
        assert body["error"] is None
        assert len(body["tool_calls"]) == 1
        assert body["tool_calls"][0]["sequence"] == 1
        assert body["tool_calls"][0]["deduplicated"] is False

        missing = client.get(
            f"/tasks/{task_id}/runs/00000000-0000-0000-0000-000000000000"
        )
        assert missing.status_code == 404
    finally:
        client.app.dependency_overrides.pop(get_llm_client, None)


def test_token_fields_on_agent_result(tmp_path):
    from app.agent.limits import AgentLimits
    from app.agent.loop import run_agent
    from app.tools.base import ToolContext
    from tests.conftest import write_repo_fixture

    workspace = write_repo_fixture(tmp_path / "workspace")
    llm = FakeLLMClient([text_response("ok")])
    result = run_agent(
        instruction="Explain the project.",
        context=ToolContext(workspace_root=workspace.resolve(), task_id=uuid4()),
        registry=build_read_only_registry(),
        llm=llm,
        limits=AgentLimits(max_iterations=5, timeout_seconds=60, token_budget=0),
        model="gpt-5.4-mini",
        repository_url="https://github.com/example/repo",
    )
    assert result.prompt_tokens == 6
    assert result.completion_tokens == 4
    assert result.total_tokens == 10
