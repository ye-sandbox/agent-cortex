"""Benchmark command implementation for agent-cortex CLI."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

import cortex.cli
from cortex.cli.common import console
from cortex.config.loader import load_config
from cortex.models.profile import HardwareProfileName


def benchmark_cmd(
    iterations: Annotated[
        int,
        typer.Option(
            "--iterations",
            "-n",
            help="Number of query benchmark iterations.",
        ),
    ] = 5,
    quality: Annotated[
        bool,
        typer.Option(
            "--quality/--no-quality",
            "--eval/--no-eval",
            help=(
                "Run IR retrieval & reranking quality evaluation "
                "(HitRate@K, Recall@K, MRR@K, nDCG@K)."
            ),
        ),
    ] = False,
    k: Annotated[
        int,
        typer.Option(
            "--k",
            "-k",
            help="Cutoff K for IR quality metrics (HitRate@K, Recall@K, MRR@K, nDCG@K).",
        ),
    ] = 5,
    synthetic: Annotated[
        bool,
        typer.Option(
            "--synthetic/--no-synthetic",
            help="Benchmark against an isolated synthetic multi-repo portfolio.",
        ),
    ] = False,
    synthetic_repos: Annotated[
        int,
        typer.Option(
            "--synthetic-repos",
            help="Number of synthetic repositories to generate.",
        ),
    ] = 3,
    synthetic_chunks: Annotated[
        int,
        typer.Option(
            "--synthetic-chunks",
            help="Number of chunks per synthetic repository.",
        ),
    ] = 20,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Hardware profile tier override (high, balanced, low, code).",
        ),
    ] = None,
    rerank: Annotated[
        bool,
        typer.Option(
            "--rerank/--no-rerank",
            help="Include Stage 2 cross-encoder reranking.",
        ),
    ] = True,
    table: Annotated[
        str,
        typer.Option(
            "--table",
            "-t",
            help="Target table name to benchmark against.",
        ),
    ] = "chunks",
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Stream machine-readable JSON benchmark report.",
        ),
    ] = False,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config-path",
            "-c",
            help="Custom configuration path.",
        ),
    ] = None,
) -> None:
    """Benchmark Stage 1 and Stage 2 retrieval latencies and IR quality."""
    from cortex.benchmarks.evaluation import (
        generate_synthetic_evaluation_dataset,
        run_retrieval_evaluation,
    )
    from cortex.benchmarks.latency import (
        generate_synthetic_benchmark_dataset,
        run_latency_benchmark,
    )

    cfg = load_config(config_path)
    prof_name = profile or cfg.profile.value

    if quality:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            temp_cfg = cfg.model_copy(
                update={
                    "profile": HardwareProfileName(prof_name),
                    "storage": cfg.storage.model_copy(update={"data_dir": temp_path}),
                }
            )
            pipeline = cortex.cli.HybridRetrievalPipeline.from_config(
                temp_cfg, profile_override=prof_name, table_name=table
            )
            if not json_output:
                total_syn = synthetic_repos * synthetic_chunks
                console.print(
                    f"[dim]Generating synthetic evaluation dataset "
                    f"({total_syn} chunks across {synthetic_repos} repos)...[/dim]"
                )
            chunks, eval_queries = generate_synthetic_evaluation_dataset(
                num_repos=synthetic_repos,
                chunks_per_repo=synthetic_chunks,
                dim=pipeline.embeddings.profile.embedding_dim,
                embedding_engine=pipeline.embeddings,
            )
            pipeline.storage.upsert_chunks(
                chunks, table_name=table, dim=pipeline.embeddings.profile.embedding_dim
            )
            eval_report = run_retrieval_evaluation(
                pipeline=pipeline,
                eval_queries=eval_queries,
                k=k,
                rerank=rerank,
            )

        if json_output:
            typer.echo(eval_report.model_dump_json(indent=2))
            return

        eval_vitals = (
            f"[bold]Active Profile:[/bold] [cyan]{eval_report.profile}[/cyan]\n"
            f"[bold]Indexed Chunks:[/bold] {eval_report.total_chunks}\n"
            f"[bold]Ground-Truth Queries:[/bold] {eval_report.queries_evaluated} "
            f"(Cutoff K={eval_report.k})\n"
            f"[bold]Rerank Lift:[/bold] ΔMRR@{eval_report.k}={eval_report.rerank_mrr_lift:+.4f}, "
            f"ΔnDCG@{eval_report.k}={eval_report.rerank_ndcg_lift:+.4f}"
        )
        console.print(
            Panel(eval_vitals, title="IR Quality Evaluation Summary", border_style="cyan")
        )

        qual_table = Table(
            title=f"Retrieval & Reranking Quality (@K={eval_report.k})", show_header=True
        )
        qual_table.add_column("Stage", style="bold cyan")
        qual_table.add_column(f"HitRate@{eval_report.k}", justify="right")
        qual_table.add_column(f"Recall@{eval_report.k}", justify="right")
        qual_table.add_column(f"MRR@{eval_report.k}", justify="right", style="green")
        qual_table.add_column(f"nDCG@{eval_report.k}", justify="right", style="yellow")
        qual_table.add_column("Mean Latency", justify="right")

        eval_stages = [
            ("Stage 1: Vector Search", eval_report.stage1_vector),
            ("Stage 1: Sparse FTS Search", eval_report.stage1_fts),
            ("Stage 1: Hybrid Fusion (RRF)", eval_report.stage1_hybrid),
        ]
        if eval_report.stage2_reranked is not None:
            eval_stages.append(("Stage 2: Cross-Encoder Rerank", eval_report.stage2_reranked))

        for label, m in eval_stages:
            qual_table.add_row(
                label,
                f"{m.hit_rate_at_k:.4f}",
                f"{m.recall_at_k:.4f}",
                f"{m.mrr_at_k:.4f}",
                f"{m.ndcg_at_k:.4f}",
                f"{m.mean_latency_ms:.1f}ms",
            )

        console.print(qual_table)
        return

    if synthetic:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_path = Path(tmpdir)
            temp_cfg = cfg.model_copy(
                update={
                    "profile": HardwareProfileName(prof_name),
                    "storage": cfg.storage.model_copy(update={"data_dir": temp_path}),
                }
            )
            pipeline = cortex.cli.HybridRetrievalPipeline.from_config(
                temp_cfg, profile_override=prof_name, table_name=table
            )
            if not json_output:
                console.print(
                    f"[dim]Generating {synthetic_repos * synthetic_chunks} synthetic chunks "
                    f"across {synthetic_repos} repos...[/dim]"
                )
            chunks = generate_synthetic_benchmark_dataset(
                num_repos=synthetic_repos,
                chunks_per_repo=synthetic_chunks,
                dim=pipeline.embeddings.profile.embedding_dim,
                embedding_engine=pipeline.embeddings,
            )
            pipeline.storage.upsert_chunks(
                chunks, table_name=table, dim=pipeline.embeddings.profile.embedding_dim
            )
            report = run_latency_benchmark(
                pipeline=pipeline,
                iterations=iterations,
                rerank=rerank,
            )
    else:
        pipeline = cortex.cli.HybridRetrievalPipeline.from_config(
            cfg, profile_override=prof_name, table_name=table
        )
        total_chunks = pipeline.storage.count_chunks(table_name=table)
        if total_chunks == 0:
            if json_output:
                typer.echo(
                    json.dumps(
                        {"error": "Database is empty. Run with --synthetic or run 'cortex sync'."}
                    )
                )
            else:
                console.print(
                    "[yellow]Database table is empty.[/yellow] "
                    "Run with [bold cyan]--synthetic[/bold cyan] to benchmark with synthetic data "
                    "or run [bold cyan]'cortex sync'[/bold cyan] first."
                )
            raise typer.Exit(code=1)

        report = run_latency_benchmark(
            pipeline=pipeline,
            iterations=iterations,
            rerank=rerank,
        )

    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        return

    vitals = (
        f"[bold]Active Profile:[/bold] [cyan]{report.profile}[/cyan]\n"
        f"[bold]Indexed Chunks:[/bold] {report.total_chunks} across {report.total_repos} repo(s)\n"
        f"[bold]Iterations:[/bold] {report.iterations} per query ({len(report.queries)} queries)"
    )
    console.print(Panel(vitals, title="Benchmark Configuration", border_style="cyan"))

    bench_table = Table(title="Retrieval Latency Breakdown", show_header=True)
    bench_table.add_column("Stage", style="bold cyan")
    bench_table.add_column("Iterations", justify="right")
    bench_table.add_column("Min", justify="right")
    bench_table.add_column("P50", justify="right", style="green")
    bench_table.add_column("P95", justify="right", style="yellow")
    bench_table.add_column("P99", justify="right", style="red")
    bench_table.add_column("Mean", justify="right")

    stages = [
        ("Stage 1: Vector Search", report.stage1_vector),
        ("Stage 1: Sparse FTS Search", report.stage1_fts),
        ("Stage 1: Hybrid Fusion (RRF)", report.stage1_hybrid),
    ]
    if report.stage2_rerank:
        stages.append(("Stage 2: Cross-Encoder Rerank", report.stage2_rerank))
    stages.append(("End-to-End Pipeline", report.end_to_end))

    for label, s in stages:
        bench_table.add_row(
            label,
            str(s.iterations),
            f"{s.min_ms:.1f}ms",
            f"{s.p50_ms:.1f}ms",
            f"{s.p95_ms:.1f}ms",
            f"{s.p99_ms:.1f}ms",
            f"{s.mean_ms:.1f}ms",
        )

    console.print(bench_table)
