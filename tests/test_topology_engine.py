"""Unit and integration tests for PortfolioTopologyEngine."""

from __future__ import annotations

from pathlib import Path

from cortex.models.graph import CodeDependency, CodeSignature, DependencyEdgeType
from cortex.models.topology import (
    PortfolioDependencyEdge,
    PortfolioTopologyGraph,
    TopologyExportFormat,
)
from cortex.retrieval.topology import PortfolioTopologyEngine
from cortex.storage.manager import StorageManager


def test_topology_engine_empty(tmp_path: Path) -> None:
    """Test engine behavior when no repos or dependencies are indexed."""
    storage = StorageManager(data_dir=tmp_path / "data")
    engine = PortfolioTopologyEngine(storage)

    graph = engine.build_topology()
    assert graph.total_repos == 0
    assert graph.total_cross_repo_edges == 0
    assert len(graph.nodes) == 0
    assert len(graph.edges) == 0
    assert len(graph.cycles) == 0

    matrix = engine.build_matrix()
    assert len(matrix.repos) == 0
    assert len(matrix.rows) == 0


def test_topology_engine_coupling_and_metrics(tmp_path: Path) -> None:
    """Verify coupling metrics (Ca, Ce, instability) and bridges across repositories."""
    storage = StorageManager(data_dir=tmp_path / "data")

    # Add signatures for language detection
    sig_sentinel = CodeSignature(
        id=CodeSignature.build_id("sentinel-deals-backend", "src/api.py", "function", "get_deals"),
        repo="sentinel-deals-backend",
        file_path="src/api.py",
        language="python",
        kind="function",
        identifier="get_deals",
        signature="def get_deals() -> list",
        line_start=1,
        line_end=10,
        exported=True,
    )
    sig_maestri = CodeSignature(
        id=CodeSignature.build_id("ia-maestri", "src/client.ts", "function", "query"),
        repo="ia-maestri",
        file_path="src/client.ts",
        language="typescript",
        kind="function",
        identifier="query",
        signature="export function query(): void",
        line_start=1,
        line_end=15,
        exported=True,
    )
    sig_auth = CodeSignature(
        id=CodeSignature.build_id("core-auth", "main.go", "function", "Verify"),
        repo="core-auth",
        file_path="main.go",
        language="go",
        kind="function",
        identifier="Verify",
        signature="func Verify() bool",
        line_start=1,
        line_end=12,
        exported=True,
    )
    storage.upsert_signatures([sig_sentinel, sig_maestri, sig_auth])

    # Add cross-repository dependencies
    # ia-maestri -> sentinel-deals-backend
    dep1 = CodeDependency(
        id=CodeDependency.build_id(
            "ia-maestri",
            "src/client.ts",
            DependencyEdgeType.CALL,
            "sentinel-deals-backend.api",
            "get_deals",
            10,
        ),
        source_repo="ia-maestri",
        source_file="src/client.ts",
        edge_type=DependencyEdgeType.CALL,
        target_module="sentinel-deals-backend.api",
        target_symbol="get_deals",
        target_repo="sentinel-deals-backend",
        line_number=10,
    )
    dep2 = CodeDependency(
        id=CodeDependency.build_id(
            "ia-maestri",
            "src/client.ts",
            DependencyEdgeType.IMPORT,
            "sentinel-deals-backend",
            "DealsClient",
            5,
        ),
        source_repo="ia-maestri",
        source_file="src/client.ts",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="sentinel-deals-backend",
        target_symbol="DealsClient",
        target_repo="sentinel-deals-backend",
        line_number=5,
    )
    # sentinel-deals-backend -> core-auth
    dep3 = CodeDependency(
        id=CodeDependency.build_id(
            "sentinel-deals-backend",
            "src/api.py",
            DependencyEdgeType.IMPORT,
            "core-auth",
            "Verify",
            3,
        ),
        source_repo="sentinel-deals-backend",
        source_file="src/api.py",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="core-auth",
        target_symbol="Verify",
        target_repo="core-auth",
        line_number=3,
    )
    # intra-repo dependency (should be excluded by default from cross-repo edges)
    dep_intra = CodeDependency(
        id=CodeDependency.build_id(
            "sentinel-deals-backend",
            "src/api.py",
            DependencyEdgeType.CALL,
            "internal",
            "helper",
            20,
        ),
        source_repo="sentinel-deals-backend",
        source_file="src/api.py",
        edge_type=DependencyEdgeType.CALL,
        target_module="internal",
        target_symbol="helper",
        target_repo="sentinel-deals-backend",
        line_number=20,
    )
    storage.upsert_dependencies([dep1, dep2, dep3, dep_intra])

    engine = PortfolioTopologyEngine(storage)
    graph = engine.build_topology(include_internal=False)

    assert graph.total_repos == 3
    assert graph.total_cross_repo_edges == 2
    assert graph.total_cross_repo_references == 3

    node_map = {n.repo: n for n in graph.nodes}
    assert "ia-maestri" in node_map
    assert "sentinel-deals-backend" in node_map
    assert "core-auth" in node_map

    # ia-maestri depends on sentinel (Ce=1), nobody depends on ia-maestri (Ca=0) -> I = 1.0
    maestri_node = node_map["ia-maestri"]
    assert maestri_node.afferent_coupling == 0
    assert maestri_node.efferent_coupling == 1
    assert maestri_node.instability == 1.0
    assert maestri_node.is_root
    assert not maestri_node.is_leaf
    assert "typescript" in maestri_node.languages

    # sentinel-deals-backend has 1 incoming (ia-maestri) and 1 outgoing (core-auth) -> I = 0.5
    sentinel_node = node_map["sentinel-deals-backend"]
    assert sentinel_node.afferent_coupling == 1
    assert sentinel_node.efferent_coupling == 1
    assert sentinel_node.instability == 0.5
    assert not sentinel_node.is_root
    assert not sentinel_node.is_leaf
    assert "python" in sentinel_node.languages

    # core-auth has 1 incoming (sentinel), 0 outgoing -> I = 0.0 (foundational hub / leaf)
    auth_node = node_map["core-auth"]
    assert auth_node.afferent_coupling == 1
    assert auth_node.efferent_coupling == 0
    assert auth_node.instability == 0.0
    assert not auth_node.is_root
    assert auth_node.is_leaf
    assert "go" in auth_node.languages

    # Check edges
    edge_map = {(e.source_repo, e.target_repo): e for e in graph.edges}
    assert ("ia-maestri", "sentinel-deals-backend") in edge_map
    edge_ms = edge_map[("ia-maestri", "sentinel-deals-backend")]
    assert edge_ms.weight == 2
    assert edge_ms.edge_types.get("CALL") == 1
    assert edge_ms.edge_types.get("IMPORT") == 1

    assert ("sentinel-deals-backend", "core-auth") in edge_map
    edge_sc = edge_map[("sentinel-deals-backend", "core-auth")]
    assert edge_sc.weight == 1

    # Zero cycles initially
    assert len(graph.cycles) == 0


