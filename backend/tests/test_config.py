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

    settings = Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]

    assert settings.app_name == "ai-agent-platform"
    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.debug is False
    assert settings.database_url == TEST_DATABASE_URL


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DEBUG", "true")

    settings = Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]

    assert settings.app_env == "production"
    assert settings.log_level == "DEBUG"
    assert settings.debug is True


def test_settings_rejects_invalid_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
