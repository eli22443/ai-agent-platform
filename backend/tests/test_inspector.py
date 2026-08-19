from pathlib import Path

from app.repositories.inspector import inspect_workspace


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_inspect_counts_and_languages(tmp_path: Path):
    _write(tmp_path / "README.md", "# demo")
    _write(tmp_path / "src" / "main.py", "print('hi')")

    result = inspect_workspace(tmp_path)

    assert result.file_count == 2
    assert result.languages == ["Markdown", "Python"]
    assert result.entry_points == ["README.md"]


def test_inspect_skips_git_and_junk(tmp_path: Path):
    _write(tmp_path / "app.py")
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main")
    _write(tmp_path / "node_modules" / "pkg" / "index.js", "module.exports = 1")
    _write(tmp_path / ".venv" / "lib" / "site.py")
    _write(tmp_path / "pkg" / "__pycache__" / "mod.cpython-312.pyc", "not-python")

    result = inspect_workspace(tmp_path)

    assert result.file_count == 1
    assert result.languages == ["Python"]


def test_inspect_entry_points_only_at_repo_root(tmp_path: Path):
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "nested" / "Cargo.toml", "[package]")
    _write(tmp_path / "README.md", "# root")

    result = inspect_workspace(tmp_path)

    assert result.entry_points == ["README.md", "package.json"]
