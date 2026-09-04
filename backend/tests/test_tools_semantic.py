from pathlib import Path
from uuid import uuid4

from app.retrieval.indexer import ensure_indexed
from app.retrieval.vector_store import InMemoryVectorStore
from app.tools.base import ToolContext
from app.tools.semantic import SemanticSearchInput, SemanticSearchTool


class KeywordEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0] if "cookie" in text.lower() else [0.0, 1.0] for text in texts
        ]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _context(workspace: Path, task_id=None) -> ToolContext:
    return ToolContext(
        workspace_root=workspace.resolve(),
        task_id=task_id or uuid4(),
    )


def test_semantic_search_tool_returns_matches(tmp_path: Path) -> None:
    _write(tmp_path / "cookies.py", "def persist_cookie():\n    return 1\n")
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

    tool = SemanticSearchTool(embedder=embedder, store=store, top_k=5)
    result = tool.execute(
        _context(tmp_path, task_id),
        SemanticSearchInput(query="cookie persistence"),
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data["matches"][0]["file_path"] == "cookies.py"
    assert "start_line" in result.data["matches"][0]
    assert "snippet" in result.data["matches"][0]


def test_semantic_search_tool_rejects_path_escape(tmp_path: Path) -> None:
    tool = SemanticSearchTool(
        embedder=KeywordEmbedder(),
        store=InMemoryVectorStore(),
    )
    result = tool.execute(
        _context(tmp_path),
        SemanticSearchInput(query="cookie", path="../outside"),
    )

    assert result.ok is False
    assert result.error


def test_semantic_search_tool_empty_index_returns_error(tmp_path: Path) -> None:
    tool = SemanticSearchTool(
        embedder=KeywordEmbedder(),
        store=InMemoryVectorStore(),
        top_k=5,
    )
    result = tool.execute(
        _context(tmp_path),
        SemanticSearchInput(query="cookie"),
    )

    assert result.ok is False
    assert "no semantic matches" in (result.error or "")
    assert result.data == {"matches": [], "truncated": False}


def test_semantic_search_tool_path_prefix(tmp_path: Path) -> None:
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

    tool = SemanticSearchTool(embedder=embedder, store=store, top_k=5)
    result = tool.execute(
        _context(tmp_path, task_id),
        SemanticSearchInput(query="cookie", path="src"),
    )

    assert result.ok is True
    assert all(m["file_path"].startswith("src/") for m in result.data["matches"])
