"""Serve and MCP server command implementations for agent-cortex CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel

from cortex.cli.common import console
from cortex.config.loader import load_config


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
