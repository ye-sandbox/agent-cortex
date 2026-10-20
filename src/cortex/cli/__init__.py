"""CLI package and entrypoint for agent-cortex."""

from __future__ import annotations

import typer

from cortex.cli.commands.config import config_app
from cortex.cli.commands.deps import deps_app
from cortex.cli.commands.drift import drift_app
from cortex.cli.commands.evolution import changelog_cmd, history_app, timeline_cmd
from cortex.cli.commands.impact import impact_app
from cortex.cli.commands.intent import intent_app
from cortex.cli.commands.models import models_app
from cortex.cli.commands.root import (
    app_clean_orphans,
    app_compact,
    benchmark_cmd,
    bootstrap_cmd,
    mcp_server_cmd,
    search_cmd,
    serve_cmd,
    status_cmd,
    sync_cmd,
    version_cmd,
)
from cortex.cli.commands.storage import storage_app
from cortex.cli.commands.topology import topology_app
from cortex.cli.commands.watcher import watch

# Re-exported for test mock patching and backwards-compatibility
from cortex.client import CortexClient
from cortex.ingestion.engine import IngestionEngine
from cortex.ingestion.watcher import RepoWatcher
from cortex.models.lifecycle import download_profile_models
from cortex.retrieval.pipeline import HybridRetrievalPipeline

__all__ = [
    "CortexClient",
    "HybridRetrievalPipeline",
    "IngestionEngine",
    "RepoWatcher",
    "app",
    "config_app",
    "deps_app",
    "download_profile_models",
    "drift_app",
    "history_app",
    "impact_app",
    "intent_app",
    "main",
    "models_app",
    "storage_app",
    "topology_app",
]

app = typer.Typer(
    name="cortex",
    help="Cross-repository semantic memory and portfolio knowledge engine.",
    no_args_is_help=True,
)

# Register Sub-Typers
app.add_typer(models_app, name="models")
app.add_typer(storage_app, name="storage")
app.add_typer(config_app, name="config")
app.add_typer(deps_app, name="deps")
app.add_typer(drift_app, name="drift")
app.add_typer(impact_app, name="impact")
app.add_typer(intent_app, name="intent")
app.add_typer(topology_app, name="topology")
app.add_typer(history_app, name="history")


@app.callback()
def cortex_callback() -> None:
    """agent-cortex: Cross-repository semantic memory and portfolio knowledge engine."""


# Register Root Commands with explicit command names
app.command(name="version")(version_cmd)
app.command(name="bootstrap")(bootstrap_cmd)
app.command(name="sync")(sync_cmd)
app.command(name="watch")(watch)
app.command(name="search")(search_cmd)
app.command(name="timeline")(timeline_cmd)
app.command(name="changelog")(changelog_cmd)
app.command(name="status")(status_cmd)
app.command(name="compact")(app_compact)
app.command(name="clean-orphans")(app_clean_orphans)
app.command(name="benchmark")(benchmark_cmd)
app.command(name="bench", hidden=True)(benchmark_cmd)
app.command(name="mcp")(mcp_server_cmd)
app.command(name="serve")(serve_cmd)


def main() -> None:
    """Main CLI execution entrypoint."""
    app()


if __name__ == "__main__":
    main()
