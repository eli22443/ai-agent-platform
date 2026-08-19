from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import UUID


def path_for(task_id: UUID, root: Path) -> Path:
    return root / str(task_id)


def prepare(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return
    if not path.is_dir() or any(path.iterdir()):
        raise FileExistsError(f"Workspace already exists and is not empty: {path}")


def remove(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def directory_size_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, followlinks=False):
        for name in filenames:
            file_path = Path(dirpath) / name
            if file_path.is_symlink():
                continue
            total += file_path.stat().st_size
    return total
