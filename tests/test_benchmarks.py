"""Unit tests for the latency benchmarking suite and synthetic dataset generation."""

import json
from collections.abc import Sequence
from tempfile import TemporaryDirectory

import pytest
from typer.testing import CliRunner

from cortex.benchmarks.evaluation import (
    generate_synthetic_evaluation_dataset,
    hit_rate_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    run_retrieval_evaluation,
)
from cortex.benchmarks.ingestion import run_sync_throughput_benchmark
from cortex.benchmarks.latency import (
    calculate_latency_stats,
    generate_synthetic_benchmark_dataset,
    run_latency_benchmark,
)
from cortex.cli import app
from cortex.config.loader import CortexConfig
from cortex.embeddings.engine import EmbeddingEngine
from cortex.models.chunk import ChunkCategory, DocumentChunk
from cortex.models.profile import HardwareProfileName, resolve_hardware_profile
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.retrieval.reranker import RerankerEngine
from cortex.storage.manager import StorageManager


def test_calculate_latency_stats_empty() -> None:
    """Ensure empty latencies sequence returns zeroed LatencyStats."""
    stats = calculate_latency_stats("test_stage", [])
    assert stats.stage == "test_stage"
    assert stats.iterations == 0
    assert stats.min_ms == 0.0
    assert stats.max_ms == 0.0
    assert stats.mean_ms == 0.0
    assert stats.p50_ms == 0.0
    assert stats.p95_ms == 0.0
    assert stats.p99_ms == 0.0


def test_calculate_latency_stats_values() -> None:
    """Ensure percentiles and statistical aggregates are computed correctly."""
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    stats = calculate_latency_stats("vector_search", latencies)

    assert stats.stage == "vector_search"
    assert stats.iterations == 10
    assert stats.min_ms == 10.0
    assert stats.max_ms == 100.0
    assert stats.mean_ms == 55.0
    assert stats.p50_ms == 55.0
    assert stats.p95_ms > 90.0
    assert stats.p99_ms > 95.0


def test_generate_synthetic_benchmark_dataset() -> None:
    """Ensure synthetic dataset generates the expected number of repos and chunks."""
    chunks = generate_synthetic_benchmark_dataset(num_repos=3, chunks_per_repo=10, dim=16)

    assert len(chunks) == 30
    assert all(isinstance(c, DocumentChunk) for c in chunks)

    repos = {c.repo for c in chunks}
    assert len(repos) == 3
    assert all(len(c.vector or []) == 16 for c in chunks)

    categories = {c.category for c in chunks}
    assert ChunkCategory.DOC in categories
    assert ChunkCategory.CONTRACT in categories
    assert ChunkCategory.INFRA in categories


