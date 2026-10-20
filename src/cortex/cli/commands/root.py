"""Root command implementations and facade for agent-cortex CLI.

Provides version, storage compaction shims, and aggregates decoupled command modules
(bootstrap, sync, search, status, benchmark, serve, and mcp).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cortex.cli.commands.benchmark import benchmark_cmd
from cortex.cli.commands.bootstrap import bootstrap_cmd
from cortex.cli.commands.search import search_cmd
from cortex.cli.commands.serve import mcp_server_cmd, serve_cmd
from cortex.cli.commands.status import status_cmd
from cortex.cli.commands.storage import run_clean_orphans, run_compaction
from cortex.cli.commands.sync import sync_cmd
from cortex.cli.common import console


def version_cmd() -> None:
    """Print the version of agent-cortex."""
    from cortex import __version__

    console.print(f"[bold cyan]agent-cortex[/bold cyan] version [green]{__version__}[/green]")


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


__all__ = [
    "app_clean_orphans",
    "app_compact",
    "benchmark_cmd",
    "bootstrap_cmd",
    "mcp_server_cmd",
    "search_cmd",
    "serve_cmd",
    "status_cmd",
    "sync_cmd",
    "version_cmd",
]
