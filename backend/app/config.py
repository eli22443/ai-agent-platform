from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEFAULT_GIT_ALLOWED_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    app_name: str = "ai-agent-platform"
    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    debug: bool = False
    workspace_root: Path = Path(".workspaces")
    git_clone_timeout_seconds: int = 120
    max_repo_size_mb: int = 200
    git_allowed_hosts: Annotated[tuple[str, ...], NoDecode] = _DEFAULT_GIT_ALLOWED_HOSTS

    @field_validator("git_allowed_hosts", mode="before")
    @classmethod
    def parse_git_allowed_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(host.strip() for host in value.split(",") if host.strip())
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
