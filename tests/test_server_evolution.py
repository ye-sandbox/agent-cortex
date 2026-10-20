"""Tests for server /timeline, /changelog, and /history/scan endpoints."""

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from cortex.config.loader import CortexConfig
from cortex.models.drift import ChangeKind, ContractType, DriftSeverity
from cortex.models.evolution import (
    ArchitecturalChangelog,
    ChangelogRelease,
    ContractEvolutionEvent,
    ContractEvolutionTimeline,
)
from cortex.server import create_app
from cortex.storage.manager import StorageManager


def test_server_timeline_endpoint() -> None:
    event = ContractEvolutionEvent(
        id=ContractEvolutionEvent.build_id(
            "sentinel", "sha123", ContractType.OPENAPI, ChangeKind.REMOVED, "GET /deals"
        ),
        repo="sentinel",
        commit_sha="sha123",
        commit_date="2026-10-20T10:00:00Z",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.CRITICAL,
        identifier="GET /deals",
        file_path="openapi.json",
        summary="Removed deals",
    )
    timeline = ContractEvolutionTimeline.from_events([event], repo="sentinel")

    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.table_names.return_value = []
    app = create_app(config=CortexConfig(), storage=mock_storage)

    with patch("cortex.server.routes.evolution.ContractEvolutionEngine") as mock_engine_cls:
        mock_engine = MagicMock()
        mock_engine_cls.from_config.return_value = mock_engine
        mock_engine.get_timeline.return_value = timeline

        with TestClient(app) as client:
            resp = client.get("/timeline?repo=sentinel&breaking_only=true")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_events"] == 1
            assert data["breaking_count"] == 1
            assert data["events"][0]["identifier"] == "GET /deals"


def test_server_changelog_endpoint() -> None:
    release = ChangelogRelease(
        tag_or_period="v1.0.0",
        date="2026-10-20",
        repo="sentinel",
        breaking_count=0,
        total_changes=1,
    )
    changelog = ArchitecturalChangelog(
        title="Sentinel Changelog",
        repo="sentinel",
        releases=[release],
        total_breaking=0,
        total_changes=1,
    )

    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.table_names.return_value = []
    app = create_app(config=CortexConfig(), storage=mock_storage)

    with patch("cortex.server.routes.evolution.ContractEvolutionEngine") as mock_engine_cls:
        mock_engine = MagicMock()
        mock_engine_cls.from_config.return_value = mock_engine
        mock_engine.synthesize_changelog.return_value = changelog

        with TestClient(app) as client:
            # Test JSON format
            resp_json = client.get("/changelog?repo=sentinel")
            assert resp_json.status_code == 200
            data = resp_json.json()
            assert data["total_changes"] == 1

            # Test Markdown format
            resp_md = client.get("/changelog?repo=sentinel&format=markdown")
            assert resp_md.status_code == 200
            assert "text/markdown" in resp_md.headers["content-type"]
            assert "## [v1.0.0]" in resp_md.text


def test_server_history_scan_endpoint() -> None:
    mock_storage = MagicMock(spec=StorageManager)
    mock_storage.table_names.return_value = []
    app = create_app(config=CortexConfig(), storage=mock_storage)

    with (
        patch("cortex.server.resolve_sync_sources") as mock_sources,
        patch("cortex.server.routes.evolution.ContractEvolutionEngine") as mock_engine_cls,
    ):
        mock_src = MagicMock()
        mock_src.enabled = True
        mock_src.get_repo_name.return_value = "repo-x"
        mock_src.path = "/fake/repo-x"
        mock_sources.return_value = [mock_src]

        mock_engine = MagicMock()
        mock_engine_cls.from_config.return_value = mock_engine
        mock_engine.scan_git_history.return_value = [MagicMock()]

        with TestClient(app) as client:
            resp = client.post("/history/scan?repo=repo-x&max_commits=10")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["discovered_events"] == 1
