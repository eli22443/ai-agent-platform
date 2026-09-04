from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.retrieval.embeddings import EmbeddingClient
from app.retrieval.vector_store import VectorMatch, VectorStore, namespace_for_task

# Pinecone has no metadata prefix operator; over-fetch then filter in Python.
_PATH_FILTER_OVERFETCH = 3


@dataclass(frozen=True)
class ScoredChunk:
    file_path: str
    start_line: int
    end_line: int
    score: float
    snippet: str
    language: str | None


def semantic_search(
    *,
    task_id: UUID,
    query: str,
    embedder: EmbeddingClient,
    store: VectorStore,
    path_prefix: str = ".",
    top_k: int = 10,
) -> list[ScoredChunk]:
    """Embed the query and return ranked code chunks for this task's namespace."""
    if not query.strip():
        raise ValueError("query must be non-empty")
    if top_k < 1:
        raise ValueError("top_k must be >= 1")

    namespace = namespace_for_task(task_id)
    query_vector = embedder.embed_texts([query])[0]

    needs_path_filter = path_prefix not in ("", ".")
    fetch_k = top_k * _PATH_FILTER_OVERFETCH if needs_path_filter else top_k

    matches = store.query(namespace, query_vector, top_k=fetch_k)
    if needs_path_filter:
        normalized = path_prefix.strip("/").replace("\\", "/")
        matches = [
            m
            for m in matches
            if _path_matches_prefix(str(m.metadata.get("file_path", "")), normalized)
        ]

    chunks = [_to_scored_chunk(match) for match in matches]
    chunks.sort(key=lambda c: c.score, reverse=True)
    return chunks[:top_k]


def _path_matches_prefix(file_path: str, prefix: str) -> bool:
    path = file_path.replace("\\", "/")
    return path == prefix or path.startswith(prefix + "/")


def _to_scored_chunk(match: VectorMatch) -> ScoredChunk:
    metadata = match.metadata
    language = metadata.get("language")
    return ScoredChunk(
        file_path=str(metadata.get("file_path", "")),
        start_line=int(metadata.get("start_line", 0)),
        end_line=int(metadata.get("end_line", 0)),
        score=float(match.score),
        snippet=str(metadata.get("snippet", "")),
        language=str(language) if language is not None else None,
    )
