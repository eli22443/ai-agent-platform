import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.api.dependencies import get_task_service
from app.services.task_service import TaskService


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    app = create_app()
    service = TaskService()
    app.dependency_overrides[get_task_service] = lambda: service
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
