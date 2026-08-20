import os
import shutil
import socket
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

from app.api.dependencies import get_repository_service
from app.main import create_app
from app.repositories.errors import CloneError
from app.repositories.service import RepositoryService

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")


class FakeGitClient:
    def __init__(
        self,
        fixture: Path,
        *,
        fail: bool = False,
        head_sha: str = "abc123def456",
        current_branch: str | None = "main",
    ) -> None:
        self._fixture = fixture
        self._fail = fail
        self._head_sha = head_sha
        self._current_branch = current_branch

    def clone(self, url: str, dest: Path) -> None:
        if self._fail:
            raise CloneError("clone failed")
        shutil.copytree(self._fixture, dest, dirs_exist_ok=True)

    def head_sha(self, dest: Path) -> str:
        return self._head_sha

    def current_branch(self, dest: Path) -> str | None:
        return self._current_branch


def public_getaddrinfo(host: str, port: int, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port))]


def write_repo_fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# demo")
    src = root / "src"
    src.mkdir()
    (src / "main.py").write_text('print("UNIQUE_FIXTURE_TOKEN")\n')
    (src / "utils.py").write_text("def helper():\n    return 1\n")
    return root


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
def fixture_repo(tmp_path: Path) -> Path:
    return write_repo_fixture(tmp_path / "fixture")


@pytest.fixture
def repository_service(
    tmp_path: Path, fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> RepositoryService:
    monkeypatch.setattr("socket.getaddrinfo", public_getaddrinfo)
    return RepositoryService(
        FakeGitClient(fixture_repo),
        tmp_path / "workspaces",
        ALLOWED_HOSTS,
        timeout=30,
        max_size_mb=200,
    )


def _api_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fixture_repo: Path,
    *,
    clone_fails: bool,
) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("WORKSPACES_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setattr("socket.getaddrinfo", public_getaddrinfo)
    get_settings.cache_clear()

    fake_git = FakeGitClient(fixture_repo, fail=clone_fails)

    def override_repository_service() -> RepositoryService:
        settings = get_settings()
        return RepositoryService(
            fake_git,
            settings.workspaces_root,
            settings.git_allowed_hosts,
            timeout=settings.git_clone_timeout_seconds,
            max_size_mb=settings.max_repo_size_mb,
        )

    app = create_app()
    app.dependency_overrides[get_repository_service] = override_repository_service
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_repo: Path
) -> Iterator[TestClient]:
    yield from _api_client(monkeypatch, tmp_path, fixture_repo, clone_fails=False)


@pytest.fixture
def clone_failing_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_repo: Path
) -> Iterator[TestClient]:
    yield from _api_client(monkeypatch, tmp_path, fixture_repo, clone_fails=True)
