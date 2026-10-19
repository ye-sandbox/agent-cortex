"""Models CLI commands for pre-caching and listing ONNX models."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

import cortex.cli
from cortex.cli.common import console
from cortex.config.loader import load_config
from cortex.models.lifecycle import ModelDownloadError
from cortex.models.profile import (
    PREDEFINED_PROFILES,
    resolve_hardware_profile,
)

models_app = typer.Typer(
    name="models",
    help="Manage and pre-cache local ONNX models for agent-cortex.",
    no_args_is_help=True,
)


@models_app.command(name="download")
def models_download(
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Hardware profile tier (high, balanced, low, code). Defaults to config profile.",
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
            results = cortex.cli.download_profile_models(
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
