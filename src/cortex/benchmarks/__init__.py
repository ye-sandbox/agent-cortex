"""Benchmarking and performance profiling suite for agent-cortex."""

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
    "LatencyStats",
    "calculate_latency_stats",
    "generate_synthetic_benchmark_dataset",
    "run_latency_benchmark",
]
