"""Unit tests for ImpactAnalysisEngine (transitive caller tracing and blast-radius simulation)."""

from __future__ import annotations

from unittest.mock import MagicMock

from cortex.models.graph import CodeDependency, DependencyEdgeType
from cortex.models.impact import (
    BlastRadiusSeverity,
    BlastRadiusSimulationRequest,
)
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.retrieval.impact import ImpactAnalysisEngine
from cortex.retrieval.topology import PortfolioTopologyEngine
from cortex.storage.manager import StorageManager


def _build_mock_storage_with_graph() -> MagicMock:
    """Construct mock StorageManager containing multi-hop cross-repo dependency chains."""
    mock_storage = MagicMock(spec=StorageManager)

    # Chain: repoD -> repoC -> repoB -> repoA
    # repoB:service.py:call_b calls repoA:core.py:target_func
    dep1 = CodeDependency(
        id=CodeDependency.build_id(
            "repoB", "src/service.py", DependencyEdgeType.CALL, "repoA", "target_func", 10
        ),
        source_repo="repoB",
        source_file="src/service.py",
        source_symbol="call_b",
        edge_type=DependencyEdgeType.CALL,
        target_module="repoA",
        target_symbol="target_func",
        target_repo="repoA",
        line_number=10,
    )
    # repoC:handler.py:call_c calls repoB:service.py:call_b
    dep2 = CodeDependency(
        id=CodeDependency.build_id(
            "repoC", "src/handler.py", DependencyEdgeType.CALL, "repoB", "call_b", 20
        ),
        source_repo="repoC",
        source_file="src/handler.py",
        source_symbol="call_c",
        edge_type=DependencyEdgeType.CALL,
        target_module="repoB",
        target_symbol="call_b",
        target_repo="repoB",
        line_number=20,
    )
    # repoD:worker.py:call_d calls repoC:handler.py:call_c
    dep3 = CodeDependency(
        id=CodeDependency.build_id(
            "repoD", "src/worker.py", DependencyEdgeType.CALL, "repoC", "call_c", 30
        ),
        source_repo="repoD",
        source_file="src/worker.py",
        source_symbol="call_d",
        edge_type=DependencyEdgeType.CALL,
        target_module="repoC",
        target_symbol="call_c",
        target_repo="repoC",
        line_number=30,
    )

    # Cycle: cycleA:fA calls cycleB:fB, and cycleB:fB calls cycleA:fA
    cycle1 = CodeDependency(
        id=CodeDependency.build_id(
            "cycleB", "src/b.py", DependencyEdgeType.CALL, "cycleA", "funcA", 5
        ),
        source_repo="cycleB",
        source_file="src/b.py",
        source_symbol="funcB",
        edge_type=DependencyEdgeType.CALL,
        target_module="cycleA",
        target_symbol="funcA",
        target_repo="cycleA",
        line_number=5,
    )
    cycle2 = CodeDependency(
        id=CodeDependency.build_id(
            "cycleA", "src/a.py", DependencyEdgeType.CALL, "cycleB", "funcB", 15
        ),
        source_repo="cycleA",
        source_file="src/a.py",
        source_symbol="funcA",
        edge_type=DependencyEdgeType.CALL,
        target_module="cycleB",
        target_symbol="funcB",
        target_repo="cycleB",
        line_number=15,
    )

    all_deps = [dep1, dep2, dep3, cycle1, cycle2]
    mock_storage.get_dependencies.return_value = all_deps
    mock_storage.table_names.return_value = ["code_dependencies", "code_signatures", "chunks"]
    mock_storage.get_signatures.return_value = []
    mock_storage.get_technologies.return_value = []
    mock_storage.get_indexed_repos.return_value = [
        "repoA",
        "repoB",
        "repoC",
        "repoD",
        "cycleA",
        "cycleB",
    ]
    return mock_storage


