"""Bootstrap command implementation for agent-cortex CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel

import cortex.cli
from cortex.cli.common import console
from cortex.config.loader import (
    CortexConfig,
    get_default_config_path,
    load_config,
    save_config,
)
from cortex.models.lifecycle import ModelDownloadError
from cortex.models.profile import HardwareProfileName


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
