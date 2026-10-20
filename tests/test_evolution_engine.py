"""Unit and integration tests for ContractEvolutionEngine."""

from pathlib import Path

from cortex.ingestion.git import run_git
from cortex.models.drift import (
    ChangeKind,
    ContractDriftAlert,
    ContractType,
    DriftSeverity,
)
from cortex.retrieval.evolution import ContractEvolutionEngine
from cortex.storage.manager import StorageManager

SAMPLE_OPENAPI_V1 = """
openapi: "3.0.0"
info:
  title: Test API
  version: "1.0.0"
paths:
  /items:
    get:
      summary: List items
      responses:
        "200":
          description: OK
"""

SAMPLE_OPENAPI_V2 = """
openapi: "3.0.0"
info:
  title: Test API
  version: "2.0.0"
paths:
  /items:
    get:
      summary: List items
      deprecated: true
      responses:
        "200":
          description: OK
  /items/{id}:
    get:
      summary: Get item
      responses:
        "200":
          description: OK
"""


def test_evolution_engine_record_and_get_timeline(tmp_path: Path) -> None:
    storage = StorageManager(data_dir=tmp_path / "data")
    engine = ContractEvolutionEngine(storage_manager=storage)

    alerts = [
        ContractDriftAlert(
            id=ContractDriftAlert.build_id(
                "repo-alpha",
                "openapi.json",
                ContractType.OPENAPI,
                ChangeKind.REMOVED,
                "DELETE /items",
            ),
            repo="repo-alpha",
            file_path="openapi.json",
            contract_type=ContractType.OPENAPI,
            change_kind=ChangeKind.REMOVED,
            severity=DriftSeverity.CRITICAL,
            identifier="DELETE /items",
            summary="Removed delete items endpoint",
            impacted_repos=["repo-beta"],
        ),
        ContractDriftAlert(
            id=ContractDriftAlert.build_id(
                "repo-alpha",
                "openapi.json",
                ContractType.OPENAPI,
                ChangeKind.ADDED,
                "POST /items",
            ),
            repo="repo-alpha",
            file_path="openapi.json",
            contract_type=ContractType.OPENAPI,
            change_kind=ChangeKind.ADDED,
            severity=DriftSeverity.INFO,
            identifier="POST /items",
            summary="Added post items endpoint",
        ),
    ]

    events = engine.record_alerts(
        repo="repo-alpha",
        commit_sha="c0011223344",
        alerts=alerts,
        commit_date="2026-10-20T10:00:00Z",
        author="Architect",
        version_tag="v1.0.0",
    )
    assert len(events) == 2

    # Query full timeline
    timeline = engine.get_timeline(repo="repo-alpha")
    assert timeline.total_events == 2
    assert timeline.breaking_count == 1
    assert timeline.info_count == 1
    assert "repo-beta" in timeline.impacted_repos_summary

    # Query breaking only
    breaking_timeline = engine.get_timeline(repo="repo-alpha", breaking_only=True)
    assert breaking_timeline.total_events == 1
    assert breaking_timeline.events[0].identifier == "DELETE /items"

    # Query by change kind
    added_timeline = engine.get_timeline(repo="repo-alpha", change_kind=ChangeKind.ADDED)
    assert added_timeline.total_events == 1
    assert added_timeline.events[0].identifier == "POST /items"


def test_evolution_engine_synthesize_changelog(tmp_path: Path) -> None:
    storage = StorageManager(data_dir=tmp_path / "data")
    engine = ContractEvolutionEngine(storage_manager=storage)

    alerts = [
        ContractDriftAlert(
            id=ContractDriftAlert.build_id(
                "core-service",
                "openapi.json",
                ContractType.OPENAPI,
                ChangeKind.REMOVED,
                "GET /v1/old",
            ),
            repo="core-service",
            file_path="openapi.json",
            contract_type=ContractType.OPENAPI,
            change_kind=ChangeKind.REMOVED,
            severity=DriftSeverity.HIGH,
            identifier="GET /v1/old",
            summary="Removed old v1 endpoint",
            impacted_repos=["consumer-app"],
        ),
        ContractDriftAlert(
            id=ContractDriftAlert.build_id(
                "core-service",
                "openapi.json",
                ContractType.OPENAPI,
                ChangeKind.ADDED,
                "GET /v2/new",
            ),
            repo="core-service",
            file_path="openapi.json",
            contract_type=ContractType.OPENAPI,
            change_kind=ChangeKind.ADDED,
            severity=DriftSeverity.INFO,
            identifier="GET /v2/new",
            summary="Introduced v2 endpoint",
        ),
    ]

    engine.record_alerts(
        repo="core-service",
        commit_sha="abcd1234ef",
        alerts=alerts,
        commit_date="2026-10-20T12:00:00Z",
        version_tag="v2.0.0",
    )

    changelog = engine.synthesize_changelog(repo="core-service", group_by="release")
    assert changelog.total_changes == 2
    assert changelog.total_breaking == 1
    assert len(changelog.releases) == 1
    rel = changelog.releases[0]
    assert rel.tag_or_period == "v2.0.0"
    assert rel.breaking_count == 1
    assert "consumer-app" in rel.impacted_repos

    md = engine.render_markdown(changelog)
    assert "## [v2.0.0]" in md
    assert "🚨 Breaking Changes" in md
    assert "✨ Additions & Enhancements" in md


def test_evolution_engine_scan_git_history(tmp_path: Path) -> None:
    storage = StorageManager(data_dir=tmp_path / "data")
    engine = ContractEvolutionEngine(storage_manager=storage)

    # Setup git repo
    repo_dir = tmp_path / "repo-test"
    repo_dir.mkdir()
    run_git(repo_dir, ["init", "-b", "main"])
    run_git(repo_dir, ["config", "user.name", "Tester"])
    run_git(repo_dir, ["config", "user.email", "tester@example.com"])

    # Commit 1: Initial OpenAPI
    openapi_file = repo_dir / "openapi.yaml"
    openapi_file.write_text(SAMPLE_OPENAPI_V1, encoding="utf-8")
    run_git(repo_dir, ["add", "openapi.yaml"])
    run_git(repo_dir, ["commit", "-m", "feat: initial openapi spec"])
    run_git(repo_dir, ["tag", "v1.0.0"])

    # Commit 2: Update OpenAPI with deprecation and new endpoint
    openapi_file.write_text(SAMPLE_OPENAPI_V2, encoding="utf-8")
    run_git(repo_dir, ["add", "openapi.yaml"])
    run_git(repo_dir, ["commit", "-m", "feat: add get item and deprecate list"])
    run_git(repo_dir, ["tag", "v1.1.0"])

    events = engine.scan_git_history(
        repo_path=repo_dir,
        repo_name="repo-test",
        max_commits=10,
    )
    assert len(events) >= 1

    # Verify stored events
    timeline = engine.get_timeline(repo="repo-test")
    assert timeline.total_events >= 1
    assert any(e.version_tag in ("v1.1.0", "v1.0.0") for e in timeline.events)
