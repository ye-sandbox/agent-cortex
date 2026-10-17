"""Stage 1 Hybrid Retrieval pipeline with Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from cortex.config.loader import RetrievalConfig
from cortex.embeddings.engine import EmbeddingEngine
from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    SearchResultChunk,
)
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)


def build_where_clause(
    scopes: Sequence[ChunkScope] | None = None,
    category: ChunkCategory | None = None,
    repo: str | None = None,
) -> str | None:
    """Build a sanitized SQL WHERE clause for LanceDB query filtering."""
    clauses: list[str] = []

    # Scopes: default to INTERNAL and PUBLIC if omitted
    effective_scopes = (
        list(scopes) if scopes is not None else [ChunkScope.INTERNAL, ChunkScope.PUBLIC]
    )
    if effective_scopes:
        formatted_scopes = ", ".join(f"'{s.value}'" for s in effective_scopes)
        clauses.append(f"scope IN ({formatted_scopes})")

    # Category filter
    if category is not None:
        clauses.append(f"category = '{category.value}'")

    # Repository filter
    if repo is not None and repo.strip():
        safe_repo = repo.strip().replace("'", "''")
        clauses.append(f"repo = '{safe_repo}'")

    if not clauses:
        return None

    return " AND ".join(clauses)


class HybridRetrievalPipeline:
    """Combines dense vector similarity and sparse BM25 search via Reciprocal Rank Fusion."""

    def __init__(
        self,
        storage: StorageManager,
        embeddings: EmbeddingEngine,
        config: RetrievalConfig | None = None,
        table_name: str = "chunks",
    ) -> None:
        """Initialize hybrid retrieval pipeline."""
        self.storage = storage
        self.embeddings = embeddings
        self.config = config or RetrievalConfig()
        self.table_name = table_name

    def search(
        self,
        query: str,
        limit: int | None = None,
        scopes: Sequence[ChunkScope] | None = None,
        include_archived: bool = False,
        category: ChunkCategory | None = None,
        repo: str | None = None,
    ) -> list[SearchResultChunk]:
        """Execute Stage 1 Hybrid retrieval combining dense and sparse search."""
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        effective_limit = limit if limit is not None else self.config.default_limit
        candidate_pool_size = max(effective_limit * 3, 30)

        where_clause = build_where_clause(scopes=scopes, category=category, repo=repo)

        # 1. Compute query vector & execute dense search
        query_vector = self.embeddings.embed_query(cleaned_query)
        dense_results = self.storage.vector_search(
            query_vector=query_vector,
            limit=candidate_pool_size,
            where=where_clause,
            table_name=self.table_name,
        )

        # 2. Execute sparse FTS search
        sparse_results = self.storage.fts_search(
            query_text=cleaned_query,
            limit=candidate_pool_size,
            where=where_clause,
            table_name=self.table_name,
        )

        # 3. Reciprocal Rank Fusion (RRF)
        # Formula: RRF(d) = sum_m [ w_m / (k + rank_m(d)) ]
        k = self.config.k
        w_dense = self.config.weight_dense
        w_sparse = self.config.weight_sparse

        fused_scores: dict[str, float] = {}
        records_by_id: dict[str, dict[str, Any]] = {}

        # Accumulate dense ranks (1-indexed)
        for rank, item in enumerate(dense_results, start=1):
            item_id = str(item["id"])
            records_by_id[item_id] = item
            fused_scores[item_id] = fused_scores.get(item_id, 0.0) + (w_dense / (k + rank))

        # Accumulate sparse ranks (1-indexed)
        for rank, item in enumerate(sparse_results, start=1):
            item_id = str(item["id"])
            if item_id not in records_by_id:
                records_by_id[item_id] = item
            fused_scores[item_id] = fused_scores.get(item_id, 0.0) + (w_sparse / (k + rank))

        if not records_by_id:
            return []

        # 4. Apply lifecycle penalty and construct SearchResultChunk instances
        results: list[SearchResultChunk] = []
        for item_id, record in records_by_id.items():
            raw_score = fused_scores[item_id]
            lifecycle_str = str(record.get("lifecycle", ChunkLifecycle.ACTIVE.value))

            # Apply archived score penalty unless include_archived is requested
            score = raw_score
            if lifecycle_str == ChunkLifecycle.ARCHIVED.value and not include_archived:
                score *= self.config.archived_penalty

            content_text = str(record.get("content", ""))
            snippet = content_text[:200].strip() + ("..." if len(content_text) > 200 else "")

            results.append(
                SearchResultChunk(
                    id=item_id,
                    repo=str(record.get("repo", "")),
                    file_path=str(record.get("file_path", "")),
                    category=ChunkCategory(str(record.get("category", ChunkCategory.DOC.value))),
                    lifecycle=ChunkLifecycle(lifecycle_str),
                    scope=ChunkScope(str(record.get("scope", ChunkScope.INTERNAL.value))),
                    breadcrumb=str(record.get("breadcrumb", "")),
                    score=round(score, 6),
                    content=content_text,
                    snippet=snippet,
                    tags=[str(t) for t in record.get("tags", [])],
                )
            )

        # 5. Sort by fused score descending and slice to limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:effective_limit]
