"""Hermetic tests for cortex timeline, changelog, and history CLI commands."""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cortex.cli import app
from cortex.models.drift import ChangeKind, ContractType, DriftSeverity
from cortex.models.evolution import (
    ArchitecturalChangelog,
    ChangelogRelease,
    ChangelogSection,
    ContractEvolutionEvent,
    ContractEvolutionTimeline,
)

runner = CliRunner()


def test_cli_timeline_empty() -> None:
    empty_timeline = ContractEvolutionTimeline.from_events([], repo="my-repo")

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_contract_timeline.return_value = empty_timeline

        res = runner.invoke(app, ["timeline", "my-repo"])
        assert res.exit_code == 0
        assert "No contract evolution events found" in res.output


def test_cli_timeline_table_and_json() -> None:
    event = ContractEvolutionEvent(
        id=ContractEvolutionEvent.build_id(
            "sentinel", "sha123", ContractType.OPENAPI, ChangeKind.REMOVED, "DELETE /deals"
        ),
        repo="sentinel",
        commit_sha="sha12345678",
        commit_date="2026-10-20T10:00:00Z",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.CRITICAL,
        identifier="DELETE /deals",
        file_path="openapi.json",
        summary="Removed bulk delete",
    )
    timeline = ContractEvolutionTimeline.from_events([event], repo="sentinel")

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_contract_timeline.return_value = timeline

        # Table output
        res_table = runner.invoke(app, ["timeline", "sentinel"])
        assert res_table.exit_code == 0
        assert "sentinel @ sha1234" in res_table.output
        assert "DELETE" in res_table.output
        assert "deals" in res_table.output

        # JSON output
        res_json = runner.invoke(app, ["timeline", "sentinel", "--json"])
        assert res_json.exit_code == 0
        data = json.loads(res_json.output)
        assert data["total_events"] == 1
        assert data["breaking_count"] == 1


def test_cli_changelog_rich_and_json() -> None:
    release = ChangelogRelease(
        tag_or_period="v1.0.0",
        date="2026-10-20",
        repo="core-api",
        breaking_count=0,
        total_changes=1,
        sections=[
            ChangelogSection(title="✨ Additions & Enhancements", events=[]),
        ],
    )
    changelog = ArchitecturalChangelog(
        title="Portfolio Changelog",
        repo="core-api",
        releases=[release],
        total_breaking=0,
        total_changes=1,
    )

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.synthesize_changelog.return_value = changelog

        res_rich = runner.invoke(app, ["changelog", "core-api"])
        assert res_rich.exit_code == 0
        assert "v1.0.0" in res_rich.output

        res_json = runner.invoke(app, ["changelog", "core-api", "--json"])
        assert res_json.exit_code == 0
        data = json.loads(res_json.output)
        assert data["total_changes"] == 1


def test_cli_history_scan() -> None:
    with (
        patch("cortex.cli.commands.evolution.resolve_sync_sources") as mock_sources,
        patch("cortex.cli.commands.evolution.ContractEvolutionEngine") as mock_engine_cls,
    ):
        mock_src = MagicMock()
        mock_src.enabled = True
        mock_src.get_repo_name.return_value = "test-repo"
        mock_src.path = "/tmp/fake-repo"
        mock_sources.return_value = [mock_src]

        mock_engine = MagicMock()
        mock_engine_cls.from_config.return_value = mock_engine
        mock_engine.scan_git_history.return_value = [MagicMock(), MagicMock()]

        res = runner.invoke(app, ["history", "scan", "test-repo", "--json"])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["status"] == "ok"
        assert data["total_events_recorded"] == 2
