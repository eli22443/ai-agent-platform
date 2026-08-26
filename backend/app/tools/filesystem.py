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
        min_length=1,
        description=(
            "Relative directory to list within the workspace. "
            "Use '.' for the workspace root; never pass an empty path."
        ),
    )
    max_depth: int = Field(
        default=3,
        ge=0,
        le=32,
        description="Maximum directory depth to descend from the start path.",
    )


class ReadFileInput(BaseModel):
    path: str = Field(
        min_length=1,
        description="Relative path of the file to read. Never pass an empty path.",
    )
    start_line: int = Field(
        default=1,
        ge=1,
        description=(
            "1-based line to start reading from. "
            "If a previous read returned truncated=true, call again with "
            "start_line=end_line+1. Do not re-read the same start_line."
        ),
    )


class GetFileInfoInput(BaseModel):
    path: str = Field(
        min_length=1,
        description=(
            "Relative path of the file or directory to inspect. "
            "Never pass an empty path."
        ),
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
            dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)

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
        "Returns at most max_lines starting at start_line (also bounded by max_bytes). "
        "If truncated=true, continue with start_line=end_line+1; "
        "re-reading the same start_line returns the same content."
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

        text = path.read_bytes().decode("utf-8", errors="replace")
        all_lines = text.splitlines()
        total_lines = len(all_lines)
        start = arguments.start_line

        if start > total_lines and total_lines > 0:
            return ToolResult(
                ok=False,
                data=None,
                error=(f"start_line {start} is past end of file ({total_lines} lines)"),
            )

        slice_lines = all_lines[start - 1 :]
        truncated = False

        if len(slice_lines) > self._max_lines:
            slice_lines = slice_lines[: self._max_lines]
            truncated = True

        content = "\n".join(slice_lines)
        if content:
            content += "\n"

        encoded = content.encode("utf-8")
        if len(encoded) > self._max_bytes:
            encoded = encoded[: self._max_bytes]
            content = encoded.decode("utf-8", errors="ignore")
            if not content.endswith("\n") and "\n" in content:
                content = content.rsplit("\n", 1)[0] + "\n"
            slice_lines = content.splitlines()
            truncated = True

        end_line = start + len(slice_lines) - 1 if slice_lines else 0
        if end_line < total_lines:
            truncated = True

        return ToolResult(
            ok=True,
            data={
                "path": arguments.path,
                "content": content,
                "start_line": start if slice_lines else 0,
                "end_line": end_line,
                "total_lines": total_lines,
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