def test_trace_transitive_callers_multi_hop() -> None:
    """Verify transitive multi-hop caller traversal across repository boundaries."""
    storage = _build_mock_storage_with_graph()
    graph_engine = DependencyGraphEngine(storage)
    topology_engine = PortfolioTopologyEngine(storage, graph_engine=graph_engine)
    engine = ImpactAnalysisEngine(
        storage, graph_engine=graph_engine, topology_engine=topology_engine
    )

    # Query target in repoA with depth 1
    chains_d1, nodes_d1, cycles_d1 = engine.trace_transitive_callers(
        target_repo="repoA",
        symbol="target_func",
        max_depth=1,
    )
    assert len(chains_d1) == 1
    assert chains_d1[0].hops[0].repo == "repoB"
    assert chains_d1[0].depth == 1
    assert len(nodes_d1) == 1
    assert nodes_d1[0].repo == "repoB"
    assert nodes_d1[0].direct is True

    # Query target in repoA with depth 3 (should traverse repoB -> repoC -> repoD)
    chains_d3, nodes_d3, cycles_d3 = engine.trace_transitive_callers(
        target_repo="repoA",
        symbol="target_func",
        max_depth=3,
    )
    assert len(chains_d3) == 3
    # Check that deepest chain has 3 hops
    deepest = max(chains_d3, key=lambda c: c.depth)
    assert deepest.depth == 3
    assert [h.repo for h in deepest.hops] == ["repoB", "repoC", "repoD"]

    # Verify nodes
    node_repos = {n.repo for n in nodes_d3}
    assert node_repos == {"repoB", "repoC", "repoD"}
    direct_nodes = [n for n in nodes_d3 if n.direct]
    assert len(direct_nodes) == 1
    assert direct_nodes[0].repo == "repoB"


def test_trace_transitive_callers_cycle_detection() -> None:
    """Verify detection of circular caller loops during traversal."""
    storage = _build_mock_storage_with_graph()
    engine = ImpactAnalysisEngine(storage)

    chains, nodes, cycles = engine.trace_transitive_callers(
        target_repo="cycleA",
        symbol="funcA",
        max_depth=5,
    )
    # Traversal starts at cycleB calling cycleA:funcA, then cycleA calling cycleB:funcB
    # and detects circular loop!
    assert len(cycles) > 0
    # Traversal terminates cleanly without infinite loop
    assert len(chains) >= 1


def test_calculate_risk_score_and_severity() -> None:
    """Verify risk calculation logic across change kinds and cross-repo distribution."""
    storage = _build_mock_storage_with_graph()
    engine = ImpactAnalysisEngine(storage)

    # Simulating REMOVED with cross-repo callers should be CRITICAL
    chains, nodes, cycles = engine.trace_transitive_callers("repoA", "target_func", max_depth=3)
    score_removed, sev_removed = engine.calculate_risk_score(
        target_repo="repoA",
        change_kind="REMOVED",
        impacted_nodes=nodes,
        cycles_detected=cycles,
        afferent_coupling=3,
    )
    assert score_removed >= 50.0
    assert sev_removed == BlastRadiusSeverity.CRITICAL

    # Simulating ADDED should be much lower risk
    score_added, sev_added = engine.calculate_risk_score(
        target_repo="repoA",
        change_kind="ADDED",
        impacted_nodes=nodes,
        cycles_detected=cycles,
        afferent_coupling=3,
    )
    assert score_added < score_removed
    assert sev_added in (
        BlastRadiusSeverity.LOW,
        BlastRadiusSeverity.MINIMAL,
        BlastRadiusSeverity.MEDIUM,
    )


def test_simulate_blast_radius_full_report() -> None:
    """Verify complete blast-radius simulation report generation."""
    storage = _build_mock_storage_with_graph()
    engine = ImpactAnalysisEngine(storage)

    req = BlastRadiusSimulationRequest(
        repo="repoA",
        symbol="target_func",
        change_kind="MODIFIED",
        max_depth=3,
    )
    report = engine.simulate_blast_radius(req)

    assert report.target_repo == "repoA"
    assert report.target_symbol == "target_func"
    assert report.change_kind == "MODIFIED"
    assert report.total_impacted_repos >= 3
    assert "repoB" in report.impacted_repos
    assert "repoC" in report.impacted_repos
    assert "repoD" in report.impacted_repos
    assert len(report.advisories) >= 2
    assert len(report.recommended_update_order) >= 4
    assert any("[Root Target]" in step for step in report.recommended_update_order)
    assert len(report.suggested_test_suites) >= 4
