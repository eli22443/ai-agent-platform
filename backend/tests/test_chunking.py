from pathlib import Path

import pytest

from app.retrieval.chunking import CodeChunk, chunk_workspace


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_single_line_file(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "x = 1\n")

    chunks = chunk_workspace(tmp_path, chunk_lines=80, overlap=20)

    assert len(chunks) == 1
    assert chunks[0] == CodeChunk(
        file_path="a.py",
        start_line=1,
        end_line=1,
        language="Python",
        text="x = 1\n",
    )


def test_empty_file(tmp_path: Path) -> None:
    _write(tmp_path / "empty.py", "")

    assert chunk_workspace(tmp_path) == []


def test_overlap_boundaries(tmp_path: Path) -> None:
    body = "\n".join(f"line {i}" for i in range(1, 101)) + "\n"
    _write(tmp_path / "big.py", body)

    chunks = chunk_workspace(tmp_path, chunk_lines=80, overlap=20)

    assert [(c.start_line, c.end_line) for c in chunks] == [(1, 80), (61, 100)]
    assert chunks[0].text.startswith("line 1\n")
    assert "line 80\n" in chunks[0].text
    assert chunks[1].text.startswith("line 61\n")
    assert chunks[1].text.endswith("line 100\n")


def test_skips_node_modules_and_git(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "ok\n")
    _write(tmp_path / "node_modules" / "pkg" / "index.js", "bad\n")
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main")
    _write(tmp_path / ".venv" / "lib" / "site.py", "venv\n")
    _write(tmp_path / "pkg" / "__pycache__" / "mod.py", "cache\n")

    chunks = chunk_workspace(tmp_path)

    assert len(chunks) == 1
    assert chunks[0].file_path == "app.py"


def test_extension_filter(tmp_path: Path) -> None:
    _write(tmp_path / "code.py", "pass\n")
    (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n\0binary")

    chunks = chunk_workspace(tmp_path)

    assert [c.file_path for c in chunks] == ["code.py"]


def test_oversized_file_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "huge.py", "x\n" * 200_000)
    _write(tmp_path / "ok.py", "pass\n")

    chunks = chunk_workspace(tmp_path, max_file_bytes=256_000)

    assert [c.file_path for c in chunks] == ["ok.py"]


def test_relative_posix_paths(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "main.py", "print(1)\n")

    chunks = chunk_workspace(tmp_path)

    assert chunks[0].file_path == "src/main.py"


def test_rejects_invalid_overlap(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "x\n")

    with pytest.raises(ValueError, match="overlap"):
        chunk_workspace(tmp_path, chunk_lines=10, overlap=10)
