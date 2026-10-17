"""Ingestion and synchronization throughput benchmarking suite for agent-cortex."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field

from cortex.benchmarks.latency import generate_synthetic_benchmark_dataset
from cortex.models.chunk import DocumentChunk
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)


class SyncThroughputBenchmarkReport(BaseModel):
    """Benchmark comparing per-batch FTS indexing vs deferred FTS indexing."""

    model_config = ConfigDict(frozen=True)

    total_chunks: int
    batch_size: int
    batch_count: int
    per_batch_duration_ms: float
    per_batch_throughput_chunks_per_sec: float
    deferred_duration_ms: float
    deferred_throughput_chunks_per_sec: float
    speedup_factor: float
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def run_sync_throughput_benchmark(
    chunks: Sequence[DocumentChunk] | None = None,
    num_repos: int = 5,
    chunks_per_repo: int = 40,
    batch_size: int = 20,
    dim: int = 16,
) -> SyncThroughputBenchmarkReport:
    """Benchmark bulk ingestion throughput comparing per-batch vs deferred FTS indexing.

    Args:
        chunks: Optional pre-generated sequence of DocumentChunk objects. If None,
            synthetic chunks will be generated.
        num_repos: Number of repositories to simulate if chunks is None.
        chunks_per_repo: Chunks per repository if chunks is None.
        batch_size: Number of chunks per upsert batch.
        dim: Vector dimension for synthetic chunks.

    Returns:
        SyncThroughputBenchmarkReport with duration, throughput, and speedup metrics.
    """
    if chunks is None:
        dataset = generate_synthetic_benchmark_dataset(
            num_repos=num_repos,
            chunks_per_repo=chunks_per_repo,
            dim=dim,
        )
    else:
        dataset = list(chunks)

    total_chunks = len(dataset)
    if total_chunks == 0:
        msg = "Cannot run throughput benchmark on empty chunk dataset."
        raise ValueError(msg)

    effective_batch_size = max(1, batch_size)
    batches: list[list[DocumentChunk]] = [
        dataset[i : i + effective_batch_size] for i in range(0, total_chunks, effective_batch_size)
    ]
    batch_count = len(batches)

    # 1. Run per-batch FTS indexing benchmark
    with TemporaryDirectory() as tmpdir_legacy:
        storage_legacy = StorageManager(data_dir=tmpdir_legacy)
        t0 = time.perf_counter()
        for batch in batches:
            storage_legacy.upsert_chunks(
                batch,
                table_name="chunks",
                dim=dim,
                create_fts=True,  # Rebuild FTS every batch
            )
        per_batch_duration = time.perf_counter() - t0

    # 2. Run deferred FTS indexing benchmark
    with TemporaryDirectory() as tmpdir_deferred:
        storage_deferred = StorageManager(data_dir=tmpdir_deferred)
        t1 = time.perf_counter()
        for batch in batches:
            storage_deferred.upsert_chunks(
                batch,
                table_name="chunks",
                dim=dim,
                create_fts=False,  # Defer during batch loop
            )
        storage_deferred.create_fts_index(table_name="chunks")  # Rebuild once at end
        deferred_duration = time.perf_counter() - t1

    per_batch_ms = max(0.001, per_batch_duration * 1000.0)
    deferred_ms = max(0.001, deferred_duration * 1000.0)

    per_batch_tput = total_chunks / (per_batch_ms / 1000.0)
    deferred_tput = total_chunks / (deferred_ms / 1000.0)
    speedup = per_batch_ms / deferred_ms

    return SyncThroughputBenchmarkReport(
        total_chunks=total_chunks,
        batch_size=effective_batch_size,
        batch_count=batch_count,
        per_batch_duration_ms=round(per_batch_ms, 2),
        per_batch_throughput_chunks_per_sec=round(per_batch_tput, 2),
        deferred_duration_ms=round(deferred_ms, 2),
        deferred_throughput_chunks_per_sec=round(deferred_tput, 2),
        speedup_factor=round(speedup, 2),
    )
