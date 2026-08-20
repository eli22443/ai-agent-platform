from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from app.config import get_settings
from app.repositories.inspector import SKIP_DIRS, language_for_path
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.paths import WorkspacePathError, resolve_workspace_path

_LIST_MAX_ENTRIES = 1000


class ListFilesInput(BaseModel):
    path: str = Field(
        default=".",
        description="Relative directory to list within the workspace.",
    )
    max_depth: int = Field(
        default=3,
        ge=0,
        le=32,
        description="Maximum directory depth to descend from the start path.",
    )


class ReadFileInput(BaseModel):
    path: str = Field(description="Relative path of the file to read.")


class GetFileInfoInput(BaseModel):
    path: str = Field(
        description="Relative path of the file or directory to inspect."
    )


class ListFilesTool(Tool):
    name: ClassVar[str] = "list_files"
    description: ClassVar[str] = (
        "List files and directories under a workspace path. "
        "Skips .git, node_modules, .venv, and __pycache__. "
        "Returns entries with relative path and type (file or dir)."
    )
    input_model: ClassVar[type[BaseModel]] = ListFilesInput
    mutating: ClassVar[bool] = False

    def __init__(self, *, max_entries: int = _LIST_MAX_ENTRIES) -> None:
        self._max_entries = max_entries

    def execute(self, context: ToolContext, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, ListFilesInput)
        try:
            start = resolve_workspace_path(
                context.workspace_root, arguments.path, must_exist=True
            )
        except WorkspacePathError as exc:
            return ToolResult(ok=False, data=None, error=str(exc))

        if not start.is_dir():
            return ToolResult(ok=False, data=None, error="path is not a directory")

        root = context.workspace_root.resolve()
        entries: list[dict[str, str]] = []
        truncated = False

        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
            current = Path(dirpath)
            depth = len(current.relative_to(start).parts)
            dirnames[:] = sorted(
                name for name in dirnames if name not in SKIP_DIRS
            )

            if depth < arguments.max_depth:
                for name in dirnames:
                    child = current / name
                    if child.is_symlink() or not child.is_dir():
                        continue
                    entries.append(
                        {
                            "path": child.relative_to(root).as_posix(),
                            "type": "dir",
                        }
                    )
                    if len(entries) >= self._max_entries:
                        truncated = True
                        break
            else:
                dirnames.clear()

            if truncated:
                break

            if depth <= arguments.max_depth:
                for name in sorted(filenames):
                    path = current / name
                    if path.is_symlink() or not path.is_file():
                        continue
                    entries.append(
                        {
                            "path": path.relative_to(root).as_posix(),
                            "type": "file",
                        }
                    )
                    if len(entries) >= self._max_entries:
                        truncated = True
                        break

            if truncated:
                break

        return ToolResult(
            ok=True,
            data={"path": arguments.path, "entries": entries},
            truncated=truncated,
        )


class ReadFileTool(Tool):
    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = (
        "Read a text file from the workspace as UTF-8. "
        "Output is bounded by byte and line limits; truncated reads set truncated=true "
        "and include the line range that was returned."
    )
    input_model: ClassVar[type[BaseModel]] = ReadFileInput
    mutating: ClassVar[bool] = False

    def __init__(
        self,
        *,
        max_bytes: int | None = None,
        max_lines: int | None = None,
    ) -> None:
        settings = get_settings()
        self._max_bytes = (
            max_bytes if max_bytes is not None else settings.tool_read_max_bytes
        )
        self._max_lines = (
            max_lines if max_lines is not None else settings.tool_read_max_lines
        )

    def execute(self, context: ToolContext, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, ReadFileInput)
        try:
            path = resolve_workspace_path(
                context.workspace_root, arguments.path, must_exist=True
            )
        except WorkspacePathError as exc:
            return ToolResult(ok=False, data=None, error=str(exc))

        if not path.is_file():
            return ToolResult(ok=False, data=None, error="path is not a file")

        raw = path.read_bytes()
        truncated = False
        if len(raw) > self._max_bytes:
            raw = raw[: self._max_bytes]
            truncated = True

        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) > self._max_lines:
            lines = lines[: self._max_lines]
            truncated = True
            text = "\n".join(lines)
            if text:
                text += "\n"

        end_line = len(lines)
        return ToolResult(
            ok=True,
            data={
                "path": arguments.path,
                "content": text,
                "start_line": 1 if end_line else 0,
                "end_line": end_line,
            },
            truncated=truncated,
        )


class GetFileInfoTool(Tool):
    name: ClassVar[str] = "get_file_info"
    description: ClassVar[str] = (
        "Return metadata for a workspace path: existence, size, language, "
        "and line count for text files."
    )
    input_model: ClassVar[type[BaseModel]] = GetFileInfoInput
    mutating: ClassVar[bool] = False

    def execute(self, context: ToolContext, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, GetFileInfoInput)
        try:
            path = resolve_workspace_path(context.workspace_root, arguments.path)
        except WorkspacePathError as exc:
            return ToolResult(ok=False, data=None, error=str(exc))

        if not path.exists():
            return ToolResult(
                ok=True,
                data={
                    "path": arguments.path,
                    "exists": False,
                    "size_bytes": None,
                    "line_count": None,
                    "language": None,
                },
            )

        if path.is_dir():
            return ToolResult(
                ok=True,
                data={
                    "path": arguments.path,
                    "exists": True,
                    "size_bytes": None,
                    "line_count": None,
                    "language": None,
                    "type": "dir",
                },
            )

        if not path.is_file():
            return ToolResult(
                ok=False, data=None, error="path is not a file or directory"
            )

        size_bytes = path.stat().st_size
        language = language_for_path(path)
        line_count: int | None
        if _is_probably_binary(path):
            line_count = None
        else:
            content = path.read_text(encoding="utf-8", errors="replace")
            line_count = len(content.splitlines())

        return ToolResult(
            ok=True,
            data={
                "path": arguments.path,
                "exists": True,
                "size_bytes": size_bytes,
                "line_count": line_count,
                "language": language,
                "type": "file",
            },
        )


def _is_probably_binary(path: Path) -> bool:
    chunk = path.read_bytes()[:8192]
    return b"\0" in chunk
