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
    monkeypatch.delenv("WORKSPACES_ROOT", raising=False)
    monkeypatch.delenv("GIT_CLONE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("MAX_REPO_SIZE_MB", raising=False)
    monkeypatch.delenv("GIT_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("RIPGREP_PATH", raising=False)
    monkeypatch.delenv("TOOL_READ_MAX_BYTES", raising=False)
    monkeypatch.delenv("TOOL_READ_MAX_LINES", raising=False)
    monkeypatch.delenv("TOOL_SEARCH_MAX_RESULTS", raising=False)
    monkeypatch.delenv("TOOL_SEARCH_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("TOOL_GIT_TIMEOUT_SECONDS", raising=False)

    settings = Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]

    assert settings.app_name == "ai-agent-platform"
    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.debug is False
    assert settings.database_url == TEST_DATABASE_URL
    assert settings.workspaces_root == Path(".workspaces")
    assert settings.git_clone_timeout_seconds == 120
    assert settings.max_repo_size_mb == 200
    assert settings.git_allowed_hosts == ("github.com", "gitlab.com", "bitbucket.org")
    assert settings.ripgrep_path == "rg"
    assert settings.tool_read_max_bytes == 65536
    assert settings.tool_read_max_lines == 500
    assert settings.tool_search_max_results == 50
    assert settings.tool_search_timeout_seconds == 30
    assert settings.tool_git_timeout_seconds == 30


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("WORKSPACES_ROOT", "/tmp/workspaces")
    monkeypatch.setenv("GIT_CLONE_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("MAX_REPO_SIZE_MB", "50")
    monkeypatch.setenv("GIT_ALLOWED_HOSTS", "github.com, gitlab.com")
    monkeypatch.setenv("RIPGREP_PATH", "/usr/bin/rg")
    monkeypatch.setenv("TOOL_READ_MAX_BYTES", "1024")
    monkeypatch.setenv("TOOL_READ_MAX_LINES", "10")
    monkeypatch.setenv("TOOL_SEARCH_MAX_RESULTS", "5")
    monkeypatch.setenv("TOOL_SEARCH_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("TOOL_GIT_TIMEOUT_SECONDS", "20")

    settings = Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]

    assert settings.app_env == "production"
    assert settings.log_level == "DEBUG"
    assert settings.debug is True
    assert settings.workspaces_root == Path("/tmp/workspaces")
    assert settings.git_clone_timeout_seconds == 30
    assert settings.max_repo_size_mb == 50
    assert settings.git_allowed_hosts == ("github.com", "gitlab.com")
    assert settings.ripgrep_path == "/usr/bin/rg"
    assert settings.tool_read_max_bytes == 1024
    assert settings.tool_read_max_lines == 10
    assert settings.tool_search_max_results == 5
    assert settings.tool_search_timeout_seconds == 15
    assert settings.tool_git_timeout_seconds == 20


def test_settings_rejects_invalid_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
