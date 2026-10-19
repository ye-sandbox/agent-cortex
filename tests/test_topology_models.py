"""Unit tests for portfolio topology and dependency matrix domain models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cortex.models.graph import CrossRepoLink, DependencyEdgeType
from cortex.models.topology import (
    DependencyCycle,
    PortfolioDependencyEdge,
    PortfolioDependencyMatrix,
    PortfolioMatrixRow,
    PortfolioRepoNode,
    PortfolioTopologyGraph,
    TopologyExportFormat,
)


def test_portfolio_repo_node_defaults() -> None:
    """Validate PortfolioRepoNode fields and metric calculations."""
    node = PortfolioRepoNode(
        repo="sentinel-deals-backend",
        languages=["python"],
        technologies=["fastapi", "lancedb"],
        total_signatures=42,
        total_contracts=10,
        afferent_coupling=4,
        efferent_coupling=1,
        instability=0.20,
        is_leaf=False,
        is_root=False,
    )
    assert node.repo == "sentinel-deals-backend"
    assert node.languages == ["python"]
    assert node.technologies == ["fastapi", "lancedb"]
    assert node.afferent_coupling == 4
    assert node.efferent_coupling == 1
    assert node.instability == 0.20
    assert not node.is_leaf
    assert not node.is_root


def test_portfolio_repo_node_leaf_and_root() -> None:
    """Verify leaf and root node flags."""
    root = PortfolioRepoNode(
        repo="core-lib",
        afferent_coupling=5,
        efferent_coupling=0,
        instability=0.0,
        is_leaf=True,
        is_root=False,
    )
    assert root.is_leaf
    assert root.instability == 0.0

    leaf = PortfolioRepoNode(
        repo="consumer-app",
        afferent_coupling=0,
        efferent_coupling=3,
        instability=1.0,
        is_leaf=False,
        is_root=True,
    )
    assert leaf.is_root
    assert leaf.instability == 1.0


def test_portfolio_dependency_edge() -> None:
    """Validate PortfolioDependencyEdge creation and properties."""
    bridge = CrossRepoLink(
        source_repo="ia-maestri",
        source_file="src/client.ts",
        target_repo="sentinel-deals-backend",
        edge_type=DependencyEdgeType.CALL,
        symbol="get_deals",
        detail="CALL get_deals",
    )
    edge = PortfolioDependencyEdge(
        source_repo="ia-maestri",
        target_repo="sentinel-deals-backend",
        weight=5,
        edge_types={"CALL": 3, "IMPORT": 2},
        symbols=["get_deals", "DealsClient"],
        bridges=[bridge],
    )
    assert edge.source_repo == "ia-maestri"
    assert edge.target_repo == "sentinel-deals-backend"
    assert edge.weight == 5
    assert edge.edge_types["CALL"] == 3
    assert len(edge.bridges) == 1


def test_dependency_cycle_validation() -> None:
    """Test validation of circular dependency model."""
    cycle = DependencyCycle(path=["repoA", "repoB", "repoA"], length=2)
    assert cycle.path == ["repoA", "repoB", "repoA"]
    assert cycle.length == 2

    # Length must be >= 2
    with pytest.raises(ValidationError):
        DependencyCycle(path=["repoA"], length=1)


def test_portfolio_topology_graph_serialization() -> None:
    """Validate serialization and round-trip parsing of topology graph."""
    node_a = PortfolioRepoNode(repo="repoA", afferent_coupling=1, efferent_coupling=0)
    node_b = PortfolioRepoNode(repo="repoB", afferent_coupling=0, efferent_coupling=1)
    edge = PortfolioDependencyEdge(source_repo="repoB", target_repo="repoA", weight=3)

    graph = PortfolioTopologyGraph(
        nodes=[node_a, node_b],
        edges=[edge],
        cycles=[],
        total_repos=2,
        total_cross_repo_edges=1,
        total_cross_repo_references=3,
        density=0.5,
    )

    dumped = graph.model_dump(mode="json")
    reconstructed = PortfolioTopologyGraph.model_validate(dumped)
    assert reconstructed.total_repos == 2
    assert reconstructed.density == 0.5
    assert len(reconstructed.edges) == 1
    assert reconstructed.edges[0].source_repo == "repoB"


def test_portfolio_dependency_matrix_models() -> None:
    """Test matrix rows and summary structures."""
    row = PortfolioMatrixRow(
        source_repo="repoB",
        targets={"repoA": 3, "repoB": 0},
        afferent_coupling=0,
        efferent_coupling=1,
        instability=1.0,
    )
    matrix = PortfolioDependencyMatrix(
        repos=["repoA", "repoB"],
        rows=[row],
        cycles=[],
        summary={"total_repositories": 2, "total_cross_repo_edges": 1},
    )
    assert len(matrix.repos) == 2
    assert matrix.rows[0].targets["repoA"] == 3
    assert matrix.summary["total_cross_repo_edges"] == 1


def test_topology_export_format_enum() -> None:
    """Ensure all expected serialization formats are supported."""
    assert TopologyExportFormat.MERMAID == "mermaid"
    assert TopologyExportFormat.DOT == "dot"
    assert TopologyExportFormat.CYTOSCAPE == "cytoscape"
    assert TopologyExportFormat.JSON == "json"
