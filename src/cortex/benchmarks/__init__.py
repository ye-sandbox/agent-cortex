"""Benchmarking and performance profiling suite for agent-cortex."""

from cortex.benchmarks.evaluation import (
    EvaluationQuery,
    RetrievalEvaluationReport,
    StageEvaluationMetrics,
    generate_synthetic_evaluation_dataset,
    hit_rate_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    run_retrieval_evaluation,
)
from cortex.benchmarks.ingestion import (
    SyncThroughputBenchmarkReport,
    run_sync_throughput_benchmark,
)
from cortex.benchmarks.latency import (
    DEFAULT_BENCHMARK_QUERIES,
    BenchmarkReport,
    LatencyStats,
    calculate_latency_stats,
    generate_synthetic_benchmark_dataset,
    run_latency_benchmark,
)

__all__ = [
    "DEFAULT_BENCHMARK_QUERIES",
    "BenchmarkReport",
    "EvaluationQuery",
    "LatencyStats",
    "RetrievalEvaluationReport",
    "StageEvaluationMetrics",
    "SyncThroughputBenchmarkReport",
    "calculate_latency_stats",
    "generate_synthetic_benchmark_dataset",
    "generate_synthetic_evaluation_dataset",
    "hit_rate_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "recall_at_k",
    "run_latency_benchmark",
    "run_retrieval_evaluation",
    "run_sync_throughput_benchmark",
]
