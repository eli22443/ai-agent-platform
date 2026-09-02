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

    workspaces_root: Path = Path(".workspaces")
    git_clone_timeout_seconds: int = 120

    max_repo_size_mb: int = 200
    git_allowed_hosts: Annotated[tuple[str, ...], NoDecode] = _DEFAULT_GIT_ALLOWED_HOSTS
    ripgrep_path: str = "rg"
    tool_read_max_bytes: int = 65536
    tool_read_max_lines: int = 500
    tool_search_max_results: int = 50
    tool_search_timeout_seconds: int = 30
    tool_git_timeout_seconds: int = 30

    # Empty allowed so Settings can load in tests; OpenAILLMClient rejects empty at call time.
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    agent_max_iterations: int = 10
    agent_timeout_seconds: int = 180
    agent_max_output_tokens: int = 8192
    agent_token_budget: int = 0

    # Phase 8 — semantic retrieval
    openai_embedding_model: str = "text-embedding-3-small"
    pinecone_api_key: str = ""
    pinecone_index: str = ""
    retrieval_chunk_lines: int = 80
    retrieval_chunk_overlap: int = 20
    retrieval_max_file_bytes: int = 256_000
    retrieval_embed_batch_size: int = 64
    retrieval_search_top_k: int = 10
    retrieval_index_enabled: bool = True

    @field_validator("git_allowed_hosts", mode="before")
    @classmethod
    def parse_git_allowed_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(host.strip() for host in value.split(",") if host.strip())
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
