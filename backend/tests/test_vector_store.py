from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pinecone.exceptions import PineconeException

from app.retrieval.vector_store import (
    InMemoryVectorStore,
    PineconeVectorStore,
    VectorRecord,
    VectorStoreError,
    namespace_for_task,
)


def _record(
    id: str,
    values: list[float],
    *,
    commit_sha: str = "abc123",
    language: str = "Python",
) -> VectorRecord:
    return VectorRecord(
        id=id,
        values=values,
        metadata={
            "commit_sha": commit_sha,
            "file_path": "src/foo.py",
            "language": language,
        },
    )


def test_namespace_for_task_is_stable() -> None:
    task_id = uuid4()
    assert namespace_for_task(task_id) == f"task-{task_id}"


def test_in_memory_query_ranks_closest_first() -> None:
    store = InMemoryVectorStore()
    ns = "task-one"
    store.upsert(
        ns,
        [
            _record("far", [1.0, 0.0]),
            _record("near", [0.9, 0.1]),
        ],
    )

    matches = store.query(ns, [1.0, 0.0], top_k=2)

    assert [m.id for m in matches] == ["far", "near"]
    assert matches[0].score > matches[1].score


def test_in_memory_query_respects_top_k_and_filter() -> None:
    store = InMemoryVectorStore()
    ns = "task-one"
    store.upsert(
        ns,
        [
            _record("py", [1.0, 0.0], language="Python"),
            _record("ts", [0.99, 0.0], language="TypeScript"),
        ],
    )

    matches = store.query(
        ns, [1.0, 0.0], top_k=1, filter={"language": "TypeScript"}
    )

    assert len(matches) == 1
    assert matches[0].id == "ts"


def test_in_memory_namespaces_are_isolated() -> None:
    store = InMemoryVectorStore()
    store.upsert("task-a", [_record("a", [1.0, 0.0])])
    store.upsert("task-b", [_record("b", [1.0, 0.0])])

    assert [m.id for m in store.query("task-a", [1.0, 0.0], top_k=5)] == ["a"]
    assert store.namespace_commit_sha("task-a") == "abc123"
    assert store.namespace_commit_sha("missing") is None

    store.delete_namespace("task-a")
    assert store.query("task-a", [1.0, 0.0], top_k=5) == []
    assert store.namespace_commit_sha("task-a") is None
    assert [m.id for m in store.query("task-b", [1.0, 0.0], top_k=5)] == ["b"]


def test_pinecone_unconfigured_raises() -> None:
    store = PineconeVectorStore(api_key="", index_name="")
    with pytest.raises(VectorStoreError, match="not configured"):
        store.query("task-x", [0.1], top_k=1)


def test_pinecone_query_maps_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PineconeVectorStore(api_key="pc-test", index_name="code-index")
    fake_index = SimpleNamespace(
        query=MagicMock(
            return_value=SimpleNamespace(
                matches=[
                    SimpleNamespace(
                        id="vec-1",
                        score=0.82,
                        metadata={"file_path": "src/foo.py", "commit_sha": "abc"},
                    )
                ]
            )
        )
    )
    monkeypatch.setattr(store, "_get_index", lambda: fake_index)

    matches = store.query("task-x", [0.1, 0.2], top_k=3, filter={"commit_sha": "abc"})

    assert matches[0].id == "vec-1"
    assert matches[0].score == 0.82
    assert matches[0].metadata["file_path"] == "src/foo.py"
    kwargs = fake_index.query.call_args.kwargs
    assert kwargs["include_metadata"] is True
    assert kwargs["namespace"] == "task-x"
    assert kwargs["filter"] == {"commit_sha": "abc"}


def test_pinecone_namespace_commit_sha_reads_one_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PineconeVectorStore(api_key="pc-test", index_name="code-index")
    page = SimpleNamespace(vectors=[SimpleNamespace(id="sha:src/foo.py:1:80")])
    fetched = SimpleNamespace(
        vectors={
            "sha:src/foo.py:1:80": SimpleNamespace(
                metadata={"commit_sha": "deadbeef"}
            )
        }
    )
    fake_index = SimpleNamespace(
        list=MagicMock(return_value=iter([page])),
        fetch=MagicMock(return_value=fetched),
    )
    monkeypatch.setattr(store, "_get_index", lambda: fake_index)

    assert store.namespace_commit_sha("task-x") == "deadbeef"
    fake_index.list.assert_called_once_with(namespace="task-x", limit=1)
    fake_index.fetch.assert_called_once_with(
        ids=["sha:src/foo.py:1:80"], namespace="task-x"
    )


def test_pinecone_wraps_sdk_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PineconeVectorStore(api_key="pc-test", index_name="code-index")
    fake_index = SimpleNamespace(
        upsert=MagicMock(side_effect=PineconeException("boom"))
    )
    monkeypatch.setattr(store, "_get_index", lambda: fake_index)

    with pytest.raises(VectorStoreError, match="upsert failed"):
        store.upsert("task-x", [_record("a", [1.0])])
