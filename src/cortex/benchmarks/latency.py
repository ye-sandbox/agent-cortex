"""Stage 1 and Stage 2 latency benchmarking suite for agent-cortex."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from cortex.embeddings.engine import EmbeddingEngine
from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    DocumentChunk,
)
from cortex.retrieval.pipeline import HybridRetrievalPipeline

logger = logging.getLogger(__name__)

DEFAULT_BENCHMARK_QUERIES: list[str] = [
    "authentication token jwt header validation",
    "docker-compose postgres database service configuration",
    "GET /api/v1/health operational status endpoint",
    "exponential backoff retry strategy with jitter",
    "lancedb vector table compaction and optimize",
]


class LatencyStats(BaseModel):
    """Statistical summary of execution latencies for a retrieval stage."""

    model_config = ConfigDict(frozen=True)

    stage: str
    iterations: int
    min_ms: float
    max_ms: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


class BenchmarkReport(BaseModel):
    """Complete latency benchmark report across retrieval stages."""

    model_config = ConfigDict(frozen=True)

    profile: str
    total_chunks: int
    total_repos: int
    iterations: int
    queries: list[str]
    stage1_vector: LatencyStats
    stage1_fts: LatencyStats
    stage1_hybrid: LatencyStats
    stage2_rerank: LatencyStats | None = None
    end_to_end: LatencyStats
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def _percentile(sorted_data: Sequence[float], pct: float) -> float:
    """Calculate the given percentile value from a pre-sorted sequence of floats."""
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return sorted_data[0]
    rank = (pct / 100.0) * (len(sorted_data) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_data) - 1)
    weight = rank - low
    return sorted_data[low] * (1.0 - weight) + sorted_data[high] * weight


def calculate_latency_stats(stage: str, latencies_ms: Sequence[float]) -> LatencyStats:
    """Calculate min, max, mean, and percentiles for a set of latency measurements."""
    if not latencies_ms:
        return LatencyStats(
            stage=stage,
            iterations=0,
            min_ms=0.0,
            max_ms=0.0,
            mean_ms=0.0,
            p50_ms=0.0,
            p95_ms=0.0,
            p99_ms=0.0,
        )

    sorted_l = sorted(latencies_ms)
    count = len(sorted_l)
    return LatencyStats(
        stage=stage,
        iterations=count,
        min_ms=round(sorted_l[0], 2),
        max_ms=round(sorted_l[-1], 2),
        mean_ms=round(sum(sorted_l) / count, 2),
        p50_ms=round(_percentile(sorted_l, 50.0), 2),
        p95_ms=round(_percentile(sorted_l, 95.0), 2),
        p99_ms=round(_percentile(sorted_l, 99.0), 2),
    )


def generate_synthetic_benchmark_dataset(
    num_repos: int = 5,
    chunks_per_repo: int = 20,
    dim: int = 384,
    embedding_engine: EmbeddingEngine | None = None,
) -> list[DocumentChunk]:
    """Generate synthetic portfolio chunks across categories for benchmark evaluation."""
    chunks: list[DocumentChunk] = []
    categories = [
        ChunkCategory.DOC,
        ChunkCategory.CONTRACT,
        ChunkCategory.INFRA,
        ChunkCategory.INVARIANT,
        ChunkCategory.SOLUTION,
    ]
    scopes = [ChunkScope.INTERNAL, ChunkScope.PUBLIC]

    repo_names = [f"portfolio-service-{i + 1:02d}" for i in range(num_repos)]
    sample_topics = [
        (
            "auth",
            "JWT authentication Bearer token validation and claim decoding",
            ["jwt", "auth", "tokens"],
        ),
        (
            "database",
            "PostgreSQL database connection pooling with asyncpg and retry backoff",
            ["postgres", "asyncpg", "pooling"],
        ),
        (
            "api",
            "GET /api/v1/orders order processing and inventory status",
            ["openapi", "orders", "GET"],
        ),
        (
            "infra",
            "Docker Compose services configuration for redis worker and vector memory",
            ["docker", "compose", "redis"],
        ),
        (
            "storage",
            "LanceDB Apache Arrow embedded vector storage compaction and indexing",
            ["lancedb", "vector", "arrow"],
        ),
    ]

    for repo_idx, repo in enumerate(repo_names):
        for chunk_idx in range(chunks_per_repo):
            topic_idx = (repo_idx + chunk_idx) % len(sample_topics)
            topic, topic_summary, tags = sample_topics[topic_idx]
            cat = categories[chunk_idx % len(categories)]
            scope = scopes[chunk_idx % len(scopes)]
            file_path = (
                f"src/modules/{topic}_{chunk_idx}.py"
                if cat == ChunkCategory.DOC
                else f"specs/{topic}.json"
            )

            content = (
                f"# Module {topic.upper()} - {repo}\n\n"
                f"Specification and implementation details for {topic_summary}.\n"
                f"Defines operational contract and invariants for chunk index {chunk_idx}.\n"
                f"Ensure zero latency overhead, proper connection handling, and error logging."
            )

            # Generate synthetic deterministic vector if no engine provided
            vector: list[float] | None = None
            if embedding_engine is None:
                vector = [
                    round(((chunk_idx * 17 + i * 31 + repo_idx * 13) % 100) / 100.0, 4)
                    for i in range(dim)
                ]

            chunk = DocumentChunk(
                id=f"{repo}:{file_path}:{chunk_idx}",
                repo=repo,
                file_path=file_path,
                category=cat,
                lifecycle=ChunkLifecycle.ACTIVE,
                scope=scope,
                breadcrumb=f"{repo} > {file_path} > {topic}",
                commit_sha="synthetic000",
                content=content,
                tags=tags + [repo, topic],
                vector=vector,
            )
            chunks.append(chunk)

    if embedding_engine is not None:
        chunks = embedding_engine.embed_chunks(chunks)

    return chunks


def run_latency_benchmark(
    pipeline: HybridRetrievalPipeline,
    queries: Sequence[str] | None = None,
    iterations: int = 10,
    warmup_runs: int = 2,
    limit: int = 10,
    rerank: bool = True,
) -> BenchmarkReport:
    """Benchmark Stage 1 dense/sparse/hybrid and Stage 2 reranker latencies."""
    benchmark_queries = list(queries) if queries is not None else DEFAULT_BENCHMARK_QUERIES
    if not benchmark_queries:
        benchmark_queries = DEFAULT_BENCHMARK_QUERIES

    total_chunks = pipeline.storage.count_chunks(table_name=pipeline.table_name)
    tech_records = pipeline.storage.get_technologies(table_name=pipeline.table_name)
    total_repos = len({str(r.get("repo", "")) for r in tech_records if r.get("repo")})

    # Warmup runs to prime ONNX engine and CPU caches
    for _ in range(warmup_runs):
        for q in benchmark_queries[:2]:
            _ = pipeline.search(query=q, limit=limit, rerank=rerank)

    vector_latencies: list[float] = []
    fts_latencies: list[float] = []
    hybrid_latencies: list[float] = []
    rerank_latencies: list[float] = []
    e2e_latencies: list[float] = []

    has_reranker = rerank and pipeline.reranker is not None and pipeline.reranker.is_enabled

    for _ in range(iterations):
        for q in benchmark_queries:
            # 1. Stage 1 Dense Vector Search
            t0 = time.perf_counter()
            query_vec = pipeline.embeddings.embed_query(q)
            _ = pipeline.storage.vector_search(
                query_vector=query_vec,
                limit=limit,
                table_name=pipeline.table_name,
            )
            vector_latencies.append((time.perf_counter() - t0) * 1000.0)

            # 2. Stage 1 Sparse FTS Search
            t0 = time.perf_counter()
            _ = pipeline.storage.fts_search(
                query_text=q,
                limit=limit,
                table_name=pipeline.table_name,
            )
            fts_latencies.append((time.perf_counter() - t0) * 1000.0)

            # 3. Stage 1 Hybrid Fusion (RRF)
            t0 = time.perf_counter()
            stage1_candidates = pipeline.search_stage1(query=q, limit=limit)
            hybrid_latencies.append((time.perf_counter() - t0) * 1000.0)

            # 4. Stage 2 Cross-Encoder Reranking
            if has_reranker and pipeline.reranker is not None:
                t0 = time.perf_counter()
                _ = pipeline.reranker.rerank(
                    query=q,
                    items=stage1_candidates,
                    top_k=limit,
                )
                rerank_latencies.append((time.perf_counter() - t0) * 1000.0)

            # 5. End-to-End Search
            t0 = time.perf_counter()
            _ = pipeline.search(query=q, limit=limit, rerank=rerank)
            e2e_latencies.append((time.perf_counter() - t0) * 1000.0)

    stage1_vec_stats = calculate_latency_stats("stage1_vector", vector_latencies)
    stage1_fts_stats = calculate_latency_stats("stage1_fts", fts_latencies)
    stage1_hybrid_stats = calculate_latency_stats("stage1_hybrid", hybrid_latencies)
    stage2_rerank_stats = (
        calculate_latency_stats("stage2_rerank", rerank_latencies) if has_reranker else None
    )
    e2e_stats = calculate_latency_stats("end_to_end", e2e_latencies)

    return BenchmarkReport(
        profile=pipeline.embeddings.profile.name,
        total_chunks=total_chunks,
        total_repos=total_repos,
        iterations=iterations,
        queries=benchmark_queries,
        stage1_vector=stage1_vec_stats,
        stage1_fts=stage1_fts_stats,
        stage1_hybrid=stage1_hybrid_stats,
        stage2_rerank=stage2_rerank_stats,
        end_to_end=e2e_stats,
    )
