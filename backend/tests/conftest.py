import os
import pytest
from fastapi.testclient import TestClient
from app.main import create_app

@pytest.fixture
def client():
    os.environ["APP_ENV"] = "test"
    app = create_app()
    with TestClient(app) as c:
        yield c