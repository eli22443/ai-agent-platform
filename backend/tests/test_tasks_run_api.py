from pathlib import Path

from app.api.dependencies import get_llm_client
from app.llm import LLMError
from app.repositories.workspace import remove as remove_workspace
from tests.llm_fakes import FakeLLMClient, text_response, tool_call_response

VALID_PAYLOAD = {
    "repository_url": "https://github.com/psf/requests",
    "instruction": "Explain how the Session object is used for HTTP requests.",
}


def _override_llm(client, scripts: list) -> FakeLLMClient:
    fake = FakeLLMClient(scripts)
    client.app.dependency_overrides[get_llm_client] = lambda: fake
    return fake


def _clear_llm_override(client) -> None:
    client.app.dependency_overrides.pop(get_llm_client, None)


def test_run_returns_200_with_answer(client):
    fake = _override_llm(client, [text_response("Session manages cookies and headers.")])
    try:
        created = client.post("/tasks", json=VALID_PAYLOAD)
        assert created.status_code == 201
        task_id = created.json()["task_id"]

        response = client.post(f"/tasks/{task_id}/run")

        assert response.status_code == 200
        body = response.json()
        assert body["task_id"] == task_id
        assert body["status"] == "completed"
        assert body["answer"] == "Session manages cookies and headers."
        assert body["halt_reason"] is None
        assert body["error"] is None
        assert body["iterations"] == 1
        assert body["tool_calls"] == []
        assert body["run_id"] is not None
        assert fake.calls == 1

        got = client.get(f"/tasks/{task_id}")
        assert got.status_code == 200
        assert got.json()["status"] == "completed"
        assert got.json()["result"] == "Session manages cookies and headers."
        assert got.json()["error"] is None

        runs = client.get(f"/tasks/{task_id}/runs")
        assert runs.status_code == 200
        assert len(runs.json()) == 1
        assert runs.json()[0]["run_id"] == body["run_id"]
        assert runs.json()[0]["tool_call_count"] == 0
    finally:
        _clear_llm_override(client)


def test_run_with_tool_call_then_answer(client):
    _override_llm(
        client,
        [
            tool_call_response(),
            text_response("README and src/ are present."),
        ],
    )
    try:
        task_id = client.post("/tasks", json=VALID_PAYLOAD).json()["task_id"]
        response = client.post(f"/tasks/{task_id}/run")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["answer"] == "README and src/ are present."
        assert body["iterations"] == 2
        assert len(body["tool_calls"]) == 1
        assert body["tool_calls"][0]["name"] == "list_files"
        assert body["tool_calls"][0]["ok"] is True
        assert body["tool_calls"][0]["duration_ms"] >= 0
        assert body["run_id"] is not None

        runs = client.get(f"/tasks/{task_id}/runs")
        assert runs.status_code == 200
        assert runs.json()[0]["tool_call_count"] == len(body["tool_calls"])

        detail = client.get(f"/tasks/{task_id}/runs/{body['run_id']}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "completed"
        assert len(detail.json()["tool_calls"]) == 1
        assert detail.json()["tool_calls"][0]["sequence"] == 1
        assert detail.json()["tool_calls"][0]["name"] == "list_files"
    finally:
        _clear_llm_override(client)


def test_run_again_returns_409(client):
    _override_llm(client, [text_response("done")])
    try:
        task_id = client.post("/tasks", json=VALID_PAYLOAD).json()["task_id"]
        first = client.post(f"/tasks/{task_id}/run")
        assert first.status_code == 200

        second = client.post(f"/tasks/{task_id}/run")
        assert second.status_code == 409
        body = second.json()
        assert body["error"]["code"] == "conflict"
        assert "not runnable" in body["error"]["message"]
    finally:
        _clear_llm_override(client)


def test_run_unknown_task_returns_404(client):
    _override_llm(client, [text_response("unused")])
    try:
        response = client.post(
            "/tasks/00000000-0000-0000-0000-000000000000/run"
        )
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "not_found"
        assert body["error"]["message"] == "Task not found."
    finally:
        _clear_llm_override(client)


def test_run_missing_workspace_returns_409(client, tmp_path: Path):
    _override_llm(client, [text_response("unused")])
    try:
        created = client.post("/tasks", json=VALID_PAYLOAD)
        task_id = created.json()["task_id"]
        workspace = tmp_path / "workspaces" / task_id
        remove_workspace(workspace)

        response = client.post(f"/tasks/{task_id}/run")
        assert response.status_code == 409
        body = response.json()
        assert body["error"]["code"] == "conflict"
        assert "workspace" in body["error"]["message"]
    finally:
        _clear_llm_override(client)


def test_run_llm_failure_returns_failed_status(client):
    _override_llm(client, [LLMError("OpenAI request failed.")])
    try:
        task_id = client.post("/tasks", json=VALID_PAYLOAD).json()["task_id"]
        response = client.post(f"/tasks/{task_id}/run")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error"] == "OpenAI request failed."
        assert body["halt_reason"] is None

        got = client.get(f"/tasks/{task_id}")
        assert got.json()["status"] == "failed"
        assert got.json()["error"] == "OpenAI request failed."
        assert got.json()["result"] is None
    finally:
        _clear_llm_override(client)


def test_openapi_includes_run_path(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/tasks/{task_id}/run" in paths
    assert "/tasks/{task_id}/runs" in paths
    assert "/tasks/{task_id}/runs/{run_id}" in paths
