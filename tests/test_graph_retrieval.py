"""Unit tests for storage and cross-repo dependency graph retrieval."""

from pathlib import Path

from cortex.models.graph import (
    CodeDependency,
    CodeSignature,
    DependencyEdgeType,
)
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.storage.manager import StorageManager


def test_storage_signatures_crud(tmp_path: Path) -> None:
    storage = StorageManager(data_dir=tmp_path / "data")

    sig1 = CodeSignature(
        id="cortex:src/lib.py:function:helper",
        repo="cortex",
        file_path="src/lib.py",
        language="python",
        kind="function",
        identifier="helper",
        signature="def helper() -> int",
        docstring="Doc helper",
        line_start=1,
        line_end=10,
        exported=True,
    )
    sig2 = CodeSignature(
        id="cortex:src/lib.py:class:Worker",
        repo="cortex",
        file_path="src/lib.py",
        language="python",
        kind="class",
        identifier="Worker",
        signature="class Worker",
        line_start=12,
        line_end=30,
        exported=True,
    )

    count = storage.upsert_signatures([sig1, sig2])
    assert count == 2

    # Query signatures
    res = storage.get_signatures()
    assert len(res) == 2

    filtered = storage.get_signatures(where="kind = 'function'")
    assert len(filtered) == 1
    assert filtered[0].identifier == "helper"

    # Delete by file
    storage.delete_signatures_by_file("cortex", "src/lib.py")
    assert len(storage.get_signatures()) == 0


def test_storage_dependencies_crud(tmp_path: Path) -> None:
    storage = StorageManager(data_dir=tmp_path / "data")

    dep1 = CodeDependency(
        id="cortex:src/a.py:IMPORT:fastembed::5",
        source_repo="cortex",
        source_file="src/a.py",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="fastembed",
        target_symbol="",
        line_number=5,
    )
    dep2 = CodeDependency(
        id="cortex:src/a.py:CALL:clipflow:fetch_feed:15",
        source_repo="cortex",
        source_file="src/a.py",
        source_symbol="sync",
        edge_type=DependencyEdgeType.CALL,
        target_module="clipflow",
        target_symbol="fetch_feed",
        target_repo="clipflow",
        line_number=15,
    )

    count = storage.upsert_dependencies([dep1, dep2])
    assert count == 2

    deps = storage.get_dependencies()
    assert len(deps) == 2

    del_dep = storage.get_dependencies(where="target_module = 'fastembed'")
    assert len(del_dep) == 1

    storage.delete_dependencies_by_file("cortex", "src/a.py")
    assert len(storage.get_dependencies()) == 0


def test_dependency_graph_engine_queries(tmp_path: Path) -> None:
    storage = StorageManager(data_dir=tmp_path / "data")
    engine = DependencyGraphEngine(storage)

    # Insert test dependencies and signatures
    sig = CodeSignature(
        id="sentinel:specs/api.py:function:get_deals",
        repo="sentinel",
        file_path="specs/api.py",
        language="python",
        kind="function",
        identifier="get_deals",
        signature="def get_deals() -> list[str]",
        line_start=10,
        line_end=20,
    )
    storage.upsert_signatures([sig])

    dep_internal = CodeDependency(
        id="ia-maestri:src/worker.ts:IMPORT:./utils::2",
        source_repo="ia-maestri",
        source_file="src/worker.ts",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="./utils",
        line_number=2,
    )
    dep_cross = CodeDependency(
        id="ia-maestri:src/worker.ts:CALL:sentinel:get_deals:25",
        source_repo="ia-maestri",
        source_file="src/worker.ts",
        source_symbol="pollDeals",
        edge_type=DependencyEdgeType.CALL,
        target_module="sentinel.api",
        target_symbol="get_deals",
        line_number=25,
    )
    storage.upsert_dependencies([dep_internal, dep_cross])

    # 1. Outgoing dependencies for ia-maestri
    res = engine.get_dependencies(repo="ia-maestri")
    assert res.total_dependencies == 2
    assert len(res.cross_repo_links) == 1
    assert res.cross_repo_links[0].target_repo == "sentinel"

    # Cross repo only filter
    cross_res = engine.get_dependencies(repo="ia-maestri", cross_repo_only=True)
    assert cross_res.total_dependencies == 1
    assert cross_res.dependencies[0].target_symbol == "get_deals"

    # 2. Callers / dependents for get_deals
    callers = engine.get_dependents(symbol="get_deals")
    assert callers.total_dependents == 1
    assert callers.dependents[0].source_repo == "ia-maestri"
    assert callers.dependents[0].source_symbol == "pollDeals"

    # 3. Signatures query
    sig_res = engine.get_signatures(query="deals", repo="sentinel")
    assert sig_res.total_signatures == 1
    assert sig_res.signatures[0].identifier == "get_deals"
