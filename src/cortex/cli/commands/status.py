"""Status command implementation for agent-cortex CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from cortex.cli.common import console
from cortex.config.loader import load_config
from cortex.ingestion.manifest import ManifestManager


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
