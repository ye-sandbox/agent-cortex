"""Unit tests for the latency benchmarking suite and synthetic dataset generation."""

from tempfile import TemporaryDirectory

from cortex.benchmarks.latency import (
    calculate_latency_stats,
    generate_synthetic_benchmark_dataset,
    run_latency_benchmark,
)
from cortex.config.loader import CortexConfig
from cortex.models.chunk import ChunkCategory, DocumentChunk
from cortex.models.profile import HardwareProfileName
from cortex.retrieval.pipeline import HybridRetrievalPipeline
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
