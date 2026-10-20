"""Sync command implementation for agent-cortex CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

import cortex.cli
from cortex.cli.commands.watcher import run_watcher_cli
from cortex.cli.common import console
from cortex.config.loader import load_config
from cortex.ingestion.discovery import resolve_sync_sources


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