def test_topology_engine_cycle_detection(tmp_path: Path) -> None:
    """Detect circular dependency cycles in directed portfolio graphs."""
    storage = StorageManager(data_dir=tmp_path / "data")
    engine = PortfolioTopologyEngine(storage)

    # Synthetic edges: A -> B -> C -> A
    edges = [
        PortfolioDependencyEdge(source_repo="repoA", target_repo="repoB", weight=1),
        PortfolioDependencyEdge(source_repo="repoB", target_repo="repoC", weight=2),
        PortfolioDependencyEdge(source_repo="repoC", target_repo="repoA", weight=1),
        PortfolioDependencyEdge(source_repo="repoC", target_repo="repoD", weight=4),
    ]

    cycles = engine.detect_cycles(edges)
    assert len(cycles) == 1
    cycle = cycles[0]
    assert cycle.length == 3
    assert cycle.path == ["repoA", "repoB", "repoC", "repoA"]


def test_topology_engine_two_node_cycle(tmp_path: Path) -> None:
    """Detect direct mutual recursion/coupling: A <-> B."""
    storage = StorageManager(data_dir=tmp_path / "data")
    engine = PortfolioTopologyEngine(storage)

    edges = [
        PortfolioDependencyEdge(source_repo="repoX", target_repo="repoY", weight=3),
        PortfolioDependencyEdge(source_repo="repoY", target_repo="repoX", weight=2),
    ]

    cycles = engine.detect_cycles(edges)
    assert len(cycles) == 1
    assert cycles[0].length == 2
    assert cycles[0].path == ["repoX", "repoY", "repoX"]


