from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__"})
_ENTRY_POINT_NAMES = (
    "README.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
)
_LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".md": "Markdown",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".sh": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".yml": "YAML",
    ".yaml": "YAML",
}


@dataclass(frozen=True)
class InspectResult:
    file_count: int
    languages: list[str]
    entry_points: list[str]


def inspect_workspace(root: Path) -> InspectResult:
    file_count = 0
    languages: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            file_count += 1
            language = _LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
            if language:
                languages.add(language)

    entry_points = [
        name for name in _ENTRY_POINT_NAMES if (root / name).is_file()
    ]
    return InspectResult(
        file_count=file_count,
        languages=sorted(languages),
        entry_points=entry_points,
    )
