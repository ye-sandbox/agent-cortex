"""CLI entrypoint for agent-cortex."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from cortex.config.loader import (
    CortexConfig,
    get_default_config_path,
    load_config,
    save_config,
)
from cortex.ingestion.discovery import resolve_sync_sources
from cortex.ingestion.engine import IngestionEngine
from cortex.ingestion.manifest import ManifestManager
from cortex.models.chunk import ChunkCategory, ChunkScope
from cortex.models.lifecycle import ModelDownloadError, download_profile_models
from cortex.models.profile import (
    PREDEFINED_PROFILES,
    HardwareProfileName,
    resolve_hardware_profile,
)
from cortex.retrieval.pipeline import HybridRetrievalPipeline
from cortex.storage.manager import StorageManager

app = typer.Typer(
    name="cortex",
    help="Cross-repository semantic memory and portfolio knowledge engine.",
    no_args_is_help=True,
)
models_app = typer.Typer(
    name="models",
    help="Manage and pre-cache local ONNX models for agent-cortex.",
    no_args_is_help=True,
)
app.add_typer(models_app, name="models")

console = Console()


@app.callback()
def cortex_callback() -> None:
    """agent-cortex: Cross-repository semantic memory and portfolio knowledge engine."""


@app.command()
def version() -> None:
    """Print the version of agent-cortex."""
    from cortex import __version__

    console.print(f"[bold cyan]agent-cortex[/bold cyan] version [green]{__version__}[/green]")


@app.command()
def bootstrap(
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Hardware profile tier to initialize (high, balanced, low).",
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
                results = download_profile_models(
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


@app.command()
def sync(
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
    sources = resolve_sync_sources(config=cfg, repo_filter=repo, all_flag=all_repos)

    if not sources:
        if repo:
            console.print(
                f"[bold red]Error:[/bold red] Repository '{repo}' not found "
                "in configuration or on filesystem."
            )
        else:
            console.print("[yellow]No repositories configured or discovered for sync.[/yellow]")
            console.print(
                "Run 'cortex sync --repo <path_or_name>' or configure repositories in config.yaml."
            )
        raise typer.Exit(code=1)

    console.print(
        f"[bold cyan]agent-cortex[/bold cyan] synchronizing "
        f"[bold]{len(sources)}[/bold] repository source(s)...\n"
    )

    engine = IngestionEngine.from_config(cfg)
    results = []

    with console.status("[bold green]Indexing repositories...[/bold green]") as status_bar:
        for src in sources:
            repo_name = src.get_repo_name()
            status_bar.update(f"Syncing [cyan]{repo_name}[/cyan]...")
            res = engine.sync_repository(
                repo_path=src.path,
                repo_name=repo_name,
                default_scope=src.default_scope,
                force_full=force_full,
            )
            results.append(res)

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


@app.command()
def search(
    query: Annotated[
        str,
        typer.Argument(help="Semantic query to search across portfolio knowledge."),
    ],
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Hardware profile tier override (high, balanced, low).",
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

    try:
        pipeline = HybridRetrievalPipeline.from_config(cfg, profile_override=profile)
        results = pipeline.search(
            query=cleaned_query,
            limit=limit,
            scopes=scopes,
            include_archived=include_archived,
            category=cat,
            repo=repo,
            rerank=rerank,
        )
    except Exception as exc:
        console.print(f"[bold red]Search failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from None

    if json_output:
        for res in results:
            typer.echo(res.model_dump_json())
        return

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


@app.command()
def status(
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


@models_app.command(name="download")
def models_download(
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Hardware profile tier (high, balanced, low). Defaults to config profile.",
        ),
    ] = None,
    cache_dir: Annotated[
        Path | None,
        typer.Option(
            "--cache-dir",
            help="Custom ONNX cache directory override.",
        ),
    ] = None,
) -> None:
    """Pre-cache embedding and reranker ONNX weights for a profile."""
    cfg = load_config()
    profile_name = profile or cfg.profile.value
    try:
        hw_profile = resolve_hardware_profile(profile_name, cfg.custom_profile)
    except ValueError as err:
        console.print(f"[bold red]Error:[/bold red] {err}")
        raise typer.Exit(code=1) from None

    console.print(f"Pre-caching models for profile '[bold cyan]{hw_profile.name}[/bold cyan]'...")
    try:
        with console.status(
            f"[bold green]Downloading weights for {hw_profile.name}...[/bold green]"
        ):
            results = download_profile_models(
                hw_profile,
                cache_dir=cache_dir,
                on_progress=lambda stage, name: console.print(
                    f"  → Downloading {stage} model: [cyan]{name}[/cyan]"
                ),
            )
        console.print(
            f"[bold green]✓[/bold green] Successfully cached {len(results)} model(s) "
            f"for profile '[cyan]{hw_profile.name}[/cyan]'."
        )
        for stage, path in results.items():
            console.print(f"    • {stage.capitalize()}: [dim]{path}[/dim]")
    except ModelDownloadError as err:
        console.print(f"[bold red]✗ Model download failed:[/bold red] {err}")
        console.print(
            "[yellow]Diagnostic:[/yellow] Check your internet connection or proxy settings. "
            "In air-gapped environments, configure local model weights or set HF_HUB_OFFLINE=1 "
            "after manual caching."
        )
        raise typer.Exit(code=1) from None


@models_app.command(name="list")
def models_list() -> None:
    """List available hardware profiles and their associated models."""
    table = Table(title="Hardware Profiles & Models", show_header=True)
    table.add_column("Profile", style="bold cyan")
    table.add_column("Embedding Model", style="green")
    table.add_column("Dim", justify="right")
    table.add_column("Reranker Model", style="yellow")
    table.add_column("Max Threads", justify="right")

    for p in PREDEFINED_PROFILES.values():
        table.add_row(
            p.name,
            p.embedding_model,
            str(p.embedding_dim),
            p.reranker_model or "[dim]None (Stage 1 only)[/dim]",
            str(p.max_threads),
        )
    console.print(table)


@app.command(name="mcp")
def mcp_server_cmd() -> None:
    """Launch Model Context Protocol (MCP) stdio server."""
    from cortex.mcp_server import main as run_mcp_server

    run_mcp_server()


def main() -> None:
    """Main CLI execution entrypoint."""
    app()


if __name__ == "__main__":
    main()
