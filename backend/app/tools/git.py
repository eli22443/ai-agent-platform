from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from app.config import get_settings
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.paths import WorkspacePathError, resolve_workspace_path


class GetGitDiffInput(BaseModel):
    path: str | None = Field(
        default=None,
        description="Optional relative path to restrict the diff to.",
    )
    staged: bool = Field(
        default=False,
        description="If true, show staged changes; otherwise the working-tree diff.",
    )


class GetGitHistoryInput(BaseModel):
    path: str | None = Field(
        default=None,
        description="Optional relative path to restrict history to.",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of commits to return (1–50).",
    )


class GetGitDiffTool(Tool):
    name: ClassVar[str] = "get_git_diff"
    description: ClassVar[str] = (
        "Show a git diff for the workspace. "
        "By default returns the working-tree diff against HEAD; "
        "set staged=true for the index. Optionally restrict to a path."
    )
    input_model: ClassVar[type[BaseModel]] = GetGitDiffInput
    mutating: ClassVar[bool] = False

    def __init__(
        self,
        *,
        timeout_seconds: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        settings = get_settings()
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.tool_git_timeout_seconds
        )
        self._max_bytes = (
            max_bytes if max_bytes is not None else settings.tool_read_max_bytes
        )

    def execute(self, context: ToolContext, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, GetGitDiffInput)
        workspace = context.workspace_root.resolve()

        rel_path: str | None = None
        if arguments.path is not None:
            try:
                resolved = resolve_workspace_path(
                    workspace, arguments.path, must_exist=True
                )
            except WorkspacePathError as exc:
                return ToolResult(ok=False, data=None, error=str(exc))
            rel_path = resolved.relative_to(workspace).as_posix()

        args = ["diff"]
        if arguments.staged:
            args.append("--cached")
        if rel_path is not None:
            args.extend(["--", rel_path])

        try:
            stdout = _run_git(
                args, cwd=workspace, timeout=self._timeout_seconds
            )
        except _GitToolError as exc:
            return ToolResult(ok=False, data=None, error=str(exc))

        truncated = False
        diff = stdout
        if len(diff.encode("utf-8")) > self._max_bytes:
            diff = diff.encode("utf-8")[: self._max_bytes].decode(
                "utf-8", errors="replace"
            )
            truncated = True

        return ToolResult(
            ok=True,
            data={
                "path": arguments.path,
                "staged": arguments.staged,
                "diff": diff,
            },
            truncated=truncated,
        )


class GetGitHistoryTool(Tool):
    name: ClassVar[str] = "get_git_history"
    description: ClassVar[str] = (
        "List recent commits in the workspace (git log --oneline). "
        "Optionally restrict to commits that touched a path."
    )
    input_model: ClassVar[type[BaseModel]] = GetGitHistoryInput
    mutating: ClassVar[bool] = False

    def __init__(self, *, timeout_seconds: int | None = None) -> None:
        settings = get_settings()
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.tool_git_timeout_seconds
        )

    def execute(self, context: ToolContext, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, GetGitHistoryInput)
        workspace = context.workspace_root.resolve()

        rel_path: str | None = None
        if arguments.path is not None:
            try:
                resolved = resolve_workspace_path(
                    workspace, arguments.path, must_exist=True
                )
            except WorkspacePathError as exc:
                return ToolResult(ok=False, data=None, error=str(exc))
            rel_path = resolved.relative_to(workspace).as_posix()

        args = ["log", "--oneline", f"-n{arguments.limit}"]
        if rel_path is not None:
            args.extend(["--", rel_path])

        try:
            stdout = _run_git(
                args, cwd=workspace, timeout=self._timeout_seconds
            )
        except _GitToolError as exc:
            return ToolResult(ok=False, data=None, error=str(exc))

        commits: list[dict[str, str]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            commit, sep, message = line.partition(" ")
            if not sep:
                commits.append({"commit": commit, "message": ""})
            else:
                commits.append({"commit": commit, "message": message})

        return ToolResult(
            ok=True,
            data={
                "path": arguments.path,
                "limit": arguments.limit,
                "commits": commits,
            },
        )


class _GitToolError(Exception):
    """Git subprocess failure for tool use (mapped to ToolResult)."""


def _run_git(args: list[str], *, cwd: Path, timeout: int) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=False,
            timeout=timeout,
            capture_output=True,
            text=True,
            env=_git_env(),
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise _GitToolError("git command timed out") from exc
    except OSError as exc:
        raise _GitToolError("git command failed") from exc

    if completed.returncode != 0:
        raise _GitToolError(_sanitize_git_error(completed.stderr))
    return completed.stdout


def _git_env() -> dict[str, str]:
    env: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0"}
    path = os.environ.get("PATH")
    if path:
        env["PATH"] = path
    home = os.environ.get("HOME")
    if home:
        env["HOME"] = home
    return env


def _sanitize_git_error(stderr: str) -> str:
    line = stderr.strip().splitlines()[0] if stderr.strip() else "git command failed"
    return line[:200]
