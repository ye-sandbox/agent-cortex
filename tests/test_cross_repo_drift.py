"""Tests for cross-repository contract drift impact correlation and escalation."""

from pathlib import Path

import pytest

from cortex.models.drift import ChangeKind, ContractType, DriftSeverity
from cortex.models.graph import CodeDependency, CodeSignature, DependencyEdgeType
from cortex.retrieval.drift import ContractDriftEngine
from cortex.storage.manager import StorageManager


@pytest.fixture
def storage(tmp_path: Path) -> StorageManager:
    """Fixture providing storage manager with indexed cross-repo dependency."""
    mgr = StorageManager(data_dir=tmp_path / "data")
    # Seed dependency from 'web-portal' calling 'billing-service'
    dep = CodeDependency(
        id=CodeDependency.build_id(
            source_repo="web-portal",
            source_file="src/checkout.ts",
            edge_type=DependencyEdgeType.CALL,
            target_module="billing-service",
            target_symbol="process_payment",
            line_number=42,
        ),
        source_repo="web-portal",
        source_file="src/checkout.ts",
        source_symbol="onCheckout",
        edge_type=DependencyEdgeType.CALL,
        target_module="billing-service",
        target_symbol="process_payment",
        target_repo="billing-service",
        line_number=42,
        raw_statement="billingService.process_payment(cartTotal)",
    )
    mgr.upsert_dependencies([dep])
    return storage_mgr_with_sigs(mgr)


def storage_mgr_with_sigs(mgr: StorageManager) -> StorageManager:
    """Helper to seed initial code signatures."""
    sig = CodeSignature(
        id=CodeSignature.build_id(
            repo="billing-service",
            file_path="src/api.py",
            kind="function",
            identifier="process_payment",
        ),
        repo="billing-service",
        file_path="src/api.py",
        language="python",
        kind="function",
        identifier="process_payment",
        signature="def process_payment(amount: float) -> bool:",
        line_start=15,
        line_end=20,
        exported=True,
    )
    mgr.upsert_signatures([sig])
    return mgr


def test_cross_repo_impact_escalates_to_critical(storage: StorageManager) -> None:
    """Verify that removing an exported symbol called by another repo escalates to CRITICAL."""
    engine = ContractDriftEngine(storage_manager=storage)

    old_sigs = storage.get_signatures(where="repo = 'billing-service'")
    assert len(old_sigs) == 1

    # billing-service deletes process_payment
    new_sigs: list[CodeSignature] = []

    raw_alerts = engine.diff_signatures(
        repo="billing-service",
        file_path="src/api.py",
        old_signatures=old_sigs,
        new_signatures=new_sigs,
    )

    assert len(raw_alerts) == 1
    # Before cross-repo resolution: HIGH
    assert raw_alerts[0].severity == DriftSeverity.HIGH
    assert raw_alerts[0].change_kind == ChangeKind.REMOVED
    assert raw_alerts[0].contract_type == ContractType.CODE_SIGNATURE

    # Resolve cross-repo impact
    resolved_alerts = engine.resolve_cross_repo_impact(raw_alerts)
    assert len(resolved_alerts) == 1
    escalated = resolved_alerts[0]

    # Escalated to CRITICAL due to dependent in 'web-portal'
    assert escalated.severity == DriftSeverity.CRITICAL
    assert "[BREAKING CROSS-REPO]" in escalated.summary
    assert "web-portal" in escalated.impacted_repos
    assert "web-portal:src/checkout.ts:42" in escalated.impacted_callers
