from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from app.config import get_settings
from app.retrieval.embeddings import (
    EmbeddingClient,
    EmbeddingError,
    OpenAIEmbeddingClient,
)
from app.retrieval.search import semantic_search
from app.retrieval.vector_store import (
    VectorStore,
    VectorStoreError,
    PineconeVectorStore,
)
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.paths import WorkspacePathError, resolve_workspace_path


class SemanticSearchInput(BaseModel):
    query: str = Field(
        min_length=1,
        description=(
            "Natural-language or conceptual description of the code to find. "
            "Prefer this for behavior and concepts without exact identifiers; "
            "use search_code for exact strings, function names, and error messages."
        ),
    )
    path: str = Field(
        default=".",
        min_length=1,
        description=(
            "Relative directory prefix to restrict results. "
            "Use '.' for the whole workspace; never pass an empty path."
        ),
    )
    max_results: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum number of chunks to return.",
    )


class SemanticSearchTool(Tool):
    name: ClassVar[str] = "semantic_search"
    description: ClassVar[str] = (
        "Find code chunks by meaning using embeddings. Prefer this when the user "
        "describes behavior or concepts without exact identifiers. Prefer "
        "search_code for exact strings, function names, and error messages. "
        "Returns file paths, line ranges, relevance scores, and short snippets — "
        "use read_file with start_line for full content."
    )
    input_model: ClassVar[type[BaseModel]] = SemanticSearchInput
    mutating: ClassVar[bool] = False

    def __init__(
        self,
        *,
        embedder: EmbeddingClient | None = None,
        store: VectorStore | None = None,
        top_k: int | None = None,
    ) -> None:
        settings = get_settings()
        self._embedder = embedder or OpenAIEmbeddingClient(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            batch_size=settings.retrieval_embed_batch_size,
        )
        self._store = store or PineconeVectorStore(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index,
        )
        self._default_top_k = (
            top_k if top_k is not None else settings.retrieval_search_top_k
        )

    def execute(self, context: ToolContext, arguments: BaseModel) -> ToolResult:
        assert isinstance(arguments, SemanticSearchInput)
        try:
            resolve_workspace_path(
                context.workspace_root, arguments.path, must_exist=True
            )
        except WorkspacePathError as exc:
            return ToolResult(ok=False, data=None, error=str(exc))

        top_k = (
            arguments.max_results
            if arguments.max_results is not None
            else self._default_top_k
        )
        top_k = min(top_k, self._default_top_k)

        try:
            hits = semantic_search(
                task_id=context.task_id,
                query=arguments.query,
                embedder=self._embedder,
                store=self._store,
                path_prefix=arguments.path,
                top_k=top_k,
            )
        except (EmbeddingError, VectorStoreError, ValueError) as exc:
            return ToolResult(ok=False, data=None, error=str(exc))

        if not hits:
            return ToolResult(
                ok=False,
                data={"matches": [], "truncated": False},
                error="no semantic matches found (index may be empty or query unmatched)",
            )

        return ToolResult(
            ok=True,
            data={
                "matches": [
                    {
                        "file_path": hit.file_path,
                        "start_line": hit.start_line,
                        "end_line": hit.end_line,
                        "score": hit.score,
                        "snippet": hit.snippet,
                        "language": hit.language,
                    }
                    for hit in hits
                ],
                "truncated": False,
            },
        )
