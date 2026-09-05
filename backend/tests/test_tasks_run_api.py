from uuid import UUID

VALID_PAYLOAD = {
    "repository_url": "https://github.com/psf/requests",
    "instruction": "Explain how the Session object is used for HTTP requests.",
}


def test_run_returns_410(client):
    created = client.post("/tasks", json=VALID_PAYLOAD)
    assert created.status_code == 202
    task_id = created.json()["task_id"]

    response = client.post(f"/tasks/{task_id}/run")

    assert response.status_code == 410
    body = response.json()
    assert body["error"]["code"] == "gone"
    assert "POST /tasks" in body["error"]["message"]


def test_run_unknown_task_still_410(client):
    response = client.post("/tasks/00000000-0000-0000-0000-000000000000/run")
    assert response.status_code == 410


def test_openapi_run_path_is_410(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/tasks/{task_id}/run" in paths
    run_post = paths["/tasks/{task_id}/run"]["post"]
    assert "410" in run_post["responses"]
    assert "/tasks/{task_id}/runs" in paths
    assert "/tasks/{task_id}/runs/{run_id}" in paths


def test_runs_history_after_process(
    client, db_session, repository_service, monkeypatch
):
    from app.services.agent_run_service import AgentRunService
    from app.services.task_service import TaskService
    from app.tools.registry import build_read_only_registry
    from tests.llm_fakes import FakeLLMClient, text_response, tool_call_response

    created = client.post("/tasks", json=VALID_PAYLOAD)
    task_id = UUID(created.json()["task_id"])

    service = TaskService(
        db_session, repository_service, AgentRunService(db_session)
    )
    result = service.process(
        task_id,
        FakeLLMClient(
            [tool_call_response(), text_response("Done.")],
        ),
        build_read_only_registry(),
    )
    assert result is not None
    run_id = result.run_id

    listed = client.get(f"/tasks/{task_id}/runs")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["run_id"] == str(run_id)
    assert listed.json()[0]["tool_call_count"] == 1

    detail = client.get(f"/tasks/{task_id}/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["result"] == "Done."
