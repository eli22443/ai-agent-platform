from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Protocol

from app.repositories.errors import CloneError
from app.repositories.workspace import directory_size_bytes
from app.repositories.workspace import remove as remove_workspace

_BYTES_PER_MB = 1024 * 1024


class GitClient(Protocol):
    def clone(self, url: str, dest: Path) -> None: ...
    def head_sha(self, dest: Path) -> str: ...
    def current_branch(self, dest: Path) -> str | None: ...


class SubprocessGitClient:
    def __init__(self, *, timeout_seconds: int, max_repo_size_mb: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_repo_size_bytes = max_repo_size_mb * _BYTES_PER_MB

    def clone(self, url: str, dest: Path) -> None:
        try:
            _run_git(
                ["clone", "--depth", "1", "--single-branch", "--", url, str(dest)],
                timeout=self._timeout_seconds,
            )
        except CloneError:
            remove_workspace(dest)
            raise

        if directory_size_bytes(dest) > self._max_repo_size_bytes:
            remove_workspace(dest)
            raise CloneError("cloned repository exceeds size limit")

    def head_sha(self, dest: Path) -> str:
        sha = _run_git(
            ["rev-parse", "HEAD"],
            cwd=dest,
            timeout=self._timeout_seconds,
        )
        if not sha:
            raise CloneError("failed to read HEAD")
        return sha

    def current_branch(self, dest: Path) -> str | None:
        branch = _run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"],
            cwd=dest,
            timeout=self._timeout_seconds,
        )
        if not branch or branch == "HEAD":
            return None
        return branch


def _run_git(
    args: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=True,
            timeout=timeout,
            capture_output=True,
            text=True,
            env=_git_env(),
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise CloneError("git command timed out") from exc
    except (subprocess.CalledProcessError, OSError) as exc:
        raise CloneError("git command failed") from exc
    return completed.stdout.strip()


def _git_env() -> dict[str, str]:
    env: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0"}
    path = os.environ.get("PATH")
    if path:
        env["PATH"] = path
    home = os.environ.get("HOME")
    if home:
        env["HOME"] = home
    return env
