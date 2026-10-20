"""CLI command sub-modules for agent-cortex."""

from cortex.cli.commands.benchmark import benchmark_cmd
from cortex.cli.commands.bootstrap import bootstrap_cmd
from cortex.cli.commands.config import config_app
from cortex.cli.commands.deps import deps_app
from cortex.cli.commands.drift import drift_app
from cortex.cli.commands.evolution import changelog_cmd, history_app, timeline_cmd
from cortex.cli.commands.impact import impact_app
from cortex.cli.commands.intent import intent_app
from cortex.cli.commands.models import models_app
from cortex.cli.commands.root import app_clean_orphans, app_compact, version_cmd
from cortex.cli.commands.search import search_cmd
from cortex.cli.commands.serve import mcp_server_cmd, serve_cmd
from cortex.cli.commands.status import status_cmd
from cortex.cli.commands.storage import storage_app
from cortex.cli.commands.sync import sync_cmd
from cortex.cli.commands.topology import topology_app
from cortex.cli.commands.watcher import watch

__all__ = [
    "app_clean_orphans",
    "app_compact",
    "benchmark_cmd",
    "bootstrap_cmd",
    "changelog_cmd",
    "config_app",
    "deps_app",
    "drift_app",
    "history_app",
    "impact_app",
    "intent_app",
    "mcp_server_cmd",
    "models_app",
    "search_cmd",
    "serve_cmd",
    "status_cmd",
    "storage_app",
    "sync_cmd",
    "timeline_cmd",
    "topology_app",
    "version_cmd",
    "watch",
]
