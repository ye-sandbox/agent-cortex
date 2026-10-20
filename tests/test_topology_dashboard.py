"""Tests for the standalone portfolio topology dashboard."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cortex.cli import app
from cortex.dashboard import render_dashboard
from cortex.models.topology import (
    DependencyCycle,
    PortfolioDependencyEdge,
    PortfolioRepoNode,
    PortfolioTopologyGraph,
)

runner = CliRunner()


def sample_graph() -> PortfolioTopologyGraph:
    """Build synthetic topology data with a cycle and hostile HTML characters."""
    return PortfolioTopologyGraph(
        nodes=[
            PortfolioRepoNode(repo="repo<alpha>", afferent_coupling=1, efferent_coupling=1),
            PortfolioRepoNode(repo="repo-beta", afferent_coupling=1, efferent_coupling=1),
        ],
        edges=[
            PortfolioDependencyEdge(
                source_repo="repo<alpha>",
                target_repo="repo-beta",
                symbols=["</script><img>"],
            ),
            PortfolioDependencyEdge(source_repo="repo-beta", target_repo="repo<alpha>"),
        ],
        cycles=[DependencyCycle(path=["repo<alpha>", "repo-beta", "repo<alpha>"], length=2)],
        total_repos=2,
        total_cross_repo_edges=2,
        total_cross_repo_references=2,
        density=1.0,
    )


def test_dashboard_is_self_contained_and_escapes_embedded_data() -> None:
    html = render_dashboard(sample_graph())

    assert "function cytoscape" in html or "cytoscape=" in html
    assert '<script id="cortex-data" type="application/json">' in html
    assert "repo\\u003calpha\\u003e" in html
    assert "\\u003c/script\\u003e\\u003cimg\\u003e" in html
    assert "</script><img>" not in html
    assert "https://cdn" not in html
    assert "<script src=" not in html


def test_dashboard_command_writes_synthetic_snapshot(tmp_path: Path) -> None:
    destination = tmp_path / "topology.html"
    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.get_portfolio_topology.return_value = sample_graph()

        result = runner.invoke(
            app, ["topology", "dashboard", "--output", str(destination), "--min-weight", "2"]
        )

    assert result.exit_code == 0, result.output
    assert destination.is_file()
    assert "repo\\u003calpha\\u003e" in destination.read_text(encoding="utf-8")
    mock_client.get_portfolio_topology.assert_called_once_with(
        format="json", include_internal=False, min_weight=2
    )


def test_dashboard_command_rejects_unexpected_payload(tmp_path: Path) -> None:
    destination = tmp_path / "topology.html"
    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.get_portfolio_topology.return_value = {}
        result = runner.invoke(app, ["topology", "dashboard", "--output", str(destination)])

    assert result.exit_code == 1
    assert "unexpected" in result.output and "graph format" in result.output
    assert not destination.exists()
