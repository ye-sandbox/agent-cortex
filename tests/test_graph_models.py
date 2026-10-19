"""Unit tests for code signature and dependency graph domain models."""

import pytest
from pydantic import ValidationError

from cortex.models.graph import (
    CodeDependency,
    CodeSignature,
    CrossRepoLink,
    DependencyEdgeType,
    DependencyQueryResult,
    DependentsQueryResult,
    SignaturesQueryResult,
)


def test_code_signature_build_id_and_validation() -> None:
    sig_id = CodeSignature.build_id(
        repo="agent-cortex",
        file_path="src/cortex/cli.py",
        kind="function",
        identifier="deps_trace",
    )
    assert sig_id == "agent-cortex:src/cortex/cli.py:function:deps_trace"

    sig = CodeSignature(
        id=sig_id,
        repo="agent-cortex",
        file_path="src/cortex/cli.py",
        language="python",
        kind="function",
        identifier="deps_trace",
        signature="def deps_trace(...) -> None",
        docstring="Trace outgoing dependencies.",
        line_start=10,
        line_end=50,
        exported=True,
        calls=["load_config", "CortexClient"],
    )
    assert sig.identifier == "deps_trace"
    assert len(sig.calls) == 2


def test_code_signature_id_mismatch_raises() -> None:
    with pytest.raises(ValidationError, match="does not start with expected prefix"):
        CodeSignature(
            id="wrong-repo:src/cortex/cli.py:function:deps_trace",
            repo="agent-cortex",
            file_path="src/cortex/cli.py",
            language="python",
            kind="function",
            identifier="deps_trace",
            signature="def deps_trace(...) -> None",
            line_start=1,
            line_end=5,
        )


def test_code_dependency_build_id_and_validation() -> None:
    dep_id = CodeDependency.build_id(
        source_repo="ia-maestri",
        source_file="src/client.ts",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="agent-cortex",
        target_symbol="CortexClient",
        line_number=5,
    )
    assert dep_id == "ia-maestri:src/client.ts:IMPORT:agent-cortex:CortexClient:5"

    dep = CodeDependency(
        id=dep_id,
        source_repo="ia-maestri",
        source_file="src/client.ts",
        source_symbol="main",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="agent-cortex",
        target_symbol="CortexClient",
        target_repo="agent-cortex",
        line_number=5,
        raw_statement="import { CortexClient } from 'agent-cortex'",
    )
    assert dep.edge_type == DependencyEdgeType.IMPORT
    assert dep.target_repo == "agent-cortex"


def test_code_dependency_id_mismatch_raises() -> None:
    with pytest.raises(ValidationError, match="does not start with expected prefix"):
        CodeDependency(
            id="wrong-repo:src/client.ts:IMPORT:agent-cortex:CortexClient:5",
            source_repo="ia-maestri",
            source_file="src/client.ts",
            edge_type=DependencyEdgeType.IMPORT,
            target_module="agent-cortex",
        )


def test_query_result_dtos() -> None:
    link = CrossRepoLink(
        source_repo="ia-maestri",
        source_file="src/app.ts",
        target_repo="clipflow",
        edge_type=DependencyEdgeType.CALL,
        symbol="fetch_stream",
        detail="CALL clipflow::fetch_stream",
    )
    dep = CodeDependency(
        id="ia-maestri:src/app.ts:CALL:clipflow:fetch_stream:42",
        source_repo="ia-maestri",
        source_file="src/app.ts",
        source_symbol="init",
        edge_type=DependencyEdgeType.CALL,
        target_module="clipflow",
        target_symbol="fetch_stream",
        target_repo="clipflow",
        line_number=42,
    )

    query_res = DependencyQueryResult(
        repo="ia-maestri",
        file_path="src/app.ts",
        total_dependencies=1,
        dependencies=[dep],
        cross_repo_links=[link],
    )
    assert query_res.total_dependencies == 1
    assert len(query_res.cross_repo_links) == 1

    dependents_res = DependentsQueryResult(
        symbol="fetch_stream",
        total_dependents=1,
        dependents=[dep],
        cross_repo_links=[link],
    )
    assert dependents_res.symbol == "fetch_stream"

    sig = CodeSignature(
        id="ia-maestri:src/app.ts:function:init",
        repo="ia-maestri",
        file_path="src/app.ts",
        language="typescript",
        kind="function",
        identifier="init",
        signature="function init(): void",
        line_start=1,
        line_end=10,
    )
    sigs_res = SignaturesQueryResult(
        query="init",
        total_signatures=1,
        signatures=[sig],
    )
    assert sigs_res.total_signatures == 1
