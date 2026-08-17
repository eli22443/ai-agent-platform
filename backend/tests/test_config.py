import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_name == "ai-agent-platform"
    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.debug is False


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DEBUG", "true")

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.log_level == "DEBUG"
    assert settings.debug is True


def test_settings_rejects_invalid_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
