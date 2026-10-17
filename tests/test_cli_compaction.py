"""Tests for CLI compaction and benchmarking subcommands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cortex.cli import app
from cortex.config.loader import CortexConfig, save_config
from cortex.ingestion.manifest import ManifestManager, RepoSyncState
from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    DocumentChunk,
)
from cortex.storage.manager import StorageManager

runner = CliRunner()


def _populate_test_storage(data_dir: Path, table_name: str = "chunks") -> None:
    storage = StorageManager(data_dir=data_dir)
    chunks = [
        DocumentChunk(
            id=f"repo-alpha:doc_{i}.md:c0",
            repo="repo-alpha",
            file_path=f"doc_{i}.md",
            category=ChunkCategory.DOC,
            lifecycle=ChunkLifecycle.ACTIVE,
            scope=ChunkScope.INTERNAL,
            breadcrumb="Section",
            commit_sha="11112222",
            tags=["alpha", "test"],
            content=f"Alpha document content {i}",
            vector=[0.1, 0.2, 0.3, 0.4],
        )
        for i in range(5)
    ]
    chunks.append(
        DocumentChunk(
            id="orphan-repo:doc_0.md:c0",
            repo="orphan-repo",
            file_path="doc_0.md",
            category=ChunkCategory.DOC,
            lifecycle=ChunkLifecycle.ACTIVE,
            scope=ChunkScope.INTERNAL,
            breadcrumb="Section",
            commit_sha="33334444",
            tags=["orphan"],
            content="Orphan repo content",
            vector=[0.4, 0.3, 0.2, 0.1],
        )
    )
    storage.upsert_chunks(chunks, table_name=table_name, dim=4)


def test_cli_compact_help() -> None:
    """Ensure both cortex compact and cortex storage compact provide help."""
    res1 = runner.invoke(app, ["compact", "--help"])
    assert res1.exit_code == 0
    assert "Optimize, compact, and prune" in res1.stdout

    res2 = runner.invoke(app, ["storage", "compact", "--help"])
    assert res2.exit_code == 0
    assert "Optimize, compact, and prune" in res2.stdout


def test_cli_compact_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure compact handles empty storage gracefully."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    result = runner.invoke(app, ["compact", "--config-path", str(config_file)])
    assert result.exit_code == 0
    assert "No tables found in storage" in result.stdout


def test_cli_compact_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure compact executes successfully on populated storage."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    _populate_test_storage(data_dir)

    result = runner.invoke(app, ["compact", "--config-path", str(config_file)])
    assert result.exit_code == 0
    assert "Compaction complete" in result.stdout
    assert "chunks" in result.stdout
    assert "Fragments" in result.stdout
    assert "Versions" in result.stdout


def test_cli_compact_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure compact --json returns structured JSON metrics with native telemetry."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    _populate_test_storage(data_dir)

    result = runner.invoke(app, ["compact", "--json", "--config-path", str(config_file)])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["table_name"] == "chunks"
    assert data[0]["chunks_count"] == 6
    assert "bytes_before" in data[0]
    assert "bytes_after" in data[0]
    assert "fragments_before" in data[0]
    assert "fragments_after" in data[0]
    assert "versions_before" in data[0]
    assert "versions_after" in data[0]


def test_cli_compact_clean_orphans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure compact --clean-orphans purges chunks not in manifest."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    _populate_test_storage(data_dir)

    # Setup manifest with only repo-alpha (orphan-repo is missing)
    manifest_mgr = ManifestManager(data_dir / "manifest.json")
    manifest = manifest_mgr.load()
    manifest.repositories["repo-alpha"] = RepoSyncState(
        repo_name="repo-alpha",
        repo_path="/tmp/repo-alpha",
        last_synced_commit="11112222",
        last_synced_at="2026-10-17T00:00:00",
        chunk_count=5,
        file_count=5,
    )
    manifest_mgr.save(manifest)

    result = runner.invoke(
        app,
        ["compact", "--clean-orphans", "--json", "--config-path", str(config_file)],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data[0]["chunks_count"] == 5


def test_cli_benchmark_empty_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure benchmark on empty table warns user to run with --synthetic."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    result = runner.invoke(app, ["benchmark", "--config-path", str(config_file)])
    assert result.exit_code == 1
    assert "Database table is empty" in result.stdout


def test_cli_benchmark_synthetic_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure benchmark with --synthetic and --json generates report."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    result = runner.invoke(
        app,
        [
            "benchmark",
            "--synthetic",
            "--synthetic-repos",
            "2",
            "--synthetic-chunks",
            "3",
            "-n",
            "1",
            "--profile",
            "low",
            "--no-rerank",
            "--json",
            "--config-path",
            str(config_file),
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["profile"] == "low"
    assert data["total_chunks"] == 6
    assert data["total_repos"] == 2
    assert "stage1_vector" in data
    assert "stage1_fts" in data
    assert "stage1_hybrid" in data
    assert "end_to_end" in data


def test_cli_clean_orphans_help() -> None:
    """Ensure both cortex clean-orphans and storage clean-orphans provide help with --keep."""
    res1 = runner.invoke(app, ["clean-orphans", "--help"])
    assert res1.exit_code == 0
    assert "--keep" in res1.stdout
    assert "overrides manifest.json" in res1.stdout

    res2 = runner.invoke(app, ["storage", "clean-orphans", "--help"])
    assert res2.exit_code == 0
    assert "--keep" in res2.stdout
    assert "overrides manifest.json" in res2.stdout


def test_cli_clean_orphans_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure clean-orphans handles empty storage gracefully."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    result = runner.invoke(app, ["storage", "clean-orphans", "--config-path", str(config_file)])
    assert result.exit_code == 0
    assert "No tables found in storage to clean" in result.stdout

    result_json = runner.invoke(
        app, ["storage", "clean-orphans", "--json", "--config-path", str(config_file)]
    )
    assert result_json.exit_code == 0
    assert json.loads(result_json.stdout) == []


def test_cli_clean_orphans_default_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure clean-orphans purges chunks not in manifest by default."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    _populate_test_storage(data_dir)

    manifest_mgr = ManifestManager(data_dir / "manifest.json")
    manifest = manifest_mgr.load()
    manifest.repositories["repo-alpha"] = RepoSyncState(
        repo_name="repo-alpha",
        repo_path="/tmp/repo-alpha",
        last_synced_commit="11112222",
        last_synced_at="2026-10-17T00:00:00",
        chunk_count=5,
        file_count=5,
    )
    manifest_mgr.save(manifest)

    result = runner.invoke(
        app,
        ["storage", "clean-orphans", "--config-path", str(config_file)],
    )
    assert result.exit_code == 0
    assert "Orphan cleanup complete" in result.stdout
    assert "repo-alpha" in result.stdout

    storage = StorageManager(data_dir=data_dir)
    assert storage.count_chunks() == 5


def test_cli_clean_orphans_keep_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure --keep overrides manifest.json retention list."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    _populate_test_storage(data_dir)

    # Set up manifest that tracks BOTH repo-alpha and orphan-repo
    manifest_mgr = ManifestManager(data_dir / "manifest.json")
    manifest = manifest_mgr.load()
    manifest.repositories["repo-alpha"] = RepoSyncState(
        repo_name="repo-alpha",
        repo_path="/tmp/repo-alpha",
        last_synced_commit="11112222",
        last_synced_at="2026-10-17T00:00:00",
        chunk_count=5,
        file_count=5,
    )
    manifest.repositories["orphan-repo"] = RepoSyncState(
        repo_name="orphan-repo",
        repo_path="/tmp/orphan-repo",
        last_synced_commit="33334444",
        last_synced_at="2026-10-17T00:00:00",
        chunk_count=1,
        file_count=1,
    )
    manifest_mgr.save(manifest)

    # Now run clean-orphans specifying --keep repo-alpha
    # Even though orphan-repo is in manifest, it MUST be purged!
    result = runner.invoke(
        app,
        [
            "storage",
            "clean-orphans",
            "--keep",
            "repo-alpha",
            "--json",
            "--config-path",
            str(config_file),
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data) == 1
    assert data[0]["table_name"] == "chunks"
    assert data[0]["purged_chunks"] == 1
    assert data[0]["remaining_chunks"] == 5
    assert data[0]["retained_repos"] == ["repo-alpha"]

    storage = StorageManager(data_dir=data_dir)
    assert storage.count_chunks() == 5
    assert storage.get_indexed_repos() == ["repo-alpha"]


def test_cli_clean_orphans_keep_invalid_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure passing empty/whitespace --keep raises an error."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    _populate_test_storage(data_dir)

    result = runner.invoke(
        app,
        ["storage", "clean-orphans", "--keep", " ,  ", "--config-path", str(config_file)],
    )
    assert result.exit_code == 1
    assert "--keep was provided but no valid repository names" in result.stdout


def test_cli_clean_orphans_no_manifest_no_keep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure clean-orphans warns and skips deletion if no manifest and no --keep."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    _populate_test_storage(data_dir)

    result = runner.invoke(
        app,
        ["storage", "clean-orphans", "--config-path", str(config_file)],
    )
    assert result.exit_code == 0
    assert "No active repositories found in manifest and no --keep specified" in result.stdout

    storage = StorageManager(data_dir=data_dir)
    assert storage.count_chunks() == 6


def test_cli_compact_keep_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure cortex compact --keep repo1 overrides manifest.json."""
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig()
    cfg.storage.data_dir = data_dir
    save_config(cfg, config_file)
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    _populate_test_storage(data_dir)

    result = runner.invoke(
        app,
        [
            "compact",
            "--clean-orphans",
            "--keep",
            "repo-alpha",
            "--json",
            "--config-path",
            str(config_file),
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data[0]["chunks_count"] == 5
