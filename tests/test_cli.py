"""Hermetic CLI tests for agent-cortex."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cortex.cli import app
from cortex.config.loader import (
    CortexConfig,
    RepositorySourceConfig,
    SourcesConfig,
    save_config,
)
from cortex.ingestion.manifest import ManifestManager, RepoSyncState
from cortex.ingestion.models import SyncResult
from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    SearchResultChunk,
)
from cortex.models.lifecycle import ModelDownloadError

runner = CliRunner()


def test_cli_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "agent-cortex version" in result.stdout


def test_cli_bootstrap_new_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(data_dir))

    result = runner.invoke(
        app,
        [
            "bootstrap",
            "--config-path",
            str(config_file),
            "--profile",
            "low",
            "--no-download-models",
        ],
    )

    assert result.exit_code == 0
    assert "Configuration written to" in result.stdout
    assert "Active hardware profile: low" in result.stdout
    assert "Model download skipped" in result.stdout
    assert config_file.is_file()


def test_cli_bootstrap_with_model_download(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"

    with patch(
        "cortex.cli.download_profile_models",
        return_value={"embedding": Path("/tmp/emb"), "reranker": Path("/tmp/rerank")},
    ) as mock_download:
        result = runner.invoke(
            app,
            [
                "bootstrap",
                "--config-path",
                str(config_file),
                "--profile",
                "balanced",
            ],
        )

    assert result.exit_code == 0
    assert "Cached 2 model(s) successfully" in result.stdout
    assert mock_download.called


def test_cli_bootstrap_existing_config_without_force(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("profile: balanced\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "bootstrap",
            "--config-path",
            str(config_file),
            "--no-download-models",
        ],
    )

    assert result.exit_code == 0
    assert "Found existing configuration" in result.stdout


def test_cli_bootstrap_invalid_profile(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"

    result = runner.invoke(
        app,
        [
            "bootstrap",
            "--config-path",
            str(config_file),
            "--profile",
            "nonexistent_tier",
            "--no-download-models",
        ],
    )

    assert result.exit_code == 1
    assert "Error:" in result.stdout


def test_cli_bootstrap_download_error(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"

    with patch(
        "cortex.cli.download_profile_models",
        side_effect=ModelDownloadError("BAAI/bge-small-en-v1.5", "Connection timed out"),
    ):
        result = runner.invoke(
            app,
            [
                "bootstrap",
                "--config-path",
                str(config_file),
                "--profile",
                "balanced",
            ],
        )

    assert result.exit_code == 1
    assert "Model download failed" in result.stdout
    assert "Diagnostic:" in result.stdout


def test_cli_models_download_success() -> None:
    with patch(
        "cortex.cli.download_profile_models",
        return_value={"embedding": Path("/tmp/emb")},
    ) as mock_download:
        result = runner.invoke(
            app,
            [
                "models",
                "download",
                "--profile",
                "low",
                "--cache-dir",
                "/tmp/cache",
            ],
        )

    assert result.exit_code == 0
    assert "Successfully cached 1 model(s) for profile 'low'" in result.stdout
    assert mock_download.called


def test_cli_models_download_invalid_profile() -> None:
    result = runner.invoke(app, ["models", "download", "--profile", "unknown_tier"])
    assert result.exit_code == 1
    assert "Error: Unknown hardware profile 'unknown_tier'" in result.stdout


def test_cli_models_download_network_error() -> None:
    with patch(
        "cortex.cli.download_profile_models",
        side_effect=ModelDownloadError("BAAI/bge-m3", "HF Hub unreachable"),
    ):
        result = runner.invoke(app, ["models", "download", "--profile", "high"])

    assert result.exit_code == 1
    assert "Model download failed" in result.stdout
    assert "Diagnostic: Check your internet connection" in result.stdout


def test_cli_models_list() -> None:
    result = runner.invoke(app, ["models", "list"])
    assert result.exit_code == 0
    assert "Hardware Profiles & Models" in result.stdout
    assert "balanced" in result.stdout
    assert "high" in result.stdout
    assert "low" in result.stdout


def test_cli_sync_no_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.yaml"
    cfg = CortexConfig()
    save_config(cfg, config_file)

    non_git_dir = tmp_path / "empty"
    non_git_dir.mkdir()
    monkeypatch.chdir(non_git_dir)

    result = runner.invoke(app, ["sync", "--config-path", str(config_file)])
    assert result.exit_code == 1
    assert "No repositories configured or discovered for sync" in result.stdout


def test_cli_sync_repo_not_found(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    cfg = CortexConfig()
    save_config(cfg, config_file)

    result = runner.invoke(
        app,
        ["sync", "--config-path", str(config_file), "--repo", "non_existent_repo"],
    )
    assert result.exit_code == 1
    assert "Repository 'non_existent_repo' not found" in result.stdout


def test_cli_sync_success_single_repo(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    repo_dir = tmp_path / "sample-repo"
    repo_dir.mkdir()

    cfg = CortexConfig(
        sources=SourcesConfig(
            repositories=[RepositorySourceConfig(path=repo_dir, name="sample-repo")]
        )
    )
    save_config(cfg, config_file)

    mock_result = SyncResult(
        repo="sample-repo",
        base_commit=None,
        target_commit="abcdef123456",
        added_chunks=5,
        updated_chunks=0,
        deleted_chunks=0,
        processed_files=2,
        duration_seconds=0.15,
    )

    with patch("cortex.cli.IngestionEngine.from_config") as mock_engine_factory:
        mock_engine = MagicMock()
        mock_engine.sync_repository.return_value = mock_result
        mock_engine_factory.return_value = mock_engine

        result = runner.invoke(app, ["sync", "--config-path", str(config_file)])

    assert result.exit_code == 0
    assert "sample-repo" in result.stdout
    assert "abcdef12" in result.stdout
    assert "✓ Synced" in result.stdout
    assert "All repositories synchronized successfully" in result.stdout


def test_cli_sync_with_errors(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    repo_dir = tmp_path / "failing-repo"
    repo_dir.mkdir()

    cfg = CortexConfig(
        sources=SourcesConfig(
            repositories=[RepositorySourceConfig(path=repo_dir, name="failing-repo")]
        )
    )
    save_config(cfg, config_file)

    mock_result = SyncResult(
        repo="failing-repo",
        base_commit=None,
        target_commit="112233445566",
        errors=["Failed to parse OpenAPI schema: malformed JSON"],
    )

    with patch("cortex.cli.IngestionEngine.from_config") as mock_engine_factory:
        mock_engine = MagicMock()
        mock_engine.sync_repository.return_value = mock_result
        mock_engine_factory.return_value = mock_engine

        result = runner.invoke(app, ["sync", "--config-path", str(config_file)])

    assert result.exit_code == 1
    assert "✗ Failed" in result.stdout
    assert "Failed to parse OpenAPI schema" in result.stdout


def test_cli_search_empty_query() -> None:
    result = runner.invoke(app, ["search", "   "])
    assert result.exit_code == 0
    assert "Empty query provided" in result.stdout


def test_cli_search_no_results(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    cfg = CortexConfig()
    save_config(cfg, config_file)

    with patch("cortex.cli.HybridRetrievalPipeline.from_config") as mock_factory:
        mock_pipeline = MagicMock()
        mock_pipeline.search.return_value = []
        mock_factory.return_value = mock_pipeline

        result = runner.invoke(app, ["search", "nonexistent", "--config-path", str(config_file)])

    assert result.exit_code == 0
    assert "No matching chunks found" in result.stdout


def test_cli_search_human_output(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    cfg = CortexConfig()
    save_config(cfg, config_file)

    chunk = SearchResultChunk(
        id="sentinel:specs/openapi.json:get_deals",
        repo="sentinel",
        file_path="specs/openapi.json",
        category=ChunkCategory.CONTRACT,
        lifecycle=ChunkLifecycle.ACTIVE,
        scope=ChunkScope.INTERNAL,
        breadcrumb="GET /deals",
        score=0.8842,
        content="GET /deals operation contract",
        snippet="Retrieve active deals list",
        tags=["deals", "GET"],
    )

    with patch("cortex.cli.HybridRetrievalPipeline.from_config") as mock_factory:
        mock_pipeline = MagicMock()
        mock_pipeline.search.return_value = [chunk]
        mock_factory.return_value = mock_pipeline

        result = runner.invoke(app, ["search", "deals", "--config-path", str(config_file)])

    assert result.exit_code == 0
    assert "found 1 matching chunk(s)" in result.stdout
    assert "[sentinel]" in result.stdout
    assert "specs/openapi.json" in result.stdout
    assert "GET /deals" in result.stdout
    assert "#deals" in result.stdout


def test_cli_search_ndjson_output(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    cfg = CortexConfig()
    save_config(cfg, config_file)

    chunk = SearchResultChunk(
        id="ia-maestri:.agent/ECOSYSTEM.md:c1",
        repo="ia-maestri",
        file_path=".agent/ECOSYSTEM.md",
        category=ChunkCategory.DOC,
        lifecycle=ChunkLifecycle.ACTIVE,
        scope=ChunkScope.INTERNAL,
        breadcrumb="Ecosystem Overview",
        score=0.9123,
        content="Agent architecture and contracts",
        snippet="Agent architecture...",
        tags=["maestri"],
    )

    with patch("cortex.cli.HybridRetrievalPipeline.from_config") as mock_factory:
        mock_pipeline = MagicMock()
        mock_pipeline.search.return_value = [chunk]
        mock_factory.return_value = mock_pipeline

        result = runner.invoke(
            app,
            ["search", "maestri", "--json", "--config-path", str(config_file)],
        )

    assert result.exit_code == 0
    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["id"] == "ia-maestri:.agent/ECOSYSTEM.md:c1"
    assert parsed["repo"] == "ia-maestri"
    assert parsed["score"] == 0.9123


def test_cli_search_invalid_filters(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    cfg = CortexConfig()
    save_config(cfg, config_file)

    result_scope = runner.invoke(
        app,
        ["search", "query", "--scope", "invalid_scope", "--config-path", str(config_file)],
    )
    assert result_scope.exit_code == 1
    assert "Invalid scope 'invalid_scope'" in result_scope.stdout

    result_cat = runner.invoke(
        app,
        ["search", "query", "--category", "invalid_category", "--config-path", str(config_file)],
    )
    assert result_cat.exit_code == 1
    assert "Invalid category 'invalid_category'" in result_cat.stdout


def test_cli_status_human_and_json(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    cfg = CortexConfig(storage={"data_dir": data_dir})
    save_config(cfg, config_file)

    manifest_mgr = ManifestManager(data_dir / "manifest.json")
    manifest_mgr.update_repo_state(
        "test-repo",
        RepoSyncState(
            repo_name="test-repo",
            repo_path="/path/to/test-repo",
            last_synced_commit="1234567890abcdef",
            chunk_count=42,
            file_count=7,
        ),
    )

    result_human = runner.invoke(app, ["status", "--config-path", str(config_file)])
    assert result_human.exit_code == 0
    assert "System Vitals" in result_human.stdout
    assert "test-repo" in result_human.stdout
    assert "42" in result_human.stdout

    result_json = runner.invoke(app, ["status", "--json", "--config-path", str(config_file)])
    assert result_json.exit_code == 0
    data = json.loads(result_json.stdout)
    assert data["profile"]["name"] == "balanced"
    assert "test-repo" in data["repositories"]
    assert data["repositories"]["test-repo"]["chunk_count"] == 42


def test_cli_mcp_help() -> None:
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "Launch Model Context Protocol (MCP) stdio server" in result.stdout


def test_cli_mcp_invokes_runner() -> None:
    with patch("cortex.mcp_server.main") as mock_server_main:
        result = runner.invoke(app, ["mcp"])
        assert result.exit_code == 0
        assert mock_server_main.called
