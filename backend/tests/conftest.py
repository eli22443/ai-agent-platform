import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
