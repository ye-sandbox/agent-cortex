"""Hermetic tests for cortex deps CLI commands."""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cortex.cli import app
from cortex.models.graph import (
    CodeDependency,
    CodeSignature,
    CrossRepoLink,
    DependencyEdgeType,
    DependencyQueryResult,
    DependentsQueryResult,
    SignaturesQueryResult,
)

runner = CliRunner()


def test_cli_deps_trace_json() -> None:
    dep = CodeDependency(
        id="cortex:src/lib.py:IMPORT:fastembed::5",
        source_repo="cortex",
        source_file="src/lib.py",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="fastembed",
        line_number=5,
    )
    link = CrossRepoLink(
        source_repo="cortex",
        source_file="src/lib.py",
        target_repo="clipflow",
        edge_type=DependencyEdgeType.CALL,
        symbol="feed",
    )
    result_dto = DependencyQueryResult(
        repo="cortex",
        file_path="src/lib.py",
        total_dependencies=1,
        dependencies=[dep],
        cross_repo_links=[link],
    )

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_dependencies.return_value = result_dto

        res = runner.invoke(app, ["deps", "trace", "--repo", "cortex", "--json"])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["repo"] == "cortex"
        assert len(data["dependencies"]) == 1
        assert len(data["cross_repo_links"]) == 1


def test_cli_deps_trace_table() -> None:
    dep = CodeDependency(
        id="cortex:src/lib.py:IMPORT:fastembed::5",
        source_repo="cortex",
        source_file="src/lib.py",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="fastembed",
        line_number=5,
    )
    result_dto = DependencyQueryResult(
        repo="cortex",
        total_dependencies=1,
        dependencies=[dep],
        cross_repo_links=[],
    )

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_dependencies.return_value = result_dto

        res = runner.invoke(app, ["deps", "trace", "--repo", "cortex"])
        assert res.exit_code == 0
        assert "Dependencies for 'cortex'" in res.output
        assert "fastembed" in res.output


def test_cli_deps_callers() -> None:
    dep = CodeDependency(
        id="maestri:src/app.ts:CALL:cortex:sync:10",
        source_repo="maestri",
        source_file="src/app.ts",
        source_symbol="start",
        edge_type=DependencyEdgeType.CALL,
        target_module="cortex",
        target_symbol="sync",
        line_number=10,
    )
    result_dto = DependentsQueryResult(
        symbol="sync",
        total_dependents=1,
        dependents=[dep],
        cross_repo_links=[],
    )

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_dependents.return_value = result_dto

        res = runner.invoke(app, ["deps", "callers", "--symbol", "sync"])
        assert res.exit_code == 0
        assert "Callers and Dependents for 'sync'" in res.output
        assert "maestri" in res.output


def test_cli_deps_signatures() -> None:
    sig = CodeSignature(
        id="cortex:src/cli.py:function:trace",
        repo="cortex",
        file_path="src/cli.py",
        language="python",
        kind="function",
        identifier="trace",
        signature="def trace() -> None",
        line_start=1,
        line_end=10,
    )
    result_dto = SignaturesQueryResult(
        query="trace",
        total_signatures=1,
        signatures=[sig],
    )

    with patch("cortex.cli.CortexClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_signatures.return_value = result_dto

        res = runner.invoke(app, ["deps", "signatures", "trace"])
        assert res.exit_code == 0
        assert "Code Signatures for 'trace'" in res.output
        assert "cortex" in res.output
