from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

TEST_DATABASE_URL = (
    "postgresql+psycopg://ai_agent:ai_agent@127.0.0.1:5432/ai_agent_platform_test"
)


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("GIT_CLONE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("MAX_REPO_SIZE_MB", raising=False)
    monkeypatch.delenv("GIT_ALLOWED_HOSTS", raising=False)

    settings = Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]

    assert settings.app_name == "ai-agent-platform"
    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.debug is False
    assert settings.database_url == TEST_DATABASE_URL
    assert settings.workspace_root == Path(".workspaces")
    assert settings.git_clone_timeout_seconds == 120
    assert settings.max_repo_size_mb == 200
    assert settings.git_allowed_hosts == ("github.com", "gitlab.com", "bitbucket.org")


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/workspaces")
    monkeypatch.setenv("GIT_CLONE_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("MAX_REPO_SIZE_MB", "50")
    monkeypatch.setenv("GIT_ALLOWED_HOSTS", "github.com, gitlab.com")

    settings = Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]

    assert settings.app_env == "production"
    assert settings.log_level == "DEBUG"
    assert settings.debug is True
    assert settings.workspace_root == Path("/tmp/workspaces")
    assert settings.git_clone_timeout_seconds == 30
    assert settings.max_repo_size_mb == 50
    assert settings.git_allowed_hosts == ("github.com", "gitlab.com")


def test_settings_rejects_invalid_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
