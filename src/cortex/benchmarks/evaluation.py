"""Information Retrieval (IR) quality and reranking evaluation harness for agent-cortex.

Computes HitRate@K, Recall@K, MRR@K (Mean Reciprocal Rank), and nDCG@K (Normalized
Discounted Cumulative Gain) across Stage 1 (Vector, FTS, Hybrid RRF) and Stage 2
(Cross-Encoder Reranker) pipelines.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from cortex.benchmarks.latency import generate_synthetic_benchmark_dataset
from cortex.embeddings.engine import EmbeddingEngine
from cortex.models.chunk import ChunkCategory, DocumentChunk
from cortex.retrieval.pipeline import HybridRetrievalPipeline, build_where_clause


class EvaluationQuery(BaseModel):
    """Ground-truth query specification for retrieval quality evaluation."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    query: str = Field(..., description="Natural language or technical search query")
    relevant_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Deterministic chunk IDs considered relevant ground-truth hits",
    )
    category: ChunkCategory | None = Field(
        default=None,
        description="Optional category filter applied during evaluation",
    )
    repo: str | None = Field(
        default=None,
        description="Optional repository filter applied during evaluation",
    )


class StageEvaluationMetrics(BaseModel):
    """Aggregated IR quality and latency metrics for a single retrieval stage."""

    model_config = ConfigDict(frozen=True)

    stage: str
    k: int
    queries_evaluated: int
    hit_rate_at_k: float
    recall_at_k: float
    mrr_at_k: float
    ndcg_at_k: float
    mean_latency_ms: float


class RetrievalEvaluationReport(BaseModel):
    """Complete retrieval and reranking quality benchmark report."""

    model_config = ConfigDict(frozen=True)

    profile: str
    k: int
    total_chunks: int
    queries_evaluated: int
    stage1_vector: StageEvaluationMetrics
    stage1_fts: StageEvaluationMetrics
    stage1_hybrid: StageEvaluationMetrics
    stage2_reranked: StageEvaluationMetrics | None = None
    rerank_mrr_lift: float = 0.0
    rerank_ndcg_lift: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def hit_rate_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float:
    """Compute binary HitRate@K (1.0 if at least one relevant item appears in top-K, else 0.0)."""
    if k <= 0 or not relevant_ids or not retrieved_ids:
        return 0.0
    rel_set = set(relevant_ids)
    top_k = retrieved_ids[:k]
    return 1.0 if any(doc_id in rel_set for doc_id in top_k) else 0.0


def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float:
    """Compute Recall@K: fraction of ground-truth relevant items found in top-K results."""
    if k <= 0 or not relevant_ids:
        return 0.0
    rel_set = set(relevant_ids)
    if not rel_set:
        return 0.0
    top_k = set(retrieved_ids[:k])
    hits = len(rel_set.intersection(top_k))
    return hits / len(rel_set)


