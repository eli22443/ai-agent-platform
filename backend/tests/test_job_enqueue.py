from uuid import UUID

from fastapi.testclient import TestClient

VALID_PAYLOAD = {
    "repository_url": "https://github.com/psf/requests",
    "instruction": "Explain how the retry logic works.",
}


def test_post_tasks_returns_202_and_enqueues(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    enqueued: list[UUID] = []
    monkeypatch.setattr(
        "app.services.task_service.enqueue_process_task",
        lambda task_id: enqueued.append(task_id),
    )

    response = client.post("/tasks", json=VALID_PAYLOAD)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["task_id"]
    assert enqueued == [UUID(body["task_id"])]
    assert not (tmp_path / "workspaces" / body["task_id"]).exists()

    got = client.get(f"/tasks/{body['task_id']}")
    assert got.status_code == 200
    assert got.json()["status"] == "pending"


def test_post_tasks_enqueue_failure_returns_503(client: TestClient, monkeypatch) -> None:
    from app.queue.client import QueueError

    monkeypatch.setattr(
        "app.services.task_service.enqueue_process_task",
        lambda _task_id: (_ for _ in ()).throw(
            QueueError("Failed to enqueue background job.")
        ),
    )

    response = client.post("/tasks", json=VALID_PAYLOAD)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert response.json()["error"]["message"] == "Failed to enqueue background job."
