"""Hermetic CLI tests for agent-cortex."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cortex.cli import app
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
