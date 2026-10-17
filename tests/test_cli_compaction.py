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
