"""Root command implementations for agent-cortex CLI.

Provides search, sync, status, bootstrap, benchmark, serve, and mcp commands.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

import cortex.cli
from cortex.cli.commands.storage import run_clean_orphans, run_compaction
from cortex.cli.commands.watcher import run_watcher_cli
from cortex.cli.common import console
from cortex.client import ClientMode, CortexRemoteError
from cortex.config.loader import (
    CortexConfig,
    get_default_config_path,
    load_config,
    save_config,
)
from cortex.ingestion.discovery import resolve_sync_sources
from cortex.ingestion.manifest import ManifestManager
from cortex.models.chunk import ChunkCategory, ChunkScope
from cortex.models.lifecycle import ModelDownloadError
from cortex.models.profile import HardwareProfileName


def version_cmd() -> None:
    """Print the version of agent-cortex."""
    from cortex import __version__

    console.print(f"[bold cyan]agent-cortex[/bold cyan] version [green]{__version__}[/green]")


def bootstrap_cmd(
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Hardware profile tier to initialize (high, balanced, low, code).",
        ),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config-path",
            "-c",
            help="Explicit destination path for generated config.yaml.",
        ),
    ] = None,
    download_models: Annotated[
        bool,
        typer.Option(
            "--download-models/--no-download-models",
            help="Pre-cache ONNX model weights for the active profile.",
        ),
    ] = True,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force overwrite existing configuration file.",
        ),
    ] = False,
) -> None:
    """Bootstrap agent-cortex directories, default configuration, and models."""
    console.print("[bold cyan]agent-cortex[/bold cyan] bootstrap initialization\n")

    target_config_path = (
        config_path.expanduser().resolve() if config_path else get_default_config_path()
    )

    if target_config_path.is_file() and not force:
        cfg = load_config(target_config_path)
        console.print(
            f"[green]✓[/green] Found existing configuration: [bold]{target_config_path}[/bold]"
        )
        if profile:
            try:
                prof_enum = HardwareProfileName(profile.lower())
                cfg = cfg.model_copy(update={"profile": prof_enum})
            except ValueError as e:
                console.print(f"[bold red]Error:[/bold red] {e}")
                raise typer.Exit(code=1) from None
    else:
        try:
            prof_enum = (
                HardwareProfileName(profile.lower()) if profile else HardwareProfileName.BALANCED
            )
        except ValueError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            raise typer.Exit(code=1) from None

        cfg = CortexConfig(profile=prof_enum)
        save_config(cfg, target_config_path)
        console.print(
            f"[green]✓[/green] Configuration written to [bold]{target_config_path}[/bold]"
        )

    # Initialize data storage directory
    cfg.storage.data_dir.mkdir(parents=True, exist_ok=True)
    console.print(
        f"[green]✓[/green] Storage directory initialized: [bold]{cfg.storage.data_dir}[/bold]"
    )

    # Verify and resolve hardware profile
    try:
        hw_profile = cfg.get_active_profile()
    except ValueError as e:
        console.print(f"[bold red]Error resolving profile:[/bold red] {e}")
        raise typer.Exit(code=1) from None

    reranker_info = hw_profile.reranker_model or "None (Stage 1 only)"
    console.print(
        f"[green]✓[/green] Active hardware profile: [bold cyan]{hw_profile.name}[/bold cyan] "
        f"(Embedding: {hw_profile.embedding_model}, Reranker: {reranker_info})"
    )

    # Pre-flight model caching
    if download_models:
        console.print(
            f"\n[bold]Pre-caching models for profile '[cyan]{hw_profile.name}[/cyan]'...[/bold]"
        )
        try:
            with console.status(
                f"[bold green]Downloading weights for {hw_profile.name}...[/bold green]"
            ):
                results = cortex.cli.download_profile_models(
                    hw_profile,
                    on_progress=lambda stage, name: console.print(
                        f"  → Downloading {stage} model: [cyan]{name}[/cyan]"
                    ),
                )
            console.print(
                f"[bold green]✓[/bold green] Cached {len(results)} model(s) successfully."
            )
        except ModelDownloadError as err:
            console.print(f"[bold red]✗ Model download failed:[/bold red] {err}")
            console.print(
                "[yellow]Diagnostic:[/yellow] Check your internet connection or proxy settings. "
                "In air-gapped environments, configure local weights or run "
                "'cortex models download' when online."
            )
            raise typer.Exit(code=1) from None
    else:
        console.print("[yellow]ℹ[/yellow] Model download skipped (--no-download-models).")

    console.print(
        Panel(
            f"agent-cortex initialized successfully.\n"
            f"Profile: [cyan]{hw_profile.name}[/cyan]\n"
            f"Config: [dim]{target_config_path}[/dim]\n"
            f"Storage: [dim]{cfg.storage.data_dir}[/dim]",
            title="Bootstrap Complete",
            border_style="green",
        )
    )


def sync_cmd(
    target: Annotated[
        str | None,
        typer.Argument(
            help="Optional repository name, path, or portfolio directory to synchronize.",
        ),
    ] = None,
    repo: Annotated[
        str | None,
        typer.Option(
            "--repo",
            "-r",
            help="Sync a specific repository by name or filesystem path.",
        ),
    ] = None,
    all_repos: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="Sync all configured and auto-discovered repositories.",
        ),
    ] = False,
    force_full: Annotated[
        bool,
        typer.Option(
            "--force-full",
            "-f",
            help="Force full re-indexing, bypassing incremental git diff checkpoints.",
        ),
    ] = False,
    watch: Annotated[
        bool,
        typer.Option(
            "--watch",
            "-w",
            help="Run continuously in background watcher mode.",
        ),
    ] = False,
    interval: Annotated[
        float,
        typer.Option(
            "--interval",
            "-i",
            help="Polling interval in seconds between repository drift checks.",
        ),
    ] = 30.0,
    debounce: Annotated[
        float,
        typer.Option(
            "--debounce",
            help="Debounce delay in seconds before triggering index sync.",
        ),
    ] = 2.0,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output sync events as machine-readable NDJSON.",
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
    """Synchronize git repositories into LanceDB vector storage incrementally."""
    cfg = load_config(config_path)
    effective_repo = repo or target

    if watch:
        run_watcher_cli(
            cfg=cfg,
            effective_repo=effective_repo,
            all_repos=all_repos,
            interval=interval,
            debounce=debounce,
            force_full=force_full,
            json_output=json_output,
        )
        return

    sources = resolve_sync_sources(config=cfg, repo_filter=effective_repo, all_flag=all_repos)

    if not sources:
        if effective_repo:
            console.print(
                f"[bold red]Error:[/bold red] Repository '{effective_repo}' not found "
                "in configuration or on filesystem."
            )
        else:
            console.print("[yellow]No repositories configured or discovered for sync.[/yellow]")
            console.print(
                "Run 'cortex sync <path_or_name>' or configure repositories in config.yaml."
            )
        raise typer.Exit(code=1)

    console.print(
        f"[bold cyan]agent-cortex[/bold cyan] synchronizing "
        f"[bold]{len(sources)}[/bold] repository source(s)...\n"
    )

    engine = cortex.cli.IngestionEngine.from_config(cfg)
    results = []

    with console.status("[bold green]Indexing repositories...[/bold green]") as status_bar:
        defer_fts = len(sources) > 1
        any_changes = False
        for src in sources:
            repo_name = src.get_repo_name()
            status_bar.update(f"Syncing [cyan]{repo_name}[/cyan]...")
            res = engine.sync_repository(
                repo_path=src.path,
                repo_name=repo_name,
                default_scope=src.default_scope,
                force_full=force_full,
                defer_fts=defer_fts,
            )
            results.append(res)
            if res.added_chunks > 0 or res.updated_chunks > 0 or res.deleted_chunks > 0:
                any_changes = True

        if defer_fts and any_changes:
            status_bar.update("Building full-text and vector search indices...")
            engine.storage.create_fts_index()
            engine.storage.create_vector_index()

    table = Table(title="Repository Synchronization Summary", show_header=True)
    table.add_column("Repository", style="bold cyan", no_wrap=True)
    table.add_column("Commit Range", style="dim", no_wrap=True)
    table.add_column("Added", justify="right", style="green")
    table.add_column("Updated", justify="right", style="yellow")
    table.add_column("Deleted", justify="right", style="red")
    table.add_column("Files", justify="right")
    table.add_column("Duration", justify="right", style="dim")
    table.add_column("Status", justify="center", no_wrap=True)

    has_errors = False
    for r in results:
        if r.errors:
            has_errors = True
            status_text = "[bold red]✗ Failed[/bold red]"
        elif r.has_changes:
            status_text = "[bold green]✓ Synced[/bold green]"
        else:
            status_text = "[green]✓ Clean[/green]"

        base_str = r.base_commit[:8] if r.base_commit else "initial"
        target_str = r.target_commit[:8] if r.target_commit else "?"
        commit_range = f"{base_str}..{target_str}" if r.base_commit else target_str

        table.add_row(
            r.repo,
            commit_range,
            str(r.added_chunks),
            str(r.updated_chunks),
            str(r.deleted_chunks),
            str(r.processed_files),
            f"{r.duration_seconds:.2f}s",
            status_text,
        )

    console.print(table)

    if has_errors:
        for r in results:
            if r.errors:
                console.print(f"\n[bold red]Errors encountered in '{r.repo}':[/bold red]")
                for err in r.errors:
                    console.print(f"  • {err}")
        raise typer.Exit(code=1)

    console.print("\n[bold green]✓ All repositories synchronized successfully.[/bold green]")


def search_cmd(
    query: Annotated[
        str,
        typer.Argument(help="Semantic query to search across portfolio knowledge."),
    ],
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Hardware profile tier override (high, balanced, low, code).",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-l",
            help="Maximum number of search results to return.",
        ),
    ] = None,
    scope: Annotated[
        str | None,
        typer.Option(
            "--scope",
            "-s",
            help="Scope filter (internal, public, confidential, or comma-separated).",
        ),
    ] = None,
    include_archived: Annotated[
        bool,
        typer.Option(
            "--include-archived",
            help="Include archived chunks without score penalty.",
        ),
    ] = False,
    category: Annotated[
        str | None,
        typer.Option(
            "--category",
            help="Filter by category (doc, contract, infra, invariant, solution).",
        ),
    ] = None,
    repo: Annotated[
        str | None,
        typer.Option(
            "--repo",
            "-r",
            help="Filter results by repository name.",
        ),
    ] = None,
    rerank: Annotated[
        bool,
        typer.Option(
            "--rerank/--no-rerank",
            help="Enable or disable Stage 2 cross-encoder reranking.",
        ),
    ] = True,
    remote: Annotated[
        bool | None,
        typer.Option(
            "--remote/--local",
            help="Force querying remote hub or local in-process storage.",
        ),
    ] = None,
    hub_url: Annotated[
        str | None,
        typer.Option(
            "--hub-url",
            help="Remote agent-cortex hub endpoint override (e.g. 'http://homelab:8000').",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Stream machine-readable NDJSON output for AI agent subshell invocation.",
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
    """Search portfolio documentation, OpenAPI contracts, and infrastructure definitions."""
    cleaned_query = query.strip()
    if not cleaned_query:
        if json_output:
            return
        console.print("[yellow]Empty query provided.[/yellow]")
        return

    cfg = load_config(config_path)

    # Parse scopes
    scopes: list[ChunkScope] | None = None
    if scope:
        scopes = []
        for s in scope.split(","):
            s_clean = s.strip().lower()
            if s_clean:
                try:
                    scopes.append(ChunkScope(s_clean))
                except ValueError:
                    console.print(f"[bold red]Error:[/bold red] Invalid scope '{s_clean}'.")
                    raise typer.Exit(code=1) from None

    # Parse category
    cat: ChunkCategory | None = None
    if category:
        try:
            cat = ChunkCategory(category.strip().lower())
        except ValueError:
            console.print(f"[bold red]Error:[/bold red] Invalid category '{category}'.")
            raise typer.Exit(code=1) from None

    mode: ClientMode = "auto"
    if remote is True:
        mode = "remote"
    elif remote is False:
        mode = "in_process"

    local_pipeline = (
        cortex.cli.HybridRetrievalPipeline.from_config(cfg, profile_override=profile)
        if profile
        else None
    )

    client = cortex.cli.CortexClient(
        mode=mode,
        hub_url=hub_url,
        config=cfg,
        pipeline=local_pipeline,
    )

    try:
        if json_output:
            for res in client.search_stream(
                query=cleaned_query,
                limit=limit,
                scopes=scopes,
                include_archived=include_archived,
                category=cat,
                repo=repo,
                rerank=rerank,
            ):
                typer.echo(res.model_dump_json())
            return

        results = client.search(
            query=cleaned_query,
            limit=limit,
            scopes=scopes,
            include_archived=include_archived,
            category=cat,
            repo=repo,
            rerank=rerank,
        )
    except CortexRemoteError as exc:
        target_hub = (
            exc.hub_url
            or client.hub_url
            or hub_url
            or (cfg.remote.hub_url if cfg.remote else None)
            or "unknown"
        )
        panel_content = (
            f"[bold red]Remote Hub Connection Failed[/bold red]\n\n"
            f"Target: [cyan]{escape(str(target_hub))}[/cyan]\n"
            f"Reason: [dim]{escape(str(exc))}[/dim]\n\n"
            f"[yellow]Diagnostic:[/yellow]\n"
            f"• Verify that the daemon is running (`cortex serve`) or network connectivity.\n"
            f"• Run with `--local` to query the local embedded LanceDB database directly."
        )
        console.print(Panel(panel_content, title="Connection Error", border_style="red"))
        raise typer.Exit(code=1) from None
    except Exception as exc:
        console.print(f"[bold red]Search failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from None

    if not results:
        console.print("[yellow]No matching chunks found.[/yellow]")
        return

    console.print(
        f"[bold cyan]agent-cortex[/bold cyan] found [green]{len(results)}[/green] "
        "matching chunk(s):\n"
    )

    for rank, r in enumerate(results, start=1):
        repo_badge = f"[bold cyan]{escape(f'[{r.repo}]')}[/bold cyan]"
        breadcrumb_str = f" > [yellow]{escape(r.breadcrumb)}[/yellow]" if r.breadcrumb else ""
        console.print(
            f"[bold green]#{rank}[/bold green] {repo_badge} "
            f"[bold]{escape(r.file_path)}[/bold]{breadcrumb_str} "
            f"[dim](score: {r.score:.4f}, scope: {r.scope.value}, {r.category.value})[/dim]"
        )
        if r.snippet:
            indented = "    " + r.snippet.replace("\n", "\n    ")
            console.print(f"[dim]{indented}[/dim]")
        if r.tags:
            tag_str = " ".join(f"[blue]#{t}[/blue]" for t in r.tags[:6])
            console.print(f"    {tag_str}")
        console.print()


def status_cmd(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config-path",
            "-c",
            help="Custom configuration path.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output machine-readable JSON status.",
        ),
    ] = False,
) -> None:
    """Display active hardware profile, storage directories, and sync status."""
    from cortex.storage.manager import StorageManager

    cfg = load_config(config_path)
    profile = cfg.get_active_profile()
    storage = StorageManager(cfg.storage.data_dir)
    manifest_mgr = ManifestManager(cfg.storage.data_dir / "manifest.json")
    manifest = manifest_mgr.load()

    total_chunks = storage.count_chunks()
    table_names = storage.table_names()

    if json_output:
        payload = {
            "profile": {
                "name": profile.name,
                "embedding_model": profile.embedding_model,
                "embedding_dim": profile.embedding_dim,
                "reranker_model": profile.reranker_model,
                "max_threads": profile.max_threads,
            },
            "storage": {
                "data_dir": str(cfg.storage.data_dir),
                "total_chunks": total_chunks,
                "tables": table_names,
            },
            "repositories": {
                name: state.model_dump(mode="json") for name, state in manifest.repositories.items()
            },
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    console.print("[bold cyan]agent-cortex[/bold cyan] system status\n")

    reranker_info = profile.reranker_model or "None (Stage 1 only)"
    vitals_panel = (
        f"[bold]Active Profile:[/bold] [cyan]{profile.name}[/cyan]\n"
        f"[bold]Embedding Model:[/bold] {profile.embedding_model} (dim: {profile.embedding_dim})\n"
        f"[bold]Reranker Model:[/bold] {reranker_info}\n"
        f"[bold]Max CPU Threads:[/bold] {profile.max_threads}\n"
        f"[bold]Storage Directory:[/bold] [dim]{cfg.storage.data_dir}[/dim]\n"
        f"[bold]Total Indexed Chunks:[/bold] [bold green]{total_chunks}[/bold green]"
    )
    console.print(Panel(vitals_panel, title="System Vitals", border_style="cyan"))

    console.print()
    if not manifest.repositories:
        console.print("[yellow]No repositories synchronized yet.[/yellow]")
        console.print("Run 'cortex sync' to index your first repository.")
        return

    table = Table(title="Indexed Repositories", show_header=True)
    table.add_column("Repository", style="bold cyan")
    table.add_column("Last Synced Commit", style="dim")
    table.add_column("Last Synced At", style="dim")
    table.add_column("Chunks", justify="right", style="green")
    table.add_column("Files", justify="right")
    table.add_column("Path", style="dim")

    for state in manifest.repositories.values():
        table.add_row(
            state.repo_name,
            state.last_synced_commit[:8] if state.last_synced_commit else "None",
            state.last_synced_at[:19] if state.last_synced_at else "-",
            str(state.chunk_count),
            str(state.file_count),
            state.repo_path,
        )

    console.print(table)


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


def mcp_server_cmd() -> None:
    """Launch Model Context Protocol (MCP) stdio server."""
    from cortex.mcp_server import main as run_mcp_server

    run_mcp_server()


def serve_cmd(
    host: Annotated[
        str,
        typer.Option(
            "--host",
            "-h",
            help="Network interface host to bind the server to.",
        ),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(
            "--port",
            "-p",
            help="TCP port to bind the server to.",
        ),
    ] = 8000,
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            help="Bearer token for securing endpoints (overrides CORTEX_API_KEY).",
        ),
    ] = None,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Log level for uvicorn (critical, error, warning, info, debug, trace).",
        ),
    ] = "info",
    watch: Annotated[
        bool,
        typer.Option(
            "--watch",
            "-w",
            help="Enable continuous background repository watcher alongside server daemon.",
        ),
    ] = False,
    sync_interval: Annotated[
        float | None,
        typer.Option(
            "--sync-interval",
            help="Polling interval in seconds for background watcher (defaults to config.yaml).",
        ),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config-path",
            "-c",
            help="Custom configuration path.",
        ),
    ] = None,
) -> None:
    """Launch the agent-cortex daemon HTTP server."""
    import cortex.server

    cfg = load_config(config_path)
    effective_api_key = api_key or cfg.remote.api_key
    profile = cfg.get_active_profile()

    auth_status = (
        "[green]Enabled (Bearer token required)[/green]"
        if effective_api_key
        else "[yellow]Disabled (Open access)[/yellow]"
    )
    watcher_status = (
        "[green]Active (Background sync enabled)[/green]"
        if (watch or cfg.sync.auto_watch)
        else "[dim]Disabled[/dim]"
    )

    console.print(
        Panel(
            f"[bold cyan]agent-cortex[/bold cyan] daemon server\n\n"
            f"Endpoint: [bold green]http://{host}:{port}[/bold green]\n"
            f"Authentication: {auth_status}\n"
            f"Continuous Watcher: {watcher_status}\n"
            f"Hardware Profile: [cyan]{profile.name}[/cyan]\n"
            f"Storage: [dim]{cfg.storage.data_dir}[/dim]",
            title="Cortex Hub Daemon",
            border_style="cyan",
        )
    )

    try:
        cortex.server.run_server(
            host=host,
            port=port,
            api_key=effective_api_key,
            config=cfg,
            log_level=log_level,
            watch=watch,
            watch_interval=sync_interval,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Server stopped.[/yellow]")


def app_compact(
    table: Annotated[
        str,
        typer.Option(
            "--table",
            "-t",
            help="Target table to compact or 'all' for all tables.",
        ),
    ] = "all",
    prune_all: Annotated[
        bool,
        typer.Option(
            "--prune-all",
            help="Remove all older table fragments and versions (cleanup_older_than=0).",
        ),
    ] = False,
    delete_unverified: Annotated[
        bool,
        typer.Option(
            "--delete-unverified/--no-delete-unverified",
            help="Purge unreferenced transaction files leftover from interrupted writes.",
        ),
    ] = True,
    clean_orphans: Annotated[
        bool,
        typer.Option(
            "--clean-orphans",
            help="Purge chunks not in manifest.json (or specified in --keep).",
        ),
    ] = False,
    keep: Annotated[
        str | None,
        typer.Option(
            "--keep",
            "-k",
            help="Comma-separated repository names to retain (overrides manifest.json).",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Stream machine-readable JSON compaction results.",
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
    """Optimize, compact, and prune old fragments in LanceDB vector tables."""
    run_compaction(
        table=table,
        prune_all=prune_all,
        delete_unverified=delete_unverified,
        clean_orphans=clean_orphans,
        keep=keep,
        json_output=json_output,
        config_path=config_path,
    )


def app_clean_orphans(
    keep: Annotated[
        str | None,
        typer.Option(
            "--keep",
            "-k",
            help="Comma-separated repository names to retain (overrides manifest.json).",
        ),
    ] = None,
    table: Annotated[
        str,
        typer.Option(
            "--table",
            "-t",
            help="Target table to clean or 'all' for all tables.",
        ),
    ] = "all",
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Stream machine-readable JSON cleanup results.",
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
    """Purge vector chunks for repositories no longer tracked in manifest or specified in --keep."""
    run_clean_orphans(
        keep=keep,
        table=table,
        json_output=json_output,
        config_path=config_path,
    )
