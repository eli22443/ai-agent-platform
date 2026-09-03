from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from pinecone import Pinecone
from pinecone.exceptions import NotFoundException, PineconeException

logger = logging.getLogger(__name__)


class VectorStoreError(Exception):
    """Vector store failure. Message is safe to surface upstream."""


@dataclass(frozen=True)
class VectorRecord:
    id: str
    values: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorMatch:
    id: str
    score: float
    metadata: dict[str, Any]


class VectorStore(Protocol):
    def upsert(self, namespace: str, vectors: list[VectorRecord]) -> int: ...

    def query(
        self,
        namespace: str,
        vector: list[float],
        *,
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorMatch]: ...

    def delete_namespace(self, namespace: str) -> None: ...

    def namespace_commit_sha(self, namespace: str) -> str | None: ...


def namespace_for_task(task_id: UUID) -> str:
    return f"task-{task_id}"


class PineconeVectorStore:
    def __init__(self, *, api_key: str, index_name: str) -> None:
        self._api_key = api_key
        self._index_name = index_name
        self._index = None

    def _get_index(self):
        if not self._api_key or not self._index_name:
            raise VectorStoreError("Pinecone is not configured.")
        if self._index is None:
            try:
                self._index = Pinecone(api_key=self._api_key).Index(self._index_name)
            except PineconeException as exc:
                logger.exception("Pinecone index handle failed")
                raise VectorStoreError("Failed to connect to Pinecone.") from exc
        return self._index

    def upsert(self, namespace: str, vectors: list[VectorRecord]) -> int:
        if not vectors:
            return 0
        payload = [
            {"id": v.id, "values": v.values, "metadata": v.metadata} for v in vectors
        ]
        try:
            self._get_index().upsert(
                vectors=payload,
                namespace=namespace,
                show_progress=False,
            )
        except PineconeException as exc:
            logger.exception("Pinecone upsert failed")
            raise VectorStoreError("Pinecone upsert failed.") from exc
        return len(payload)

    def query(
        self,
        namespace: str,
        vector: list[float],
        *,
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        try:
            response = self._get_index().query(
                vector=vector,
                top_k=top_k,
                namespace=namespace,
                filter=filter,
                include_metadata=True,
                include_values=False,
            )
        except PineconeException as exc:
            logger.exception("Pinecone query failed")
            raise VectorStoreError("Pinecone query failed.") from exc

        matches = getattr(response, "matches", None) or []
        return [
            VectorMatch(
                id=item.id,
                score=float(item.score),
                metadata=dict(item.metadata or {}),
            )
            for item in matches
        ]

    def delete_namespace(self, namespace: str) -> None:
        try:
            self._get_index().delete_namespace(name=namespace)
        except NotFoundException:
            logger.info("namespace %s absent; nothing to delete", namespace)
        except PineconeException as exc:
            logger.exception("Pinecone namespace delete failed")
            raise VectorStoreError("Pinecone delete failed.") from exc

    def namespace_commit_sha(self, namespace: str) -> str | None:
        """
        Workspace HEAD SHA stored on any vector in this namespace, or None if empty.
        list() is a page iterator and fetch() returns a dict; next() takes the first item only.
        """

        index = self._get_index()
        try:
            page = next(index.list(namespace=namespace, limit=1), None)
            if page is None:
                return None
            items = list(page.vectors or [])
            if not items or not items[0].id:
                return None
            fetched = index.fetch(ids=[items[0].id], namespace=namespace)
            record = next(iter((fetched.vectors or {}).values()), None)
            if record is None:
                return None
            sha = (record.metadata or {}).get("commit_sha")
            return str(sha) if sha else None
        except NotFoundException:
            return None
        except PineconeException as exc:
            logger.exception("Pinecone namespace inspection failed")
            raise VectorStoreError("Pinecone query failed.") from exc


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, VectorRecord]] = {}

    def upsert(self, namespace: str, vectors: list[VectorRecord]) -> int:
        bucket = self._namespaces.setdefault(namespace, {})
        for record in vectors:
            bucket[record.id] = record
        return len(vectors)

    def query(
        self,
        namespace: str,
        vector: list[float],
        *,
        top_k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        bucket = self._namespaces.get(namespace, {})
        scored = [
            VectorMatch(
                id=record.id,
                score=_cosine(vector, record.values),
                metadata=dict(record.metadata),
            )
            for record in bucket.values()
            if _matches(record.metadata, filter)
        ]
        scored.sort(key=lambda match: match.score, reverse=True)
        return scored[:top_k]

    def delete_namespace(self, namespace: str) -> None:
        self._namespaces.pop(namespace, None)

    def namespace_commit_sha(self, namespace: str) -> str | None:
        record = next(iter(self._namespaces.get(namespace, {}).values()), None)
        if record is None:
            return None
        sha = record.metadata.get("commit_sha")
        return str(sha) if sha else None


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(x * y for x, y in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(y * y for y in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _matches(metadata: dict[str, Any], filter: dict[str, Any] | None) -> bool:
    if not filter:
        return True
    return all(metadata.get(key) == value for key, value in filter.items())
