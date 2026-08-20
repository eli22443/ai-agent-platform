from __future__ import annotations

from pathlib import Path


class WorkspacePathError(Exception):
    """User path is empty, absolute, escapes the workspace, or missing when required."""


def resolve_workspace_path(
    workspace_root: Path,
    user_path: str,
    *,
    must_exist: bool = False,
) -> Path:
    """Resolve ``user_path`` under ``workspace_root`` or raise ``WorkspacePathError``.

    Rejects empty paths, absolute paths, and ``..`` traversal before any I/O.
    Resolves symlinks and verifies the final path stays inside the workspace.
    """
    if not user_path or not user_path.strip():
        raise WorkspacePathError("path must not be empty")

    if _is_absolute_user_path(user_path):
        raise WorkspacePathError("absolute paths are not allowed")

    if ".." in Path(user_path).parts:
        raise WorkspacePathError("path traversal is not allowed")

    root = workspace_root.resolve()
    candidate = (root / user_path).resolve()

    if not candidate.is_relative_to(root):
        raise WorkspacePathError("path escapes the workspace")

    if must_exist and not candidate.exists():
        raise WorkspacePathError("path does not exist")

    return candidate


def _is_absolute_user_path(user_path: str) -> bool:
    if Path(user_path).is_absolute():
        return True
    # Windows-style absolute path (e.g. C:\\... or C:/...), including under WSL.
    if len(user_path) >= 2 and user_path[0].isalpha() and user_path[1] == ":":
        return True
    return False
