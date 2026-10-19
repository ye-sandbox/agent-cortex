"""Storage management CLI commands (compaction and orphan cleanup)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.table import Table

from cortex.cli.common import _format_bytes, console
from cortex.config.loader import load_config
from cortex.ingestion.manifest import ManifestManager
from cortex.storage.manager import CompactionResult, StorageManager

storage_app = typer.Typer(
    name="storage",
    help="Manage LanceDB storage tables, compaction, and disk hygiene.",
    no_args_is_help=True,
)


def run_clean_orphans(
    keep: str | None = None,
    table: str = "all",
    json_output: bool = False,
    config_path: Path | None = None,
) -> None:
    cfg = load_config(config_path)
    storage = StorageManager(cfg.storage.data_dir)

    all_tables = storage.table_names()
    if not all_tables:
        if json_output:
            typer.echo(json.dumps([]))
            return
        console.print("[yellow]No tables found in storage to clean.[/yellow]")
        return

    target_tables = all_tables if table.lower() == "all" else [table]
    for t in target_tables:
        if t not in all_tables:
            console.print(f"[bold red]Error:[/bold red] Table '{t}' not found in storage.")
            raise typer.Exit(code=1)

    active_repos: list[str] = []
    if keep is not None:
        active_repos = [r.strip() for r in keep.split(",") if r.strip()]
        if not active_repos:
            console.print(
                "[bold red]Error:[/bold red] "
                "--keep was provided but no valid repository names were found."
            )
            raise typer.Exit(code=1)
    else:
        manifest_path = cfg.storage.data_dir / "manifest.json"
        if manifest_path.exists():
            manifest_mgr = ManifestManager(manifest_path)
            manifest = manifest_mgr.load()
            active_repos = list(manifest.repositories.keys())

    if not active_repos:
        if json_output:
            typer.echo(json.dumps([]))
            return
        console.print(
            "[yellow]No active repositories found in manifest and no --keep specified. "
            "Skipping orphan cleanup.[/yellow]"
        )
        return

    results: list[dict[str, Any]] = []
    for t in target_tables:
        purged = storage.cleanup_orphan_repos(active_repos, table_name=t)
        remaining = storage.count_chunks(table_name=t)
        results.append(
            {
                "table_name": t,
                "purged_chunks": purged,
                "remaining_chunks": remaining,
                "retained_repos": active_repos,
            }
        )

    if json_output:
        typer.echo(json.dumps(results, indent=2))
        return

    table_view = Table(title="Storage Orphan Repositories Cleanup", show_header=True)
    table_view.add_column("Table", style="bold cyan")
    table_view.add_column("Purged Chunks", justify="right", style="bold yellow")
    table_view.add_column("Remaining Chunks", justify="right", style="green")

    for r in results:
        table_view.add_row(
            r["table_name"],
            str(r["purged_chunks"]),
            str(r["remaining_chunks"]),
        )

    console.print(table_view)
    total_purged = sum(r["purged_chunks"] for r in results)
    console.print(
        f"\n[bold green]✓[/bold green] Orphan cleanup complete. "
        f"Total purged chunks: [bold yellow]{total_purged}[/bold yellow]. "
        f"Retained repos: [dim]{', '.join(active_repos)}[/dim]"
    )


def run_compaction(
    table: str = "all",
    prune_all: bool = False,
    delete_unverified: bool = True,
    clean_orphans: bool = False,
    keep: str | None = None,
    json_output: bool = False,
    config_path: Path | None = None,
) -> None:
    cfg = load_config(config_path)
    storage = StorageManager(cfg.storage.data_dir)

    all_tables = storage.table_names()
    if not all_tables:
        if json_output:
            typer.echo(json.dumps([]))
            return
        console.print("[yellow]No tables found in storage to compact.[/yellow]")
        return

    target_tables = all_tables if table.lower() == "all" else [table]
    for t in target_tables:
        if t not in all_tables:
            console.print(f"[bold red]Error:[/bold red] Table '{t}' not found in storage.")
            raise typer.Exit(code=1)

    if clean_orphans or keep is not None:
        active_repos: list[str] = []
        if keep is not None:
            active_repos = [r.strip() for r in keep.split(",") if r.strip()]
            if not active_repos:
                console.print(
                    "[bold red]Error:[/bold red] "
                    "--keep was provided but no valid repository names were found."
                )
                raise typer.Exit(code=1)
        else:
            manifest_path = cfg.storage.data_dir / "manifest.json"
            if manifest_path.exists():
                manifest_mgr = ManifestManager(manifest_path)
                manifest = manifest_mgr.load()
                active_repos = list(manifest.repositories.keys())

        if active_repos:
            for t in target_tables:
                purged = storage.cleanup_orphan_repos(active_repos, table_name=t)
                if not json_output and purged > 0:
                    console.print(
                        f"[yellow]Purged {purged} orphan chunk(s) from table '{t}'.[/yellow]"
                    )

    cleanup_delta = timedelta(days=0) if prune_all else None
    results: list[CompactionResult] = []

    for t in target_tables:
        res = storage.compact_table(
            table_name=t,
            cleanup_older_than=cleanup_delta,
            delete_unverified=delete_unverified,
        )
        results.append(res)

    if json_output:
        typer.echo(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
        return

    table_view = Table(title="LanceDB Table Compaction Summary", show_header=True)
    table_view.add_column("Table", style="bold cyan")
    table_view.add_column("Chunks", justify="right", style="green")
    table_view.add_column("Fragments", justify="right")
    table_view.add_column("Versions", justify="right")
    table_view.add_column("Size Before", justify="right")
    table_view.add_column("Size After", justify="right")
    table_view.add_column("Freed", justify="right", style="bold yellow")

    total_freed = sum(r.bytes_freed for r in results)
    for r in results:
        frag_str = (
            f"{r.fragments_before} → {r.fragments_after}"
            if r.fragments_before != r.fragments_after
            else str(r.fragments_after)
        )
        ver_str = (
            f"{r.versions_before} → {r.versions_after}"
            if r.versions_before != r.versions_after
            else str(r.versions_after)
        )
        table_view.add_row(
            r.table_name,
            str(r.chunks_count),
            frag_str,
            ver_str,
            _format_bytes(r.bytes_before),
            _format_bytes(r.bytes_after),
            _format_bytes(r.bytes_freed),
        )

    console.print(table_view)
    console.print(
        f"\n[bold green]✓[/bold green] Compaction complete. "
        f"Total disk space freed: [bold cyan]{_format_bytes(total_freed)}[/bold cyan]."
    )


@storage_app.command(name="compact")
def storage_compact(
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


@storage_app.command(name="clean-orphans")
def storage_clean_orphans(
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
