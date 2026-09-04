from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from app.config import get_settings
from app.repositories.inspector import SKIP_DIRS
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.paths import WorkspacePathError, resolve_workspace_path

_FORBIDDEN_RG_MARKERS = (".cursor-server", "/node_modules/@vscode/ripgrep/")
_SYSTEM_RG_FALLBACKS = ("/usr/bin/rg", "/bin/rg")


class SearchCodeInput(BaseModel):
    query: str = Field(
        min_length=1,
        description=(
            "Literal string or regular expression to search for. "
            "Prefer this tool for exact identifiers and strings; "
            "use semantic_search for conceptual queries where wording differs."
        ),
    )
    path: str = Field(
        default=".",
        min_length=1,
        description=(
            "Relative directory or file to restrict the search to. "
            "Use '.' for the whole workspace; never pass an empty path."
        ),
    )
    max_results: int | None = Field(
        default=None,
        ge=1,
        le=500,
        description="Maximum number of matches to return.",
    )


class SearchCodeTool(Tool):
    name: ClassVar[str] = "search_code"
    description: ClassVar[str] = (
        "Search the repository for a pattern using ripgrep. "
        "Returns matching files with line numbers and matching line text. "
        "Prefer this for exact strings and identifiers; "
        "use semantic_search for conceptual queries where wording differs."
    )
    input_model: ClassVar[type[BaseModel]] = SearchCodeInput
    mutating: ClassVar[bool] = False

    def __init__(
        self,
        *,
        ripgrep_path: str | None = None,
        max_results: int | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        settings = get_settings()
        configured = ripgrep_path if ripgrep_path is not None else settings.ripgrep_path
        self._rg_binary = resolve_ripgrep_binary(configured)
        self._default_max_results = (
            max_results if max_results is not None else settings.tool_search_max_results
        )
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.tool_search_timeout_seconds
        )

    def execute(self, context: ToolContext, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, SearchCodeInput)
        try:
            search_root = resolve_workspace_path(
                context.workspace_root, arguments.path, must_exist=True
            )
        except WorkspacePathError as exc:
            return ToolResult(ok=False, data=None, error=str(exc))

        limit = arguments.max_results or self._default_max_results
        workspace = context.workspace_root.resolve()

        command = [
            self._rg_binary,
            "--json",
            "--max-count",
            str(limit),
            *_ignore_globs(),
            "--",
            arguments.query,
            str(search_root),
        ]

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env=_rg_env(),
            )
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, data=None, error="search timed out")
        except OSError:
            return ToolResult(ok=False, data=None, error="failed to run ripgrep")

        if completed.returncode == 0:
            matches, truncated = _parse_rg_json(
                completed.stdout, workspace=workspace, limit=limit
            )
            return ToolResult(
                ok=True,
                data={
                    "query": arguments.query,
                    "path": arguments.path,
                    "matches": matches,
                },
                truncated=truncated,
            )

        if completed.returncode == 1:
            return ToolResult(
                ok=True,
                data={
                    "query": arguments.query,
                    "path": arguments.path,
                    "matches": [],
                },
            )

        return ToolResult(
            ok=False,
            data=None,
            error=_sanitize_rg_error(completed.stderr),
        )


def resolve_ripgrep_binary(configured: str) -> str:
    """Resolve a system ripgrep binary; never use Cursor's bundled rg."""
    candidates: list[str] = []
    configured_path = Path(configured)
    if configured_path.is_absolute() and configured_path.is_file():
        candidates.append(str(configured_path.resolve()))

    found = shutil.which(configured)
    if found:
        candidates.append(found)

    for fallback in _SYSTEM_RG_FALLBACKS:
        if fallback not in candidates:
            candidates.append(fallback)

    for candidate in candidates:
        if any(marker in candidate for marker in _FORBIDDEN_RG_MARKERS):
            continue
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())

    raise FileNotFoundError(
        "system ripgrep (rg) not found; install with "
        "`sudo apt install ripgrep` or set RIPGREP_PATH to a system binary"
    )


def _ignore_globs() -> list[str]:
    globs: list[str] = []
    for name in sorted(SKIP_DIRS):
        globs.extend(["--glob", f"!{name}/**"])
    return globs


def _rg_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = os.environ.get("PATH")
    if path:
        env["PATH"] = path
    home = os.environ.get("HOME")
    if home:
        env["HOME"] = home
    return env


def _parse_rg_json(
    stdout: str, *, workspace: Path, limit: int
) -> tuple[list[dict], bool]:
    matches: list[dict] = []
    truncated = False
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        if len(matches) >= limit:
            truncated = True
            break
        data = event.get("data") or {}
        path_text = (data.get("path") or {}).get("text")
        line_text = (data.get("lines") or {}).get("text")
        line_number = data.get("line_number")
        if not path_text or line_number is None:
            continue

        abs_path = Path(path_text).resolve()
        try:
            rel = abs_path.relative_to(workspace).as_posix()
        except ValueError:
            rel = path_text

        submatches = [
            {
                "start": item.get("start"),
                "end": item.get("end"),
                "match": (item.get("match") or {}).get("text"),
            }
            for item in data.get("submatches") or []
        ]

        matches.append(
            {
                "path": rel,
                "line_number": line_number,
                "line": (line_text or "").rstrip("\n"),
                "submatches": submatches,
            }
        )

    return matches, truncated


def _sanitize_rg_error(stderr: str) -> str:
    line = stderr.strip().splitlines()[0] if stderr.strip() else "ripgrep failed"
    return line[:200]
