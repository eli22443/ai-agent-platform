from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from app.repositories.inspector import SKIP_DIRS, language_for_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodeChunk:
    file_path: str  # relative to workspace root, posix separators
    start_line: int  # 1-based inclusive
    end_line: int  # 1-based inclusive
    language: str | None
    text: str


def chunk_workspace(
    root: Path,
    *,
    chunk_lines: int = 80,
    overlap: int = 20,
    max_file_bytes: int = 256_000,
) -> list[CodeChunk]:
    if chunk_lines < 1:
        raise ValueError("chunk_lines must be >= 1")
    if overlap < 0 or overlap >= chunk_lines:
        raise ValueError("overlap must be >= 0 and < chunk_lines")

    root = root.resolve()
    step = chunk_lines - overlap
    chunks: list[CodeChunk] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue

            language = language_for_path(path)
            if language is None:
                continue
            if _is_probably_binary(path):
                continue

            size = path.stat().st_size
            if size > max_file_bytes:
                rel = path.relative_to(root).as_posix()
                logger.warning(
                    "skipping oversized file for chunking: %s (%d bytes)",
                    rel,
                    size,
                )
                continue

            rel_path = path.relative_to(root).as_posix()
            lines = path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines(keepends=True)
            if not lines:
                continue

            start = 1
            total = len(lines)
            while start <= total:
                end = min(start + chunk_lines - 1, total)
                text = "".join(lines[start - 1 : end])
                chunks.append(
                    CodeChunk(
                        file_path=rel_path,
                        start_line=start,
                        end_line=end,
                        language=language,
                        text=text,
                    )
                )
                if end == total:
                    break
                start += step

    return chunks


def _is_probably_binary(path: Path) -> bool:
    return b"\0" in path.read_bytes()[:8192]
