import subprocess
from pathlib import Path

import pytest

from app.repositories.errors import CloneError
from app.repositories.git_client import SubprocessGitClient

CLONE_URL = "https://github.com/psf/requests"


def _completed(cmd: list[str], stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, 0, stdout, "")


def test_clone_invokes_git_with_timeout_and_minimal_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    dest = tmp_path / "repo"
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        dest.mkdir()
        (dest / "README").write_text("ok")
        return _completed(cmd)

    monkeypatch.setattr("app.repositories.git_client.subprocess.run", fake_run)
    monkeypatch.setenv("DATABASE_URL", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    client = SubprocessGitClient(timeout_seconds=15, max_repo_size_mb=200)
    client.clone(CLONE_URL, dest)

    assert captured["cmd"] == [
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--",
        CLONE_URL,
        str(dest),
    ]
    kwargs = captured["kwargs"]
    assert kwargs["timeout"] == 15
    assert kwargs["check"] is True
    env = kwargs["env"]
    assert env["PATH"]
    assert "DATABASE_URL" not in env
    assert "OPENAI_API_KEY" not in env


def test_clone_timeout_removes_dest_and_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    dest = tmp_path / "repo"

    def fake_run(cmd, **kwargs):
        dest.mkdir()
        (dest / "partial").write_text("x")
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr("app.repositories.git_client.subprocess.run", fake_run)
    client = SubprocessGitClient(timeout_seconds=1, max_repo_size_mb=200)

    with pytest.raises(CloneError, match="timed out"):
        client.clone(CLONE_URL, dest)
    assert not dest.exists()


def test_clone_nonzero_exit_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    dest = tmp_path / "repo"

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd)

    monkeypatch.setattr("app.repositories.git_client.subprocess.run", fake_run)
    client = SubprocessGitClient(timeout_seconds=15, max_repo_size_mb=200)

    with pytest.raises(CloneError):
        client.clone(CLONE_URL, dest)
    assert not dest.exists()


def test_size_cap_deletes_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    dest = tmp_path / "repo"

    def fake_run(cmd, **kwargs):
        dest.mkdir()
        (dest / "blob").write_bytes(b"x" * (2 * 1024 * 1024))
        return _completed(cmd)

    monkeypatch.setattr("app.repositories.git_client.subprocess.run", fake_run)
    client = SubprocessGitClient(timeout_seconds=15, max_repo_size_mb=1)

    with pytest.raises(CloneError, match="size limit"):
        client.clone(CLONE_URL, dest)
    assert not dest.exists()


def test_head_sha_and_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    dest = tmp_path / "repo"
    dest.mkdir()

    def fake_run(cmd, **kwargs):
        if cmd[-1] == "HEAD" and "--abbrev-ref" in cmd:
            return _completed(cmd, "main\n")
        return _completed(cmd, "abc123\n")

    monkeypatch.setattr("app.repositories.git_client.subprocess.run", fake_run)
    client = SubprocessGitClient(timeout_seconds=15, max_repo_size_mb=200)

    assert client.head_sha(dest) == "abc123"
    assert client.current_branch(dest) == "main"


def test_detached_head_returns_null_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    dest = tmp_path / "repo"
    dest.mkdir()

    def fake_run(cmd, **kwargs):
        return _completed(cmd, "HEAD\n")

    monkeypatch.setattr("app.repositories.git_client.subprocess.run", fake_run)
    client = SubprocessGitClient(timeout_seconds=15, max_repo_size_mb=200)

    assert client.current_branch(dest) is None
