from pathlib import Path
from uuid import uuid4

import pytest

from app.retrieval.indexer import ensure_indexed
from app.retrieval.search import semantic_search
from app.retrieval.vector_store import InMemoryVectorStore, namespace_for_task


class FakeEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t) % 10), 1.0] for t in texts]


class KeywordEmbedder:
    """Maps texts containing 'cookie' near [1, 0]; others near [0, 1]."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            if "cookie" in text.lower():
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors


class MismatchedEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0]]  # always one vector, regardless of input size


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_ensure_indexed_upserts_chunks(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "def foo():\n    return 1\n")
    task_id = uuid4()
    store = InMemoryVectorStore()

    result = ensure_indexed(
        workspace_root=tmp_path,
        task_id=task_id,
        embedder=FakeEmbedder(),
        store=store,
        chunk_lines=80,
        overlap=20,
    )

    assert result.chunks_indexed >= 1
    assert result.vectors_upserted == result.chunks_indexed
    assert result.duration_ms >= 0

    matches = store.query(namespace_for_task(task_id), [2.0, 1.0], top_k=5)
    assert any(m.metadata["file_path"] == "a.py" for m in matches)
    assert matches[0].metadata["task_id"] == str(task_id)
    assert "start_line" in matches[0].metadata
    assert "end_line" in matches[0].metadata
    assert "snippet" in matches[0].metadata


def test_ensure_indexed_empty_workspace(tmp_path: Path) -> None:
    result = ensure_indexed(
        workspace_root=tmp_path,
        task_id=uuid4(),
        embedder=FakeEmbedder(),
        store=InMemoryVectorStore(),
    )

    assert result.chunks_indexed == 0
    assert result.vectors_upserted == 0


def test_ensure_indexed_skips_vendored_dirs(tmp_path: Path) -> None:
    _write(tmp_path / "app.py", "ok\n")
    _write(tmp_path / "node_modules" / "pkg" / "index.js", "bad\n")
    task_id = uuid4()
    store = InMemoryVectorStore()

    result = ensure_indexed(
        workspace_root=tmp_path,
        task_id=task_id,
        embedder=FakeEmbedder(),
        store=store,
    )

    assert result.chunks_indexed == 1
    matches = store.query(namespace_for_task(task_id), [1.0, 1.0], top_k=10)
    assert [m.metadata["file_path"] for m in matches] == ["app.py"]


def test_ensure_indexed_optional_metadata(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "x = 1\n")
    task_id = uuid4()
    repo_id = uuid4()
    store = InMemoryVectorStore()

    ensure_indexed(
        workspace_root=tmp_path,
        task_id=task_id,
        embedder=FakeEmbedder(),
        store=store,
        repository_id=repo_id,
        commit_sha="abc123",
    )

    matches = store.query(namespace_for_task(task_id), [1.0, 1.0], top_k=1)
    assert matches[0].metadata["repository_id"] == str(repo_id)
    assert matches[0].metadata["commit_sha"] == "abc123"


def test_ensure_indexed_rejects_embedder_length_mismatch(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "x = 1\n")
    _write(tmp_path / "b.py", "y = 2\n")

    with pytest.raises(RuntimeError, match="embedder returned"):
        ensure_indexed(
            workspace_root=tmp_path,
            task_id=uuid4(),
            embedder=MismatchedEmbedder(),
            store=InMemoryVectorStore(),
        )


def test_ensure_indexed_idempotent_ids(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "x = 1\n")
    task_id = uuid4()
    store = InMemoryVectorStore()

    first = ensure_indexed(
        workspace_root=tmp_path,
        task_id=task_id,
        embedder=FakeEmbedder(),
        store=store,
    )
    second = ensure_indexed(
        workspace_root=tmp_path,
        task_id=task_id,
        embedder=FakeEmbedder(),
        store=store,
    )

    assert first.chunks_indexed == second.chunks_indexed
    matches = store.query(namespace_for_task(task_id), [1.0, 1.0], top_k=20)
    assert len(matches) == first.chunks_indexed


def test_semantic_search_ranks_relevant_file_first(tmp_path: Path) -> None:
    _write(tmp_path / "cookies.py", "def persist_cookie():\n    save_cookie()\n")
    _write(tmp_path / "math.py", "def add(a, b):\n    return a + b\n")
    task_id = uuid4()
    store = InMemoryVectorStore()
    embedder = KeywordEmbedder()

    ensure_indexed(
        workspace_root=tmp_path,
        task_id=task_id,
        embedder=embedder,
        store=store,
    )

    hits = semantic_search(
        task_id=task_id,
        query="cookie persistence",
        embedder=embedder,
        store=store,
        top_k=5,
    )

    assert hits
    assert hits[0].file_path == "cookies.py"
    assert hits[0].start_line >= 1
    assert hits[0].snippet
    assert hits[0].score >= hits[-1].score


def test_semantic_search_path_prefix_filter(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "cookie jar\n")
    _write(tmp_path / "tests" / "b.py", "cookie jar\n")
    task_id = uuid4()
    store = InMemoryVectorStore()
    embedder = KeywordEmbedder()

    ensure_indexed(
        workspace_root=tmp_path,
        task_id=task_id,
        embedder=embedder,
        store=store,
    )

    hits = semantic_search(
        task_id=task_id,
        query="cookie",
        embedder=embedder,
        store=store,
        path_prefix="src",
        top_k=5,
    )

    assert hits
    assert all(h.file_path.startswith("src/") for h in hits)


def test_semantic_search_empty_query_raises() -> None:
    with pytest.raises(ValueError, match="query"):
        semantic_search(
            task_id=uuid4(),
            query="   ",
            embedder=KeywordEmbedder(),
            store=InMemoryVectorStore(),
        )


def test_semantic_search_empty_index_returns_empty() -> None:
    hits = semantic_search(
        task_id=uuid4(),
        query="anything",
        embedder=KeywordEmbedder(),
        store=InMemoryVectorStore(),
        top_k=5,
    )
    assert hits == []
