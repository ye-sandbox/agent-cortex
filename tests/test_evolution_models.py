"""Unit tests for ContractEvolution domain models."""

import pytest

from cortex.models.drift import ChangeKind, ContractType, DriftSeverity
from cortex.models.evolution import (
    ArchitecturalChangelog,
    ChangelogRelease,
    ChangelogSection,
    ContractEvolutionEvent,
    ContractEvolutionTimeline,
)


def test_contract_evolution_event_build_id() -> None:
    event_id = ContractEvolutionEvent.build_id(
        repo="sentinel-api",
        commit_sha="a1b2c3d4e5f67890",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        identifier="DELETE /deals/{id}",
    )
    assert event_id == "sentinel-api:a1b2c3d4e5f6:openapi:removed:DELETE_deals_id"

    event = ContractEvolutionEvent(
        id=event_id,
        repo="sentinel-api",
        commit_sha="a1b2c3d4e5f67890",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.HIGH,
        identifier="DELETE /deals/{id}",
        file_path="specs/openapi.json",
        summary="Endpoint DELETE /deals/{id} was removed",
        impacted_repos=["clipflow-worker"],
        impacted_callers=["clipflow-worker:src/client.ts:42"],
    )
    assert event.id == event_id
    assert event.repo == "sentinel-api"
    assert event.severity == DriftSeverity.HIGH
    assert "clipflow-worker" in event.impacted_repos


def test_contract_evolution_event_invalid_id() -> None:
    with pytest.raises(ValueError, match="does not start with repo prefix"):
        ContractEvolutionEvent(
            id="other-repo:abc:openapi:removed:test",
            repo="sentinel-api",
            commit_sha="abc",
            contract_type=ContractType.OPENAPI,
            change_kind=ChangeKind.REMOVED,
            severity=DriftSeverity.HIGH,
            identifier="test",
            file_path="openapi.json",
            summary="Test removal",
        )


def test_contract_evolution_timeline_from_events() -> None:
    e1 = ContractEvolutionEvent(
        id=ContractEvolutionEvent.build_id(
            "repo-a", "c1", ContractType.OPENAPI, ChangeKind.REMOVED, "GET /a"
        ),
        repo="repo-a",
        commit_sha="c1",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.CRITICAL,
        identifier="GET /a",
        file_path="openapi.json",
        summary="Removed endpoint",
        impacted_repos=["repo-b", "repo-c"],
    )
    e2 = ContractEvolutionEvent(
        id=ContractEvolutionEvent.build_id(
            "repo-a", "c1", ContractType.COMPOSE, ChangeKind.DEPRECATED, "services.db"
        ),
        repo="repo-a",
        commit_sha="c1",
        contract_type=ContractType.COMPOSE,
        change_kind=ChangeKind.DEPRECATED,
        severity=DriftSeverity.MEDIUM,
        identifier="services.db",
        file_path="compose.yaml",
        summary="Deprecated service",
    )
    e3 = ContractEvolutionEvent(
        id=ContractEvolutionEvent.build_id(
            "repo-a", "c2", ContractType.CODE_SIGNATURE, ChangeKind.ADDED, "ProcessItem"
        ),
        repo="repo-a",
        commit_sha="c2",
        contract_type=ContractType.CODE_SIGNATURE,
        change_kind=ChangeKind.ADDED,
        severity=DriftSeverity.LOW,
        identifier="ProcessItem",
        file_path="src/main.py",
        summary="Added function",
    )

    timeline = ContractEvolutionTimeline.from_events([e1, e2, e3], repo="repo-a")
    assert timeline.total_events == 3
    assert timeline.breaking_count == 1
    assert timeline.warning_count == 1
    assert timeline.info_count == 1
    assert timeline.impacted_repos_summary == {"repo-b": 1, "repo-c": 1}


def test_architectural_changelog_to_markdown() -> None:
    e_breaking = ContractEvolutionEvent(
        id=ContractEvolutionEvent.build_id(
            "sentinel", "c123", ContractType.OPENAPI, ChangeKind.REMOVED, "DELETE /deals"
        ),
        repo="sentinel",
        commit_sha="c123",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.REMOVED,
        severity=DriftSeverity.CRITICAL,
        identifier="DELETE /deals",
        file_path="specs/openapi.json",
        summary="Removed bulk delete",
        details="Endpoint removed in favor of /deals/batch",
        impacted_repos=["clipflow"],
        impacted_callers=["clipflow:src/sync.ts:15"],
    )
    e_added = ContractEvolutionEvent(
        id=ContractEvolutionEvent.build_id(
            "sentinel", "c123", ContractType.OPENAPI, ChangeKind.ADDED, "POST /deals/batch"
        ),
        repo="sentinel",
        commit_sha="c123",
        contract_type=ContractType.OPENAPI,
        change_kind=ChangeKind.ADDED,
        severity=DriftSeverity.INFO,
        identifier="POST /deals/batch",
        file_path="specs/openapi.json",
        summary="Batch deals creation",
    )

    release = ChangelogRelease(
        tag_or_period="v2.0.0",
        date="2026-10-20",
        repo="sentinel",
        breaking_count=1,
        total_changes=2,
        sections=[
            ChangelogSection(title="🚨 Breaking Changes", events=[e_breaking]),
            ChangelogSection(title="✨ Additions & Enhancements", events=[e_added]),
        ],
        impacted_repos=["clipflow"],
    )

    changelog = ArchitecturalChangelog(
        title="Sentinel Architecture Changelog",
        repo="sentinel",
        releases=[release],
        total_breaking=1,
        total_changes=2,
    )

    md = changelog.to_markdown()
    assert "# Sentinel Architecture Changelog — `sentinel`" in md
    assert "## [v2.0.0] (2026-10-20)" in md
    assert "⚠️ **Downstream Portfolio Impact:** `clipflow`" in md
    assert "### 🚨 Breaking Changes" in md
    assert "**[CRITICAL]** `DELETE /deals`: Removed bulk delete" in md
    assert "*Impacted Repos:* `clipflow`" in md
    assert "*Impacted Callers:* `clipflow:src/sync.ts:15`" in md
    assert "### ✨ Additions & Enhancements" in md
    assert "**[INFO]** `POST /deals/batch`: Batch deals creation" in md