def mrr_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float:
    """Compute Reciprocal Rank at cutoff K (1 / rank of first relevant result)."""
    if k <= 0 or not relevant_ids or not retrieved_ids:
        return 0.0
    rel_set = set(relevant_ids)
    for rank, doc_id in enumerate(retrieved_ids[:k], start=1):
        if doc_id in rel_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float:
    """Compute binary Normalized Discounted Cumulative Gain (nDCG@K)."""
    if k <= 0 or not relevant_ids or not retrieved_ids:
        return 0.0
    rel_set = set(relevant_ids)
    if not rel_set:
        return 0.0

    # Deduplicate retrieved_ids while preserving ranking order
    seen: set[str] = set()
    dcg = 0.0
    for idx, doc_id in enumerate(retrieved_ids[:k]):
        if doc_id in rel_set and doc_id not in seen:
            seen.add(doc_id)
            dcg += 1.0 / math.log2(idx + 2)

    ideal_hits = min(len(rel_set), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def generate_synthetic_evaluation_dataset(
    num_repos: int = 3,
    chunks_per_repo: int = 10,
    dim: int = 384,
    embedding_engine: EmbeddingEngine | None = None,
) -> tuple[list[DocumentChunk], list[EvaluationQuery]]:
    """Generate paired synthetic chunks and ground-truth evaluation queries."""
    chunks = generate_synthetic_benchmark_dataset(
        num_repos=num_repos,
        chunks_per_repo=chunks_per_repo,
        dim=dim,
        embedding_engine=embedding_engine,
    )

    topic_queries: list[tuple[str, str]] = [
        ("auth", "JWT authentication Bearer token validation and claim decoding"),
        ("database", "PostgreSQL database connection pooling with asyncpg and retry backoff"),
        ("api", "GET /api/v1/orders order processing and inventory status"),
        ("infra", "Docker Compose services configuration for redis worker and vector memory"),
        ("storage", "LanceDB Apache Arrow embedded vector storage compaction and indexing"),
    ]

    eval_queries: list[EvaluationQuery] = []
    for topic_tag, query_text in topic_queries:
        matching_ids = [c.id for c in chunks if topic_tag in c.tags]
        if matching_ids:
            eval_queries.append(
                EvaluationQuery(
                    query=query_text,
                    relevant_ids=matching_ids,
                )
            )

    return chunks, eval_queries


def _aggregate_stage_metrics(
    stage: str,
    k: int,
    retrieved_lists: Sequence[Sequence[str]],
    relevant_lists: Sequence[Sequence[str]],
    latencies_ms: Sequence[float],
) -> StageEvaluationMetrics:
    """Aggregate per-query IR metrics into a StageEvaluationMetrics summary."""
    count = len(retrieved_lists)
    if count == 0:
        return StageEvaluationMetrics(
            stage=stage,
            k=k,
            queries_evaluated=0,
            hit_rate_at_k=0.0,
            recall_at_k=0.0,
            mrr_at_k=0.0,
            ndcg_at_k=0.0,
            mean_latency_ms=0.0,
        )

    total_hit = 0.0
    total_recall = 0.0
    total_mrr = 0.0
    total_ndcg = 0.0

    for retrieved, relevant in zip(retrieved_lists, relevant_lists, strict=True):
        total_hit += hit_rate_at_k(retrieved, relevant, k)
        total_recall += recall_at_k(retrieved, relevant, k)
        total_mrr += mrr_at_k(retrieved, relevant, k)
        total_ndcg += ndcg_at_k(retrieved, relevant, k)

    mean_lat = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0

    return StageEvaluationMetrics(
        stage=stage,
        k=k,
        queries_evaluated=count,
        hit_rate_at_k=round(total_hit / count, 4),
        recall_at_k=round(total_recall / count, 4),
        mrr_at_k=round(total_mrr / count, 4),
        ndcg_at_k=round(total_ndcg / count, 4),
        mean_latency_ms=round(mean_lat, 2),
    )


def run_retrieval_evaluation(
    pipeline: HybridRetrievalPipeline,
    eval_queries: Sequence[EvaluationQuery],
    k: int = 5,
    rerank: bool = True,
) -> RetrievalEvaluationReport:
    """Evaluate Stage 1 (Vector, FTS, Hybrid RRF) and Stage 2 (Cross-Encoder) IR quality."""
    if k <= 0:
        msg = "Evaluation cutoff k must be greater than 0."
        raise ValueError(msg)

    total_chunks = pipeline.storage.count_chunks(table_name=pipeline.table_name)
    has_reranker = rerank and pipeline.reranker is not None and pipeline.reranker.is_enabled

    vec_retrieved: list[list[str]] = []
    fts_retrieved: list[list[str]] = []
    hybrid_retrieved: list[list[str]] = []
    rerank_retrieved: list[list[str]] = []
    relevant_lists: list[list[str]] = []

    vec_latencies: list[float] = []
    fts_latencies: list[float] = []
    hybrid_latencies: list[float] = []
    rerank_latencies: list[float] = []

    for eq in eval_queries:
        relevant_lists.append(list(eq.relevant_ids))
        where_clause = build_where_clause(category=eq.category, repo=eq.repo)

        # 1. Stage 1 Dense Vector
        t0 = time.perf_counter()
        q_vec = pipeline.embeddings.embed_query(eq.query)
        vec_rows = pipeline.storage.vector_search(
            query_vector=q_vec,
            limit=k,
            where=where_clause,
            table_name=pipeline.table_name,
        )
        vec_latencies.append((time.perf_counter() - t0) * 1000.0)
        vec_retrieved.append([str(r["id"]) for r in vec_rows])

        # 2. Stage 1 Sparse FTS
        t0 = time.perf_counter()
        fts_rows = pipeline.storage.fts_search(
            query_text=eq.query,
            limit=k,
            where=where_clause,
            table_name=pipeline.table_name,
        )
        fts_latencies.append((time.perf_counter() - t0) * 1000.0)
        fts_retrieved.append([str(r["id"]) for r in fts_rows])

        # 3. Stage 1 Hybrid RRF
        t0 = time.perf_counter()
        hybrid_chunks = pipeline.search_stage1(
            query=eq.query,
            limit=k,
            category=eq.category,
            repo=eq.repo,
        )
        hybrid_latencies.append((time.perf_counter() - t0) * 1000.0)
        hybrid_retrieved.append([c.id for c in hybrid_chunks])

        # 4. Stage 2 Cross-Encoder Reranked
        if has_reranker:
            t0 = time.perf_counter()
            reranked_chunks = pipeline.search(
                query=eq.query,
                limit=k,
                category=eq.category,
                repo=eq.repo,
                rerank=True,
            )
            rerank_latencies.append((time.perf_counter() - t0) * 1000.0)
            rerank_retrieved.append([c.id for c in reranked_chunks])

    s1_vec = _aggregate_stage_metrics(
        "stage1_vector", k, vec_retrieved, relevant_lists, vec_latencies
    )
    s1_fts = _aggregate_stage_metrics("stage1_fts", k, fts_retrieved, relevant_lists, fts_latencies)
    s1_hyb = _aggregate_stage_metrics(
        "stage1_hybrid", k, hybrid_retrieved, relevant_lists, hybrid_latencies
    )

    s2_rerank: StageEvaluationMetrics | None = None
    mrr_lift = 0.0
    ndcg_lift = 0.0
    if has_reranker:
        s2_rerank = _aggregate_stage_metrics(
            "stage2_reranked", k, rerank_retrieved, relevant_lists, rerank_latencies
        )
        mrr_lift = round(s2_rerank.mrr_at_k - s1_hyb.mrr_at_k, 4)
        ndcg_lift = round(s2_rerank.ndcg_at_k - s1_hyb.ndcg_at_k, 4)

    return RetrievalEvaluationReport(
        profile=pipeline.embeddings.profile.name,
        k=k,
        total_chunks=total_chunks,
        queries_evaluated=len(eval_queries),
        stage1_vector=s1_vec,
        stage1_fts=s1_fts,
        stage1_hybrid=s1_hyb,
        stage2_reranked=s2_rerank,
        rerank_mrr_lift=mrr_lift,
        rerank_ndcg_lift=ndcg_lift,
    )
