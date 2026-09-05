from pathlib import Path

VALID_PAYLOAD = {
    "repository_url": "https://github.com/psf/requests",
    "instruction": "Explain how the retry logic works.",
}


def test_create_task_returns_201_with_pending_status(client):
    response = client.post("/tasks", json=VALID_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["task_id"]
    assert body["status"] == "pending"


def test_create_task_echoes_submitted_fields(client):
    response = client.post("/tasks", json=VALID_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["repository_url"] == VALID_PAYLOAD["repository_url"]
    assert body["instruction"] == VALID_PAYLOAD["instruction"]
    assert body["created_at"]


def test_create_task_generates_unique_ids(client):
    first = client.post("/tasks", json=VALID_PAYLOAD)
    second = client.post("/tasks", json=VALID_PAYLOAD)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["task_id"] != second.json()["task_id"]


def test_list_tasks_is_empty_initially(client):
    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == []


def test_get_task_returns_created_task(client):
    created = client.post("/tasks", json=VALID_PAYLOAD)
    task_id = created.json()["task_id"]

    response = client.get(f"/tasks/{task_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["status"] == "pending"
    assert body["repository_url"] == VALID_PAYLOAD["repository_url"]
    assert body["instruction"] == VALID_PAYLOAD["instruction"]


def test_list_tasks_returns_created_tasks(client):
    first = client.post("/tasks", json=VALID_PAYLOAD)
    second = client.post(
        "/tasks",
        json={
            "repository_url": "https://github.com/encode/httpx",
            "instruction": "Summarize the transport layer design.",
        },
    )

    response = client.get("/tasks")

    assert response.status_code == 200
    bodies = response.json()
    assert len(bodies) == 2
    ids = {body["task_id"] for body in bodies}
    assert ids == {first.json()["task_id"], second.json()["task_id"]}


def test_get_unknown_task_returns_404_envelope(client):
    response = client.get("/tasks/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    body = response.json()
    assert "detail" not in body
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "Task not found."
    assert body["error"]["request_id"]


def test_get_task_malformed_uuid_returns_422(client):
    response = client.get("/tasks/not-a-uuid")

    assert response.status_code == 422
    body = response.json()
    assert "detail" not in body
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["request_id"]


def test_create_task_rejects_invalid_url(client):
    response = client.post(
        "/tasks",
        json={"repository_url": "nonsense", "instruction": VALID_PAYLOAD["instruction"]},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


def test_create_task_rejects_non_http_scheme(client):
    response = client.post(
        "/tasks",
        json={
            "repository_url": "file:///etc/passwd",
            "instruction": VALID_PAYLOAD["instruction"],
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


def test_create_task_rejects_short_instruction(client):
    response = client.post(
        "/tasks",
        json={"repository_url": VALID_PAYLOAD["repository_url"], "instruction": "short"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


def test_create_task_rejects_missing_fields(client):
    response = client.post("/tasks", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"


def test_openapi_includes_task_paths(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/tasks" in paths
    assert "/tasks/{task_id}" in paths
    assert "/tasks/{task_id}/run" in paths


def test_create_task_rejects_localhost(client):
    response = client.post(
        "/tasks",
        json={
            "repository_url": "https://127.0.0.1/x",
            "instruction": VALID_PAYLOAD["instruction"],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert "detail" not in body
    assert body["error"]["code"] == "bad_request"
    assert body["error"]["message"] == "Repository URL is not allowed."
    assert body["error"]["request_id"]


def test_create_task_rejects_unknown_host(client):
    response = client.post(
        "/tasks",
        json={
            "repository_url": "https://evil.example/org/repo",
            "instruction": VALID_PAYLOAD["instruction"],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "bad_request"
    assert body["error"]["message"] == "Repository URL is not allowed."
    assert body["error"]["request_id"]


def test_create_task_does_not_clone(client, tmp_path: Path):
    response = client.post("/tasks", json=VALID_PAYLOAD)

    assert response.status_code == 201
    task_id = response.json()["task_id"]
    assert not (tmp_path / "workspaces" / task_id).exists()


def test_create_task_enqueue_failure_returns_503(client, monkeypatch):
    from app.queue.client import QueueError

    monkeypatch.setattr(
        "app.services.task_service.enqueue_process_task",
        lambda _task_id: (_ for _ in ()).throw(QueueError("Failed to enqueue background job.")),
    )

    response = client.post("/tasks", json=VALID_PAYLOAD)

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["message"] == "Failed to enqueue background job."
    assert body["error"]["request_id"]
