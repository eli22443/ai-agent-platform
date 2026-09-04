from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.retrieval.chunking import CodeChunk, chunk_workspace
from app.retrieval.embeddings import EmbeddingClient
from app.retrieval.vector_store import (
    VectorRecord,
    VectorStore,
    namespace_for_task,
)

logger = logging.getLogger(__name__)

_SNIPPET_MAX = 500


@dataclass(frozen=True)
class IndexResult:
    chunks_indexed: int
    vectors_upserted: int
    duration_ms: int


def ensure_indexed(
    *,
    workspace_root: Path,
    task_id: UUID,
    embedder: EmbeddingClient,
    store: VectorStore,
    repository_id: UUID | None = None,
    commit_sha: str | None = None,
    chunk_lines: int = 80,
    overlap: int = 20,
    max_file_bytes: int = 256_000,
) -> IndexResult:
    """Chunk the workspace, embed chunks, and upsert into task-{task_id}."""
    started = time.perf_counter()
    namespace = namespace_for_task(task_id)

    chunks = chunk_workspace(
        workspace_root,
        chunk_lines=chunk_lines,
        overlap=overlap,
        max_file_bytes=max_file_bytes,
    )
    if not chunks:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "indexed empty workspace task_id=%s duration_ms=%d",
            task_id,
            duration_ms,
        )
        return IndexResult(
            chunks_indexed=0, vectors_upserted=0, duration_ms=duration_ms
        )

    vectors = embedder.embed_texts([chunk.text for chunk in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError(
            f"embedder returned {len(vectors)} vectors for {len(chunks)} chunks"
        )

    records = [
        _to_record(
            chunk,
            values,
            task_id=task_id,
            repository_id=repository_id,
            commit_sha=commit_sha,
        )
        for chunk, values in zip(chunks, vectors, strict=True)
    ]
    upserted = store.upsert(namespace, records)

    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "indexed task_id=%s chunks=%d vectors=%d duration_ms=%d",
        task_id,
        len(chunks),
        upserted,
        duration_ms,
    )
    return IndexResult(
        chunks_indexed=len(chunks),
        vectors_upserted=upserted,
        duration_ms=duration_ms,
    )


def _vector_id(task_id: UUID, chunk: CodeChunk) -> str:
    path_digest = hashlib.sha1(chunk.file_path.encode("utf-8")).hexdigest()[:16]
    return f"{task_id}:{path_digest}:{chunk.start_line}:{chunk.end_line}"


def _to_record(
    chunk: CodeChunk,
    values: list[float],
    *,
    task_id: UUID,
    repository_id: UUID | None,
    commit_sha: str | None,
) -> VectorRecord:
    metadata: dict[str, object] = {
        "task_id": str(task_id),
        "file_path": chunk.file_path,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "snippet": chunk.text[:_SNIPPET_MAX],
    }
    if chunk.language is not None:
        metadata["language"] = chunk.language
    if repository_id is not None:
        metadata["repository_id"] = str(repository_id)
    if commit_sha is not None:
        metadata["commit_sha"] = commit_sha
    return VectorRecord(
        id=_vector_id(task_id, chunk),
        values=values,
        metadata=metadata,
    )
