"""Automated continuous background sync service (daemonized watcher).

Monitors configured and auto-discovered git portfolio repositories for commit drift,
triggering debounced incremental re-indexing via IngestionEngine with graceful shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from cortex.config.loader import CortexConfig, RepositorySourceConfig, load_config
from cortex.ingestion.discovery import resolve_sync_sources
from cortex.ingestion.engine import IngestionEngine
from cortex.ingestion.git import get_head_commit, is_git_repository
from cortex.ingestion.models import SyncResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WatcherConfig(BaseModel):
    """Configuration options for continuous repository watcher."""

    model_config = ConfigDict(str_strip_whitespace=True)

    interval: float = Field(
        default=30.0,
        ge=0.01,
        description="Polling interval in seconds between repository drift checks",
    )
    debounce: float = Field(
        default=2.0,
        ge=0.0,
        description="Debounce delay in seconds before triggering index sync",
    )
    repo: str | None = Field(
        default=None,
        description="Optional repository name or path filter",
    )
    all_repos: bool = Field(
        default=False,
        description="Watch all configured and auto-discovered repositories",
    )
    force_full: bool = Field(
        default=False,
        description="Force full re-indexing, bypassing incremental checkpoints",
    )
    auto_refresh_discovery: bool = Field(
        default=True,
        description="Periodically refresh auto-discovered repositories in portfolio roots",
    )


class RepoWatchStatus(BaseModel):
    """Real-time watch and synchronization state for a single monitored repository."""

    model_config = ConfigDict(str_strip_whitespace=True)

    repo_name: str
    repo_path: str
    last_checked_at: float | None = None
    last_synced_commit: str | None = None
    last_sync_at: float | None = None
    last_sync_status: str = "idle"  # "idle", "syncing", "synced", "error"
    total_syncs: int = 0
    errors: list[str] = Field(default_factory=list)


class WatcherSummary(BaseModel):
    """Aggregated status summary of the continuous background watcher service."""

    model_config = ConfigDict(str_strip_whitespace=True)

    is_running: bool = False
    started_at: float | None = None
    interval_seconds: float = 30.0
    tracked_repos_count: int = 0
    total_sync_runs: int = 0
    repositories: dict[str, RepoWatchStatus] = Field(default_factory=dict)


class RepoWatcher:
    """Continuous repository watcher detecting git drift and orchestrating incremental sync."""

    def __init__(
        self,
        config: CortexConfig | None = None,
        watcher_config: WatcherConfig | None = None,
        engine: IngestionEngine | None = None,
        on_sync_start: Callable[[str], None] | None = None,
        on_sync_complete: Callable[[SyncResult], None] | None = None,
        on_error: Callable[[str, Exception], None] | None = None,
    ) -> None:
        """Initialize repository watcher with config and optional notification callbacks."""
        self.config = config or load_config()
        self.watcher_config = watcher_config or WatcherConfig(
            interval=self.config.sync.interval,
            debounce=self.config.sync.debounce,
        )
        self.engine = engine or IngestionEngine.from_config(self.config)
        self.on_sync_start = on_sync_start
        self.on_sync_complete = on_sync_complete
        self.on_error = on_error

        self._stop_event = threading.Event()
        self._async_stop_event: asyncio.Event | None = None
        self._is_running = False
        self._started_at: float | None = None
        self._total_sync_runs = 0

        self._repo_statuses: dict[str, RepoWatchStatus] = {}
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Return whether watcher is currently executing its loop."""
        return self._is_running

    def resolve_monitored_sources(self) -> list[RepositorySourceConfig]:
        """Resolve all repository sources monitored during this cycle."""
        sources = resolve_sync_sources(
            config=self.config,
            repo_filter=self.watcher_config.repo,
            all_flag=self.watcher_config.all_repos,
        )
        with self._lock:
            for src in sources:
                name = src.get_repo_name()
                if name not in self._repo_statuses:
                    self._repo_statuses[name] = RepoWatchStatus(
                        repo_name=name,
                        repo_path=str(src.path),
                    )
        return sources

    def check_repo_drift(
        self,
        src: RepositorySourceConfig,
    ) -> tuple[bool, str | None, str | None]:
        """Inspect repository for commit drift between disk HEAD and manifest.

        Returns (has_drift, head_commit, base_commit).
        """
        repo_name = src.get_repo_name()
        repo_path = Path(src.path).expanduser().resolve()

        if not is_git_repository(repo_path):
            logger.warning("Path '%s' for repo '%s' is not a git repository", repo_path, repo_name)
            return False, None, None

        try:
            head_commit = get_head_commit(repo_path)
        except Exception as exc:
            logger.warning("Failed to resolve HEAD commit for '%s': %s", repo_name, exc)
            return False, None, None

        repo_state = self.engine.manifest.get_repo_state(repo_name)
        base_commit = None if repo_state is None else repo_state.last_synced_commit

        if self.watcher_config.force_full or base_commit is None or base_commit != head_commit:
            return True, head_commit, base_commit

        return False, head_commit, base_commit

    def scan_and_sync_once(self) -> list[SyncResult]:
        """Perform one complete evaluation cycle across all monitored repositories."""
        sources = self.resolve_monitored_sources()
        if not sources:
            logger.debug("Watcher found zero monitored repository sources.")
            return []

        drifting_sources: list[tuple[RepositorySourceConfig, str, str | None]] = []
        now = time.time()

        for src in sources:
            name = src.get_repo_name()
            with self._lock:
                status = self._repo_statuses.setdefault(
                    name,
                    RepoWatchStatus(repo_name=name, repo_path=str(src.path)),
                )
                status.last_checked_at = now

            has_drift, head_sha, base_sha = self.check_repo_drift(src)
            if has_drift and head_sha is not None:
                drifting_sources.append((src, head_sha, base_sha))

        if not drifting_sources:
            return []

        # Apply debounce delay to allow pending commits / file writes to settle
        if self.watcher_config.debounce > 0:
            logger.debug(
                "Debouncing %d drifting repository(ies) for %.1fs...",
                len(drifting_sources),
                self.watcher_config.debounce,
            )
            time.sleep(self.watcher_config.debounce)

        results: list[SyncResult] = []
        defer_fts = len(drifting_sources) > 1
        any_changes = False

        for src, head_sha, _base_sha in drifting_sources:
            if self._stop_event.is_set():
                logger.info("Watcher stop requested; aborting remaining sync queue.")
                break

            name = src.get_repo_name()
            logger.info("Detected drift in '%s' (syncing to %s)...", name, head_sha[:8])

            with self._lock:
                status = self._repo_statuses[name]
                status.last_sync_status = "syncing"

            if self.on_sync_start:
                try:
                    self.on_sync_start(name)
                except Exception as exc:
                    logger.debug("on_sync_start callback failed: %s", exc)

            try:
                res = self.engine.sync_repository(
                    repo_path=src.path,
                    repo_name=name,
                    default_scope=src.default_scope,
                    force_full=self.watcher_config.force_full,
                    defer_fts=defer_fts,
                )
                results.append(res)

                with self._lock:
                    status.last_sync_at = time.time()
                    status.last_synced_commit = res.target_commit
                    status.total_syncs += 1
                    status.last_sync_status = "synced" if res.is_success else "error"
                    if res.errors:
                        status.errors.extend(res.errors)

                if res.added_chunks > 0 or res.updated_chunks > 0 or res.deleted_chunks > 0:
                    any_changes = True

                if self.on_sync_complete:
                    try:
                        self.on_sync_complete(res)
                    except Exception as exc:
                        logger.debug("on_sync_complete callback failed: %s", exc)

            except Exception as exc:
                err_msg = f"Unexpected failure syncing repository '{name}': {exc}"
                logger.exception(err_msg)
                with self._lock:
                    status.last_sync_status = "error"
                    status.errors.append(err_msg)

                if self.on_error:
                    try:
                        self.on_error(name, exc)
                    except Exception as cb_exc:
                        logger.debug("on_error callback failed: %s", cb_exc)

        # Rebuild full-text and vector indexes if deferred
        if defer_fts and any_changes:
            logger.info("Rebuilding deferred FTS and vector indexes across batch...")
            try:
                self.engine.storage.create_fts_index()
                self.engine.storage.create_vector_index()
            except Exception as exc:
                logger.error("Failed to build deferred indexes: %s", exc)

        with self._lock:
            self._total_sync_runs += 1

        return results

    async def run_once_async(self) -> list[SyncResult]:
        """Asynchronously execute one drift detection and sync cycle in a worker thread."""
        return await asyncio.to_thread(self.scan_and_sync_once)

    async def run_loop_async(self, max_iterations: int | None = None) -> None:
        """Run continuous asynchronous monitoring loop until stopped or max_iterations reached."""
        self._is_running = True
        self._started_at = time.time()
        self._async_stop_event = asyncio.Event()
        iteration = 0

        logger.info(
            "Starting agent-cortex continuous sync watcher (interval=%.1fs, debounce=%.1fs)",
            self.watcher_config.interval,
            self.watcher_config.debounce,
        )

        try:
            while not self._stop_event.is_set():
                try:
                    await self.run_once_async()
                except Exception as exc:
                    logger.exception("Error during watcher cycle: %s", exc)

                iteration += 1
                if max_iterations is not None and iteration >= max_iterations:
                    logger.debug("Reached max iterations (%d); terminating loop.", max_iterations)
                    break

                # Sleep with immediate wake-up if stop event is triggered
                try:
                    await asyncio.wait_for(
                        self._async_stop_event.wait(),
                        timeout=self.watcher_config.interval,
                    )
                    break  # Stop event was set
                except TimeoutError:
                    continue  # Timeout expired, loop again

        finally:
            self._is_running = False
            logger.info("Agent-cortex continuous sync watcher loop stopped.")

    def run_blocking(self, max_iterations: int | None = None) -> None:
        """Run continuous monitoring loop synchronously, registering OS termination signals."""
        self._setup_signals()
        asyncio.run(self.run_loop_async(max_iterations=max_iterations))

    def stop(self) -> None:
        """Request immediate graceful termination of the monitoring loop."""
        self._stop_event.set()
        if self._async_stop_event is not None:
            self._async_stop_event.set()

    def get_status(self) -> WatcherSummary:
        """Return thread-safe snapshot of the watcher's current execution status."""
        with self._lock:
            return WatcherSummary(
                is_running=self._is_running,
                started_at=self._started_at,
                interval_seconds=self.watcher_config.interval,
                tracked_repos_count=len(self._repo_statuses),
                total_sync_runs=self._total_sync_runs,
                repositories=dict(self._repo_statuses),
            )

    def _setup_signals(self) -> None:
        """Install signal handlers for SIGINT and SIGTERM if running on main thread."""
        try:
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGINT, self._handle_signal)
                signal.signal(signal.SIGTERM, self._handle_signal)
        except (ValueError, AttributeError) as exc:
            logger.debug("Unable to register signal handlers: %s", exc)

    def _handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        """Signal handler triggering graceful shutdown."""
        sig_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        logger.info("Received %s signal. Stopping background watcher cleanly...", sig_name)
        self.stop()
