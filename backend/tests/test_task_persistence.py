from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database.models import Repository, TaskRecord
from app.main import create_app
from app.services.task_service import TaskService

REQUESTS_URL = "https://github.com/psf/requests"
HTTPX_URL = "https://github.com/encode/httpx"
INSTRUCTION = "Explain how the retry logic works."
OTHER_INSTRUCTION = "Summarize the transport layer design."


def test_create_task_persists_across_sessions(
    session_factory: sessionmaker, repository_service
):
    session = session_factory()
    try:
        task = TaskService(session, repository_service).create(
            REQUESTS_URL, INSTRUCTION
        )
        session.commit()
        task_id = task.id
    finally:
        session.close()

    session = session_factory()
    try:
        found = TaskService(session, repository_service).get(task_id)
        assert found is not None
        assert found.id == task_id
        assert found.repository_url == REQUESTS_URL
        assert found.instruction == INSTRUCTION
    finally:
        session.close()


def test_create_reuses_repository_row_for_same_url(
    db_session: Session, repository_service
):
    service = TaskService(db_session, repository_service)
    service.create(REQUESTS_URL, INSTRUCTION)
    service.create(REQUESTS_URL, OTHER_INSTRUCTION)

    repositories = db_session.scalars(select(Repository)).all()
    tasks = db_session.scalars(select(TaskRecord)).all()

    assert len(repositories) == 1
    assert len(tasks) == 2
    assert {row.repository_id for row in tasks} == {repositories[0].id}


def test_create_separate_urls_create_separate_repositories(
    db_session: Session, repository_service
):
    service = TaskService(db_session, repository_service)
    service.create(REQUESTS_URL, INSTRUCTION)
    service.create(HTTPX_URL, OTHER_INSTRUCTION)

    urls = set(db_session.scalars(select(Repository.url)).all())
    assert urls == {REQUESTS_URL, HTTPX_URL}


def test_task_row_has_foreign_key_to_repository(
    db_session: Session, repository_service
):
    task = TaskService(db_session, repository_service).create(
        REQUESTS_URL, INSTRUCTION
    )

    record = db_session.get(TaskRecord, task.id)
    repository = db_session.scalars(
        select(Repository).where(Repository.url == REQUESTS_URL)
    ).one()

    assert record is not None
    assert record.repository_id == repository.id


def test_get_unknown_task_returns_none_from_new_session(
    session_factory: sessionmaker,
    repository_service,
):
    session = session_factory()
    try:
        result = TaskService(session, repository_service).get(
            UUID("00000000-0000-0000-0000-000000000000")
        )
        assert result is None
    finally:
        session.close()


def test_list_tasks_empty_after_truncate(client: TestClient):
    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == []


def test_restart_survives_via_api(client: TestClient):
    created = client.post(
        "/tasks",
        json={"repository_url": REQUESTS_URL, "instruction": INSTRUCTION},
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as restarted:
        response = restarted.get(f"/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json()["task_id"] == task_id
    assert response.json()["instruction"] == INSTRUCTION


def test_migration_creates_expected_tables(engine: Engine):
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        ).all()

    names = {row[0] for row in rows}
    assert {"repositories", "tasks", "agent_runs"}.issubset(names)
