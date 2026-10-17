"""CLI entrypoint for agent-cortex."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cortex.config.loader import (
    CortexConfig,
    get_default_config_path,
    load_config,
    save_config,
)
from cortex.models.lifecycle import ModelDownloadError, download_profile_models
from cortex.models.profile import (
    PREDEFINED_PROFILES,
    HardwareProfileName,
    resolve_hardware_profile,
)

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


def main() -> None:
    """Main CLI execution entrypoint."""
    app()


if __name__ == "__main__":
    main()
