import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

TEST_DATABASE_URL = (
    "postgresql+psycopg://ai_agent:ai_agent@127.0.0.1:5432/ai_agent_platform_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.config import get_settings

get_settings.cache_clear()

from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _truncate(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(
            text("TRUNCATE agent_runs, tasks, repositories RESTART IDENTITY CASCADE")
        )
        connection.commit()


@pytest.fixture(scope="session")
def apply_migrations() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def engine(apply_migrations) -> Engine:
    return create_engine(TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def session_factory(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def truncate_tables(engine: Engine) -> Iterator[None]:
    _truncate(engine)
    yield
    _truncate(engine)


@pytest.fixture
def db_session(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
