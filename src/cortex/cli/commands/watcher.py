"""Continuous background sync watcher CLI command."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel

import cortex.cli
from cortex.cli.common import console
from cortex.config.loader import CortexConfig, load_config
from cortex.ingestion.models import SyncResult
from cortex.ingestion.watcher import WatcherConfig


def run_watcher_cli(
    cfg: CortexConfig,
    effective_repo: str | None,
    all_repos: bool,
    interval: float,
    debounce: float,
    force_full: bool,
    json_output: bool,
) -> None:
    watcher_config = WatcherConfig(
        interval=interval,
        debounce=debounce,
        repo=effective_repo,
        all_repos=all_repos,
        force_full=force_full,
    )

    def on_sync_start(name: str) -> None:
        if json_output:
            print(json.dumps({"event": "sync_start", "repo": name}), flush=True)
        else:
            console.print(f"[bold cyan]agent-cortex[/bold cyan] syncing [cyan]{name}[/cyan]...")

    def on_sync_complete(res: SyncResult) -> None:
        if json_output:
            print(json.dumps({"event": "sync_complete", "result": res.model_dump()}), flush=True)
        else:
            base_str = res.base_commit[:8] if res.base_commit else "initial"
            target_str = res.target_commit[:8] if res.target_commit else "?"
            range_str = f"{base_str}..{target_str}" if res.base_commit else target_str
            if res.is_success:
                console.print(
                    f"[bold green]✓[/bold green] Synced [cyan]{res.repo}[/cyan] "
                    f"([dim]{range_str}[/dim]): +{res.added_chunks} ~{res.updated_chunks} "
                    f"-{res.deleted_chunks} chunks ({res.duration_seconds:.2f}s)"
                )
            else:
                console.print(
                    f"[bold red]✗[/bold red] Sync failed for [cyan]{res.repo}[/cyan]: "
                    f"{', '.join(res.errors)}"
                )

    def on_error(name: str, exc: Exception) -> None:
        if json_output:
            print(json.dumps({"event": "error", "repo": name, "error": str(exc)}), flush=True)
        else:
            console.print(f"[bold red]Error[/bold red] in watcher for [cyan]{name}[/cyan]: {exc}")

    watcher = cortex.cli.RepoWatcher(
        config=cfg,
        watcher_config=watcher_config,
        on_sync_start=on_sync_start,
        on_sync_complete=on_sync_complete,
        on_error=on_error,
    )

    sources = watcher.resolve_monitored_sources()
    if not sources:
        if effective_repo:
            console.print(
                f"[bold red]Error:[/bold red] Repository '{effective_repo}' not found "
                "in configuration or on filesystem."
            )
        else:
            console.print("[yellow]No repositories configured or discovered for watcher.[/yellow]")
        raise typer.Exit(code=1)

    if json_output:
        print(
            json.dumps(
                {
                    "event": "watcher_started",
                    "interval_seconds": interval,
                    "debounce_seconds": debounce,
                    "monitored_repositories": [s.get_repo_name() for s in sources],
                }
            ),
            flush=True,
        )
    else:
        console.print(
            Panel(
                f"[bold cyan]agent-cortex[/bold cyan] continuous background watcher active\n\n"
                f"Interval: [bold green]{interval:.1f}s[/bold green] | "
                f"Debounce: [bold green]{debounce:.1f}s[/bold green]\n"
                f"Monitored: [cyan]{len(sources)}[/cyan] repository(ies)\n"
                f"Storage: [dim]{cfg.storage.data_dir}[/dim]\n\n"
                f"[dim]Press Ctrl+C to stop watcher safely.[/dim]",
                title="Continuous Sync Watcher",
                border_style="cyan",
            )
        )

    with contextlib.suppress(KeyboardInterrupt):
        watcher.run_blocking()

    if json_output:
        print(json.dumps({"event": "watcher_stopped"}), flush=True)
    else:
        console.print("\n[yellow]Watcher stopped cleanly.[/yellow]")


def watch(
    target: Annotated[
        str | None,
        typer.Argument(
            help="Optional repository name, path, or portfolio directory to watch.",
        ),
    ] = None,
    repo: Annotated[
        str | None,
        typer.Option(
            "--repo",
            "-r",
            help="Watch a specific repository by name or filesystem path.",
        ),
    ] = None,
    all_repos: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="Watch all configured and auto-discovered repositories.",
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
    force_full: Annotated[
        bool,
        typer.Option(
            "--force-full",
            "-f",
            help="Force full re-indexing on detected drift.",
        ),
    ] = False,
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
    """Run automated continuous background sync service watching repositories for git drift."""
    cfg = load_config(config_path)
    effective_repo = repo or target
    run_watcher_cli(
        cfg=cfg,
        effective_repo=effective_repo,
        all_repos=all_repos,
        interval=interval,
        debounce=debounce,
        force_full=force_full,
        json_output=json_output,
    )
