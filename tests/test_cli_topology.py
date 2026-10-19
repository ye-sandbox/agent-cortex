"""Hermetic tests for cortex topology CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cortex.cli import app
from cortex.models.topology import (
    DependencyCycle,
    PortfolioDependencyMatrix,
    PortfolioMatrixRow,
)

runner = CliRunner()


def test_cli_topology_matrix_table() -> None:
    """Test cortex topology matrix rendering formatted Rich table and summary."""
    row_sentinel = PortfolioMatrixRow(
        source_repo="sentinel",
        targets={"sentinel": 0, "maestri": 2},
        afferent_coupling=1,
        efferent_coupling=1,
        instability=0.5,
    )
    row_maestri = PortfolioMatrixRow(
        source_repo="maestri",
        targets={"sentinel": 1, "maestri": 0},
        afferent_coupling=1,
        efferent_coupling=1,
        instability=0.5,
    )
    cycle = DependencyCycle(path=["sentinel", "maestri", "sentinel"], length=2)
    matrix = PortfolioDependencyMatrix(
        repos=["sentinel", "maestri"],
        rows=[row_sentinel, row_maestri],
        cycles=[cycle],
        summary={
            "total_repositories": 2,
            "total_cross_repo_edges": 2,
            "total_cross_repo_references": 3,
            "density": 1.0,
            "most_depended_repository": "sentinel",
            "most_dependent_repository": "maestri",
        },
    )

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_dependency_matrix.return_value = matrix

        res = runner.invoke(app, ["topology", "matrix"])
        assert res.exit_code == 0
        assert "Cross-Repository Dependency Matrix" in res.output
        assert "sentinel" in res.output
        assert "maestri" in res.output
        assert "Circular Dependencies Detected" in res.output


def test_cli_topology_matrix_json() -> None:
    """Test cortex topology matrix machine-readable JSON output."""
    matrix = PortfolioDependencyMatrix(
        repos=["repoA"],
        rows=[PortfolioMatrixRow(source_repo="repoA", targets={"repoA": 0})],
        cycles=[],
        summary={"total_repositories": 1},
    )

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_dependency_matrix.return_value = matrix

        res = runner.invoke(app, ["topology", "matrix", "--json"])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["repos"] == ["repoA"]
        assert len(data["rows"]) == 1


def test_cli_topology_graph_stdout_and_file(tmp_path: Path) -> None:
    """Test cortex topology graph export to stdout and file."""
    mermaid_str = "flowchart LR\n    repoA --> repoB"

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_portfolio_topology.return_value = mermaid_str

        # 1. Stdout
        res_stdout = runner.invoke(app, ["topology", "graph", "--format", "mermaid"])
        assert res_stdout.exit_code == 0
        assert "flowchart LR" in res_stdout.output

        # 2. File export
        out_file = tmp_path / "graph.mmd"
        res_file = runner.invoke(
            app, ["topology", "graph", "--format", "mermaid", "--output", str(out_file)]
        )
        assert res_file.exit_code == 0
        assert out_file.is_file()
        assert "flowchart LR" in out_file.read_text(encoding="utf-8")


def test_cli_topology_graph_cytoscape_json() -> None:
    """Test cortex topology graph with Cytoscape JSON output."""
    cyto_dict = {
        "elements": {
            "nodes": [{"data": {"id": "repoA"}}],
            "edges": [],
        }
    }

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_portfolio_topology.return_value = cyto_dict

        res = runner.invoke(app, ["topology", "graph", "--format", "cytoscape"])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert "elements" in data
        assert len(data["elements"]["nodes"]) == 1


def test_cli_topology_cycles_clean() -> None:
    """Test cortex topology cycles command when zero cycles exist."""
    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_topology_cycles.return_value = []

        res = runner.invoke(app, ["topology", "cycles", "--fail-on-cycles"])
        assert res.exit_code == 0
        assert "Zero circular dependencies detected" in res.output


def test_cli_topology_cycles_detected_fail_gate() -> None:
    """Test cortex topology cycles CI/CD failure gate (--fail-on-cycles)."""
    cycles = [DependencyCycle(path=["repoA", "repoB", "repoA"], length=2)]

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_topology_cycles.return_value = cycles

        # Without fail flag -> exit 0
        res_ok = runner.invoke(app, ["topology", "cycles"])
        assert res_ok.exit_code == 0
        assert "repoA -> repoB -> repoA" in res_ok.output

        # With fail flag -> exit 1
        res_fail = runner.invoke(app, ["topology", "cycles", "--fail-on-cycles"])
        assert res_fail.exit_code == 1

        # JSON with fail flag -> exit 1
        res_json = runner.invoke(app, ["topology", "cycles", "--fail-on-cycles", "--json"])
        assert res_json.exit_code == 1