def test_topology_engine_matrix_generation(tmp_path: Path) -> None:
    """Verify build_matrix synthesis and summary statistics."""
    storage = StorageManager(data_dir=tmp_path / "data")

    # Insert two repos with directed connection
    dep = CodeDependency(
        id=CodeDependency.build_id(
            "frontend-app",
            "src/main.py",
            DependencyEdgeType.IMPORT,
            "backend-service",
            "run",
            1,
        ),
        source_repo="frontend-app",
        source_file="src/main.py",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="backend-service",
        target_symbol="run",
        target_repo="backend-service",
        line_number=1,
    )
    storage.upsert_dependencies([dep])

    engine = PortfolioTopologyEngine(storage)
    matrix = engine.build_matrix()

    assert matrix.repos == ["backend-service", "frontend-app"]
    assert len(matrix.rows) == 2

    row_front = next(r for r in matrix.rows if r.source_repo == "frontend-app")
    assert row_front.targets["backend-service"] == 1
    assert row_front.targets["frontend-app"] == 0
    assert row_front.efferent_coupling == 1
    assert row_front.afferent_coupling == 0

    row_back = next(r for r in matrix.rows if r.source_repo == "backend-service")
    assert row_back.targets["frontend-app"] == 0
    assert row_back.afferent_coupling == 1
    assert row_back.efferent_coupling == 0

    assert matrix.summary["total_repositories"] == 2
    assert matrix.summary["total_cross_repo_edges"] == 1
    assert matrix.summary["most_depended_repository"] == "backend-service"
    assert matrix.summary["most_dependent_repository"] == "frontend-app"


def test_topology_engine_exporters(tmp_path: Path) -> None:
    """Validate Mermaid, DOT, Cytoscape, and JSON exports."""
    storage = StorageManager(data_dir=tmp_path / "data")

    dep = CodeDependency(
        id=CodeDependency.build_id(
            "web-client",
            "src/api.ts",
            DependencyEdgeType.CALL,
            "api-server",
            "get_data",
            5,
        ),
        source_repo="web-client",
        source_file="src/api.ts",
        edge_type=DependencyEdgeType.CALL,
        target_module="api-server",
        target_symbol="get_data",
        target_repo="api-server",
        line_number=5,
    )
    storage.upsert_dependencies([dep])

    engine = PortfolioTopologyEngine(storage)

    # 1. Mermaid
    mermaid = engine.export(TopologyExportFormat.MERMAID, direction="TD")
    assert isinstance(mermaid, str)
    assert mermaid.startswith("flowchart TD")
    assert "web_client" in mermaid
    assert "api_server" in mermaid
    assert "-->" in mermaid

    # 2. DOT
    dot = engine.export(TopologyExportFormat.DOT)
    assert isinstance(dot, str)
    assert "digraph PortfolioTopology {" in dot
    assert '"web-client" -> "api-server"' in dot

    # 3. Cytoscape
    cyto = engine.export(TopologyExportFormat.CYTOSCAPE)
    assert isinstance(cyto, dict)
    assert "elements" in cyto
    assert "nodes" in cyto["elements"]
    assert "edges" in cyto["elements"]
    assert len(cyto["elements"]["nodes"]) == 2
    assert len(cyto["elements"]["edges"]) == 1
    edge_data = cyto["elements"]["edges"][0]["data"]
    assert edge_data["source"] == "web-client"
    assert edge_data["target"] == "api-server"

    # 4. JSON
    json_export = engine.export(TopologyExportFormat.JSON)
    assert isinstance(json_export, dict)
    graph = PortfolioTopologyGraph.model_validate(json_export)
    assert graph.total_repos == 2
