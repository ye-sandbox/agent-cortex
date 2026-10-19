"""Hermetic CLI tests for cortex watch and cortex sync --watch commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cortex.cli import app
from cortex.config.loader import CortexConfig, RepositorySourceConfig, save_config

runner = CliRunner()


def test_cli_watch_help() -> None:
    """Verify watch command options and help documentation."""
    result = runner.invoke(app, ["watch", "--help"])
    assert result.exit_code == 0
    assert "--interval" in result.stdout
    assert "--debounce" in result.stdout
    assert "--force-full" in result.stdout
    assert "--json" in result.stdout


def test_cli_sync_watch_options_help() -> None:
    """Verify sync command exposes continuous watch options."""
    result = runner.invoke(app, ["sync", "--help"])
    assert result.exit_code == 0
    assert "--watch" in result.stdout
    assert "--interval" in result.stdout
    assert "--debounce" in result.stdout


def test_cli_watch_missing_repository(tmp_path: Path) -> None:
    """Verify watch errors when specified repository is not found."""
    cfg = CortexConfig()
    config_file = tmp_path / "config.yaml"
    save_config(cfg, config_file)

    result = runner.invoke(
        app,
        ["watch", "--repo", "non-existent-repo", "--config-path", str(config_file)],
    )
    assert result.exit_code == 1
    assert "Repository 'non-existent-repo' not found" in result.stdout


def test_cli_watch_invokes_watcher(tmp_path: Path) -> None:
    """Verify watch command initializes RepoWatcher and calls run_blocking."""
    repo_dir = tmp_path / "repo1"
    repo_dir.mkdir()
    cfg = CortexConfig()
    cfg.sources.repositories = [RepositorySourceConfig(path=repo_dir, name="repo1")]
    config_file = tmp_path / "config.yaml"
    save_config(cfg, config_file)

    with patch("cortex.cli.RepoWatcher") as mock_watcher_cls:
        mock_instance = MagicMock()
        mock_instance.resolve_monitored_sources.return_value = cfg.sources.repositories
        mock_watcher_cls.return_value = mock_instance

        result = runner.invoke(
            app,
            [
                "watch",
                "--config-path",
                str(config_file),
                "--interval",
                "15.0",
                "--debounce",
                "1.0",
            ],
        )

        assert result.exit_code == 0
        mock_watcher_cls.assert_called_once()
        mock_instance.run_blocking.assert_called_once()


def test_cli_sync_watch_flag_invokes_watcher(tmp_path: Path) -> None:
    """Verify sync --watch delegates to continuous watcher runner."""
    repo_dir = tmp_path / "repo2"
    repo_dir.mkdir()
    cfg = CortexConfig()
    cfg.sources.repositories = [RepositorySourceConfig(path=repo_dir, name="repo2")]
    config_file = tmp_path / "config.yaml"
    save_config(cfg, config_file)

    with patch("cortex.cli.RepoWatcher") as mock_watcher_cls:
        mock_instance = MagicMock()
        mock_instance.resolve_monitored_sources.return_value = cfg.sources.repositories
        mock_watcher_cls.return_value = mock_instance

        result = runner.invoke(
            app,
            [
                "sync",
                "--watch",
                "--config-path",
                str(config_file),
                "--interval",
                "10.0",
            ],
        )

        assert result.exit_code == 0
        mock_watcher_cls.assert_called_once()
        mock_instance.run_blocking.assert_called_once()
