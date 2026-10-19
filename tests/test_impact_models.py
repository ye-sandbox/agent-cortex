"""Unit tests for impact simulation and caller tracing domain models."""

from __future__ import annotations

import pytest

from cortex.models.graph import DependencyEdgeType
from cortex.models.impact import (
    BlastRadiusSeverity,
    BlastRadiusSimulationReport,
    BlastRadiusSimulationRequest,
    CallerChain,
    CallerChainHop,
    ImpactAdvisory,
    ImpactedNode,
    ImpactTraceResult,
)


def test_blast_radius_severity_properties() -> None:
    """Verify BlastRadiusSeverity helper methods."""
    assert BlastRadiusSeverity.CRITICAL.is_breaking is True
    assert BlastRadiusSeverity.HIGH.is_breaking is True
    assert BlastRadiusSeverity.MEDIUM.is_breaking is False
    assert BlastRadiusSeverity.LOW.is_breaking is False
    assert BlastRadiusSeverity.MINIMAL.is_breaking is False


def test_caller_chain_hop_model() -> None:
    """Verify CallerChainHop construction and fields."""
    hop = CallerChainHop(
        repo="consumer-service",
        file_path="src/client.py",
        symbol="fetch_deals",
        line_number=42,
        edge_type=DependencyEdgeType.CALL,
        depth=2,
    )
    assert hop.repo == "consumer-service"
    assert hop.file_path == "src/client.py"
    assert hop.symbol == "fetch_deals"
    assert hop.line_number == 42
    assert hop.edge_type == DependencyEdgeType.CALL
    assert hop.depth == 2


def test_caller_chain_model() -> None:
    """Verify CallerChain properties and cross_repo detection."""
    hop1 = CallerChainHop(
        repo="gateway",
        file_path="src/router.py",
        symbol="route_req",
        depth=1,
    )
    hop2 = CallerChainHop(
        repo="worker",
        file_path="src/task.py",
        symbol="process",
        depth=2,
    )
    chain = CallerChain(
        hops=[hop1, hop2],
        path_str="gateway:src/router.py:route_req -> worker:src/task.py:process",
        depth=2,
        cross_repo=True,
        repos_involved=["gateway", "worker"],
    )
    assert chain.depth == 2
    assert chain.cross_repo is True
    assert len(chain.repos_involved) == 2


def test_impacted_node_model() -> None:
    """Verify ImpactedNode properties."""
    node = ImpactedNode(
        repo="backend",
        file_path="src/handler.py",
        symbol="handle",
        depth=1,
        direct=True,
        caller_count=3,
    )
    assert node.direct is True
    assert node.depth == 1
    assert node.caller_count == 3


def test_simulation_request_validation() -> None:
    """Verify request bounds and defaults."""
    req = BlastRadiusSimulationRequest(repo="sentinel")
    assert req.repo == "sentinel"
    assert req.change_kind == "MODIFIED"
    assert req.max_depth == 5

    with pytest.raises(ValueError):
        BlastRadiusSimulationRequest(repo="sentinel", max_depth=0)


def test_simulation_report_and_markdown() -> None:
    """Verify simulation report counts population and markdown formatting."""
    adv = ImpactAdvisory(
        severity=BlastRadiusSeverity.HIGH,
        category="migration_order",
        message="Update callers before target",
        recommended_action="Stage leaf changes first",
    )
    node1 = ImpactedNode(
        repo="consumer-app",
        file_path="src/main.py",
        symbol="run",
        depth=1,
        direct=True,
    )
    node2 = ImpactedNode(
        repo="worker-app",
        file_path="src/job.py",
        symbol="exec",
        depth=2,
        direct=False,
    )

    report = BlastRadiusSimulationReport(
        target_repo="core-lib",
        target_symbol="execute_command",
        change_kind="REMOVED",
        max_depth=3,
        risk_score=78.5,
        risk_level=BlastRadiusSeverity.CRITICAL,
        impacted_nodes=[node1, node2],
        advisories=[adv],
        recommended_update_order=["[Hop 2] worker-app", "[Hop 1] consumer-app", "[Root] core-lib"],
        suggested_test_suites=["core-lib: tests/", "consumer-app: tests/"],
    )

    assert report.is_breaking is True
    assert report.total_impacted_repos == 2
    assert report.total_impacted_files == 2
    assert report.total_impacted_symbols == 2

    md = report.to_markdown_summary()
    assert "### Blast Radius Simulation: `core-lib` :: `execute_command`" in md
    assert "- **Risk Level:** `CRITICAL` (Score: 78.5/100.0)"
    assert "#### Planning Advisories" in md
    assert "#### Recommended Staging Sequence" in md
    assert "#### Required Test Suites" in md


def test_impact_trace_result() -> None:
    """Verify ImpactTraceResult container."""
    res = ImpactTraceResult(
        target_repo="auth-service",
        symbol="verify_token",
        total_chains=1,
        total_impacted_nodes=1,
    )
    assert res.target_repo == "auth-service"
    assert res.symbol == "verify_token"
    assert res.total_chains == 1
