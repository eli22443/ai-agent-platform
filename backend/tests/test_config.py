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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("AGENT_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("AGENT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AGENT_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("AGENT_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    monkeypatch.delenv("PINECONE_INDEX", raising=False)
    monkeypatch.delenv("RETRIEVAL_CHUNK_LINES", raising=False)
    monkeypatch.delenv("RETRIEVAL_CHUNK_OVERLAP", raising=False)
    monkeypatch.delenv("RETRIEVAL_MAX_FILE_BYTES", raising=False)
    monkeypatch.delenv("RETRIEVAL_EMBED_BATCH_SIZE", raising=False)
    monkeypatch.delenv("RETRIEVAL_SEARCH_TOP_K", raising=False)
    monkeypatch.delenv("RETRIEVAL_INDEX_ENABLED", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("ARQ_JOB_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("STUCK_TASK_THRESHOLD_MINUTES", raising=False)

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
    assert settings.openai_api_key == ""
    assert settings.openai_model == "gpt-5.4-mini"
    assert settings.agent_max_iterations == 10
    assert settings.agent_timeout_seconds == 180
    assert settings.agent_max_output_tokens == 8192
    assert settings.agent_token_budget == 0
    assert settings.openai_embedding_model == "text-embedding-3-small"
    assert settings.pinecone_api_key == ""
    assert settings.pinecone_index == ""
    assert settings.retrieval_chunk_lines == 80
    assert settings.retrieval_chunk_overlap == 20
    assert settings.retrieval_max_file_bytes == 256_000
    assert settings.retrieval_embed_batch_size == 64
    assert settings.retrieval_search_top_k == 10
    assert settings.retrieval_index_enabled is True
    assert settings.redis_url == "redis://127.0.0.1:6379/0"
    assert settings.arq_job_timeout_seconds == 600
    assert settings.stuck_task_threshold_minutes == 30


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
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "5")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("AGENT_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("AGENT_TOKEN_BUDGET", "10000")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("PINECONE_API_KEY", "pc-test")
    monkeypatch.setenv("PINECONE_INDEX", "code-index")
    monkeypatch.setenv("RETRIEVAL_CHUNK_LINES", "40")
    monkeypatch.setenv("RETRIEVAL_CHUNK_OVERLAP", "10")
    monkeypatch.setenv("RETRIEVAL_MAX_FILE_BYTES", "128000")
    monkeypatch.setenv("RETRIEVAL_EMBED_BATCH_SIZE", "32")
    monkeypatch.setenv("RETRIEVAL_SEARCH_TOP_K", "5")
    monkeypatch.setenv("RETRIEVAL_INDEX_ENABLED", "false")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/1")
    monkeypatch.setenv("ARQ_JOB_TIMEOUT_SECONDS", "900")
    monkeypatch.setenv("STUCK_TASK_THRESHOLD_MINUTES", "45")

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
    assert settings.openai_api_key == "sk-test"
    assert settings.openai_model == "gpt-4.1"
    assert settings.agent_max_iterations == 5
    assert settings.agent_timeout_seconds == 60
    assert settings.agent_max_output_tokens == 2048
    assert settings.agent_token_budget == 10000
    assert settings.openai_embedding_model == "text-embedding-3-large"
    assert settings.pinecone_api_key == "pc-test"
    assert settings.pinecone_index == "code-index"
    assert settings.retrieval_chunk_lines == 40
    assert settings.retrieval_chunk_overlap == 10
    assert settings.retrieval_max_file_bytes == 128000
    assert settings.retrieval_embed_batch_size == 32
    assert settings.retrieval_search_top_k == 5
    assert settings.retrieval_index_enabled is False
    assert settings.redis_url == "redis://cache:6379/1"
    assert settings.arq_job_timeout_seconds == 900
    assert settings.stuck_task_threshold_minutes == 45


def test_settings_rejects_invalid_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)  # type: ignore[call-arg]


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