def test_run_latency_benchmark_isolated() -> None:
    """Ensure run_latency_benchmark runs against an isolated storage and produces a report."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        # Use low profile (no reranker) for ultra-fast unit testing
        cfg = CortexConfig(profile=HardwareProfileName.LOW)
        pipeline = HybridRetrievalPipeline.from_config(cfg, profile_override="low")
        pipeline.storage = storage

        # Seed synthetic data
        chunks = generate_synthetic_benchmark_dataset(
            num_repos=2,
            chunks_per_repo=5,
            dim=pipeline.embeddings.profile.embedding_dim,
            embedding_engine=pipeline.embeddings,
        )
        storage.upsert_chunks(
            chunks,
            table_name="chunks",
            dim=pipeline.embeddings.profile.embedding_dim,
        )

        report = run_latency_benchmark(
            pipeline=pipeline,
            queries=["JWT authentication token validation", "docker compose service"],
            iterations=2,
            warmup_runs=1,
            rerank=False,
        )

        assert report.profile == "low"
        assert report.total_chunks == 10
        assert report.total_repos == 2
        assert report.iterations == 2
        assert len(report.queries) == 2
        assert report.stage1_vector.iterations == 4  # 2 iterations * 2 queries
        assert report.stage1_fts.iterations == 4
        assert report.stage1_hybrid.iterations == 4
        assert report.end_to_end.iterations == 4
        assert report.stage2_rerank is None  # low profile has no reranker


def test_run_sync_throughput_benchmark() -> None:
    """Ensure run_sync_throughput_benchmark measures per-batch vs deferred indexing."""
    report = run_sync_throughput_benchmark(
        num_repos=3,
        chunks_per_repo=10,
        batch_size=5,
        dim=4,
    )

    assert report.total_chunks == 30
    assert report.batch_size == 5
    assert report.batch_count == 6
    assert report.per_batch_duration_ms > 0.0
    assert report.deferred_duration_ms > 0.0
    assert report.per_batch_throughput_chunks_per_sec > 0.0
    assert report.deferred_throughput_chunks_per_sec > 0.0
    assert report.speedup_factor > 0.0


def test_ir_quality_metrics_primitives() -> None:
    """Verify HitRate@K, Recall@K, MRR@K, and nDCG@K mathematical invariants."""
    retrieved = ["doc_a", "doc_b", "doc_c", "doc_d", "doc_e"]
    relevant = ["doc_b", "doc_e"]

    assert hit_rate_at_k(retrieved, relevant, k=1) == 0.0
    assert hit_rate_at_k(retrieved, relevant, k=2) == 1.0
    assert hit_rate_at_k([], relevant, k=5) == 0.0
    assert hit_rate_at_k(retrieved, [], k=5) == 0.0
    assert hit_rate_at_k(retrieved, relevant, k=0) == 0.0

    assert recall_at_k(retrieved, relevant, k=1) == 0.0
    assert recall_at_k(retrieved, relevant, k=2) == 0.5
    assert recall_at_k(retrieved, relevant, k=5) == 1.0

    # First relevant hit is at rank 2 -> RR = 1/2 = 0.5
    assert mrr_at_k(retrieved, relevant, k=1) == 0.0
    assert mrr_at_k(retrieved, relevant, k=2) == 0.5
    assert mrr_at_k(retrieved, relevant, k=5) == 0.5

    # Perfect ranking should yield nDCG = 1.0
    assert ndcg_at_k(["doc_b", "doc_e", "doc_a"], relevant, k=3) == pytest.approx(1.0)
    assert 0.0 < ndcg_at_k(retrieved, relevant, k=5) < 1.0
    assert ndcg_at_k(retrieved, ["non_existent"], k=5) == 0.0


def test_run_retrieval_evaluation_with_reranker_lift() -> None:
    """Verify Stage 1 and Stage 2 retrieval evaluation report and reranker lift calculation."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        profile = resolve_hardware_profile(HardwareProfileName.BALANCED)

        def mock_passage_embed(texts: Sequence[str]) -> list[list[float]]:
            vecs: list[list[float]] = []
            for t in texts:
                val = 0.9 if "jwt" in t.lower() else 0.1
                vecs.append([val] * 8)
            return vecs

        def mock_query_embed(q: str) -> list[float]:
            val = 0.9 if "jwt" in q.lower() else 0.1
            return [val] * 8

        def mock_rerank(query: str, passages: Sequence[str]) -> list[float]:
            scores: list[float] = []
            q_terms = set(query.lower().split())
            for p in passages:
                p_lower = p.lower()
                overlap = sum(1.0 for term in q_terms if term in p_lower)
                scores.append(overlap)
            return scores

        custom_profile = profile.model_copy(update={"embedding_dim": 8, "top_k_rerank": 10})
        embeddings = EmbeddingEngine(
            profile=custom_profile,
            passage_embed_fn=mock_passage_embed,
            query_embed_fn=mock_query_embed,
        )
        reranker = RerankerEngine(profile=custom_profile, rerank_fn=mock_rerank)
        pipeline = HybridRetrievalPipeline(
            storage=storage,
            embeddings=embeddings,
            reranker=reranker,
        )

        chunks, eval_queries = generate_synthetic_evaluation_dataset(
            num_repos=2,
            chunks_per_repo=5,
            dim=8,
            embedding_engine=embeddings,
        )
        storage.upsert_chunks(chunks, table_name="chunks", dim=8)

        report = run_retrieval_evaluation(
            pipeline=pipeline,
            eval_queries=eval_queries,
            k=5,
            rerank=True,
        )

        assert report.profile == "balanced"
        assert report.k == 5
        assert report.total_chunks == 10
        assert report.queries_evaluated == len(eval_queries)
        assert report.stage1_vector.queries_evaluated == len(eval_queries)
        assert report.stage1_fts.queries_evaluated == len(eval_queries)
        assert report.stage1_hybrid.queries_evaluated == len(eval_queries)
        assert report.stage2_reranked is not None
        assert report.stage2_reranked.hit_rate_at_k > 0.0
        assert report.stage2_reranked.ndcg_at_k > 0.0

        with pytest.raises(ValueError, match="Evaluation cutoff k must be greater than 0"):
            run_retrieval_evaluation(pipeline=pipeline, eval_queries=eval_queries, k=0)


def test_cli_benchmark_quality_json() -> None:
    """Verify 'cortex benchmark --quality --json' executes and returns valid JSON metrics."""
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "benchmark",
            "--quality",
            "--profile",
            "low",
            "--synthetic-repos",
            "2",
            "--synthetic-chunks",
            "5",
            "--k",
            "3",
            "--json",
        ],
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["profile"] == "low"
    assert payload["k"] == 3
    assert payload["total_chunks"] == 10
    assert payload["queries_evaluated"] > 0
    assert "stage1_vector" in payload
    assert "stage1_fts" in payload
    assert "stage1_hybrid" in payload
    assert payload["stage1_hybrid"]["hit_rate_at_k"] >= 0.0
