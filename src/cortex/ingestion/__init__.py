"""Incremental ingestion and Git drift tracking subsystem for agent-cortex."""

from __future__ import annotations

from cortex.ingestion.engine import IngestionEngine
from cortex.ingestion.git import (
    get_git_common_dir,
    get_git_root,
    get_head_commit,
    is_commit_valid,
    is_git_repository,
    list_tracked_files,
    scan_git_drift,
)
from cortex.ingestion.manifest import ManifestManager, RepoSyncState, SyncManifest
from cortex.ingestion.models import (
    FileChange,
    FileChangeType,
    GitDriftSummary,
    SyncResult,
)
from cortex.ingestion.watcher import (
    RepoWatcher,
    RepoWatchStatus,
    WatcherConfig,
    WatcherSummary,
)

__all__ = [
    "FileChange",
    "FileChangeType",
    "GitDriftSummary",
    "IngestionEngine",
    "ManifestManager",
    "RepoSyncState",
    "RepoWatchStatus",
    "RepoWatcher",
    "SyncManifest",
    "SyncResult",
    "WatcherConfig",
    "WatcherSummary",
    "get_git_common_dir",
    "get_git_root",
    "get_head_commit",
    "is_commit_valid",
    "is_git_repository",
    "list_tracked_files",
    "scan_git_drift",
]
