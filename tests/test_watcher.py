"""Hermetic unit and integration tests for continuous background sync watcher."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest

from cortex.config.loader import CortexConfig, RepositorySourceConfig, SyncConfig
from cortex.ingestion.engine import IngestionEngine
from cortex.ingestion.manifest import ManifestManager
from cortex.ingestion.models import SyncResult
from cortex.ingestion.watcher import (
    RepoWatcher,
    WatcherConfig,
    WatcherSummary,
)
from cortex.storage.manager import StorageManager


def _init_mock_repo(repo_dir: Path) -> None:
    """Initialize a git repo with user configuration for testing."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test Agent"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "agent@cortex.test"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )


def _commit_file(repo_dir: Path, rel_path: str, content: str, msg: str) -> str:
    """Write file, stage, commit, and return commit SHA."""
    target_file = repo_dir / rel_path
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=repo_dir, check=True, capture_output=True)
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


class MockEmbeddingEngine:
    """Fast mock embedding engine returning deterministic float vectors without ONNX."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed_chunks(self, chunks: list[Any]) -> list[Any]:
        results: list[Any] = []
        for idx, chunk in enumerate(chunks):
            val = float(idx + 1) / float(self.dim)
            results.append(chunk.model_copy(update={"vector": [val] * self.dim}))
        return results

    def embed_query(self, query: str) -> list[float]:
        return [0.1] * self.dim


def test_watcher_config_models() -> None:
    """Verify default configurations for WatcherConfig, SyncConfig, and WatcherSummary."""
    sync_cfg = SyncConfig()
    assert sync_cfg.interval == 30.0
    assert sync_cfg.debounce == 2.0
    assert sync_cfg.auto_watch is False

    w_cfg = WatcherConfig()
    assert w_cfg.interval == 30.0
    assert w_cfg.debounce == 2.0
    assert w_cfg.repo is None
    assert w_cfg.all_repos is False

    summary = WatcherSummary()
    assert summary.is_running is False
    assert summary.tracked_repos_count == 0
    assert summary.repositories == {}


def test_watcher_drift_detection_and_sync_cycle(tmp_path: Path) -> None:
    """Verify drift detection, debounced execution, and state manifest tracking."""
    repo_dir = tmp_path / "mock-service"
    _init_mock_repo(repo_dir)

    # Initial commit
    c1 = _commit_file(
        repo_dir,
        "README.md",
        "# Mock Service\nProvides core caching capabilities.",
        "Initial commit",
    )

    data_dir = tmp_path / "data"
    storage = StorageManager(data_dir=data_dir)
    manifest = ManifestManager(manifest_path=data_dir / "manifest.json")
    mock_emb = MockEmbeddingEngine()
    engine = IngestionEngine(
        storage_manager=storage,
        embedding_engine=mock_emb,  # type: ignore[arg-type]
        manifest_manager=manifest,
    )

    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    cfg.sources.repositories = [
        RepositorySourceConfig(path=repo_dir, name="mock-service"),
    ]

    watcher_cfg = WatcherConfig(
        interval=0.1,
        debounce=0.0,
        all_repos=True,
    )

    sync_started: list[str] = []
    sync_completed: list[SyncResult] = []

    watcher = RepoWatcher(
        config=cfg,
        watcher_config=watcher_cfg,
        engine=engine,
        on_sync_start=lambda name: sync_started.append(name),
        on_sync_complete=lambda res: sync_completed.append(res),
    )

    # 1. First cycle: detects initial drift and indexes repository
    results_1 = watcher.scan_and_sync_once()
    assert len(results_1) == 1
    assert results_1[0].repo == "mock-service"
    assert results_1[0].target_commit == c1
    assert results_1[0].added_chunks > 0
    assert sync_started == ["mock-service"]
    assert len(sync_completed) == 1

    status = watcher.get_status()
    assert "mock-service" in status.repositories
    repo_stat = status.repositories["mock-service"]
    assert repo_stat.total_syncs == 1
    assert repo_stat.last_synced_commit == c1
    assert repo_stat.last_sync_status == "synced"

    # 2. Second cycle immediately: zero drift, no sync
    results_2 = watcher.scan_and_sync_once()
    assert results_2 == []
    assert len(sync_completed) == 1  # No new sync triggered

    # 3. Third cycle after new commit: detects drift and syncs incrementally
    c2 = _commit_file(
        repo_dir,
        "compose.yaml",
        "services:\n  redis:\n    image: redis:7-alpine\n    ports:\n      - '6379:6379'\n",
        "Add compose file",
    )
    results_3 = watcher.scan_and_sync_once()
    assert len(results_3) == 1
    assert results_3[0].base_commit == c1
    assert results_3[0].target_commit == c2
    assert results_3[0].added_chunks > 0
    assert len(sync_completed) == 2


@pytest.mark.anyio
async def test_watcher_async_loop_and_graceful_stop(tmp_path: Path) -> None:
    """Verify asynchronous execution loop terminates cleanly upon max_iterations or stop()."""
    repo_dir = tmp_path / "async-repo"
    _init_mock_repo(repo_dir)
    _commit_file(repo_dir, "README.md", "# Async Test Repo", "init")

    data_dir = tmp_path / "data"
    storage = StorageManager(data_dir=data_dir)
    manifest = ManifestManager(manifest_path=data_dir / "manifest.json")
    mock_emb = MockEmbeddingEngine()
    engine = IngestionEngine(
        storage_manager=storage,
        embedding_engine=mock_emb,  # type: ignore[arg-type]
        manifest_manager=manifest,
    )

    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    cfg.sources.repositories = [
        RepositorySourceConfig(path=repo_dir, name="async-repo"),
    ]

    watcher = RepoWatcher(
        config=cfg,
        watcher_config=WatcherConfig(interval=0.05, debounce=0.0, all_repos=True),
        engine=engine,
    )

    # 1. Run loop bounded by max_iterations
    await watcher.run_loop_async(max_iterations=2)
    assert watcher.is_running is False
    status = watcher.get_status()
    assert status.total_sync_runs == 1  # 1st had drift, 2nd had 0 drift

    # 2. Run loop in task and stop explicitly
    task = asyncio.create_task(watcher.run_loop_async())
    await asyncio.sleep(0.02)
    assert watcher.is_running is True
    watcher.stop()
    await task
    assert watcher.is_running is False


def test_watcher_non_git_or_error_handling(tmp_path: Path) -> None:
    """Verify that non-git paths or unexpected errors are caught gracefully."""
    non_git = tmp_path / "not-git"
    non_git.mkdir()

    cfg = CortexConfig()
    cfg.sources.repositories = [
        RepositorySourceConfig(path=non_git, name="not-git"),
    ]

    errors_caught: list[tuple[str, Exception]] = []
    watcher = RepoWatcher(
        config=cfg,
        watcher_config=WatcherConfig(interval=0.1, debounce=0.0, all_repos=True),
        on_error=lambda name, exc: errors_caught.append((name, exc)),
    )

    results = watcher.scan_and_sync_once()
    assert results == []
    has_drift, head_sha, _ = watcher.check_repo_drift(cfg.sources.repositories[0])
    assert has_drift is False
    assert head_sha is None
