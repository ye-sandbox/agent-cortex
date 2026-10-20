"""Unit tests for ChangeIntentEngine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from cortex.models.graph import CodeDependency, DependencyEdgeType
from cortex.models.impact import BlastRadiusSeverity
from cortex.models.intent import (
    ChangeIntentAction,
    ContractChangeIntent,
)
from cortex.retrieval.intent import ChangeIntentEngine
from cortex.storage.manager import StorageManager


def _build_test_storage() -> MagicMock:
    """Construct mock StorageManager with cross-repository call sites and imports."""
    mock_storage = MagicMock(spec=StorageManager)

    dep1 = CodeDependency(
        id=CodeDependency.build_id(
            "frontend-app",
            "src/auth.ts",
            DependencyEdgeType.IMPORT,
            "auth-service",
            "verify_token",
            5,
        ),
        source_repo="frontend-app",
        source_file="src/auth.ts",
        source_symbol="loginUser",
        edge_type=DependencyEdgeType.IMPORT,
        target_module="auth-service",
        target_symbol="verify_token",
        target_repo="auth-service",
        line_number=5,
        raw_statement="import { verify_token } from '@portfolio/auth-service';",
    )
    dep2 = CodeDependency(
        id=CodeDependency.build_id(
            "frontend-app",
            "src/auth.ts",
            DependencyEdgeType.CALL,
            "auth-service",
            "verify_token",
            24,
        ),
        source_repo="frontend-app",
        source_file="src/auth.ts",
        source_symbol="loginUser",
        edge_type=DependencyEdgeType.CALL,
        target_module="auth-service",
        target_symbol="verify_token",
        target_repo="auth-service",
        line_number=24,
        raw_statement="const isValid = verify_token(rawToken);",
    )
    dep3 = CodeDependency(
        id=CodeDependency.build_id(
            "worker-backend",
            "worker/tasks.py",
            DependencyEdgeType.CALL,
            "auth-service",
            "verify_token",
            42,
        ),
        source_repo="worker-backend",
        source_file="worker/tasks.py",
        source_symbol="execute_task",
        edge_type=DependencyEdgeType.CALL,
        target_module="auth-service",
        target_symbol="verify_token",
        target_repo="auth-service",
        line_number=42,
        raw_statement="auth.verify_token(token, timeout=30)",
    )

    mock_storage.get_dependencies.return_value = [dep1, dep2, dep3]
    mock_storage.table_names.return_value = ["code_dependencies", "code_signatures", "chunks"]
    mock_storage.get_signatures.return_value = []
    mock_storage.get_indexed_repos.return_value = ["auth-service", "frontend-app", "worker-backend"]
    return mock_storage


def test_find_downstream_call_sites() -> None:
    """Test locating call sites for an intended contract change."""
    storage = _build_test_storage()
    engine = ChangeIntentEngine(storage_manager=storage)

    intent = ContractChangeIntent(
        repo="auth-service",
        target_symbol="verify_token",
        action=ChangeIntentAction.RENAME_SYMBOL,
        new_symbol="validate_token",
    )

    sites = engine.find_downstream_call_sites(intent)
    assert len(sites) == 3
    repos = {s.repo for s in sites}
    assert repos == {"frontend-app", "worker-backend"}
    files = {s.file_path for s in sites}
    assert files == {"src/auth.ts", "worker/tasks.py"}


def test_detect_simulation_violations_removal_and_unmapped() -> None:
    """Test detecting breaking removals and unmapped symbols."""
    storage = _build_test_storage()
    engine = ChangeIntentEngine(storage_manager=storage)

    # 1. Removal violation
    intent_remove = ContractChangeIntent(
        repo="auth-service",
        target_symbol="verify_token",
        action=ChangeIntentAction.REMOVE_CONTRACT,
    )
    sites = engine.find_downstream_call_sites(intent_remove)
    violations = engine.detect_simulation_violations(intent_remove, sites)

    assert len(violations) >= 1
    assert violations[0].severity == BlastRadiusSeverity.CRITICAL
    assert violations[0].category == "breaking_removal"

    # 2. Rename without new_symbol
    intent_unmapped = ContractChangeIntent(
        repo="auth-service",
        target_symbol="verify_token",
        action=ChangeIntentAction.RENAME_SYMBOL,
        new_symbol="",
    )
    violations_unmapped = engine.detect_simulation_violations(intent_unmapped, sites)
    assert any(v.category == "unmapped_symbol" for v in violations_unmapped)


def test_synthesize_replacement_line() -> None:
    """Test replacing lines for symbol renames, endpoints, and parameters."""
    storage = _build_test_storage()
    engine = ChangeIntentEngine(storage_manager=storage)

    # Symbol rename
    intent_rename = ContractChangeIntent(
        repo="auth-service",
        target_symbol="verify_token",
        action=ChangeIntentAction.RENAME_SYMBOL,
        new_symbol="validate_token",
    )
    line1 = "import { verify_token } from '@portfolio/auth-service';"
    assert (
        engine.synthesize_replacement_line(line1, intent_rename)
        == "import { validate_token } from '@portfolio/auth-service';"
    )

    # Endpoint modification
    intent_endpoint = ContractChangeIntent(
        repo="sentinel",
        target_symbol="/api/v1/deals",
        action=ChangeIntentAction.CHANGE_ENDPOINT,
        new_symbol="/api/v2/deals",
    )
    line2 = 'const URL = "/api/v1/deals";'
    assert (
        engine.synthesize_replacement_line(line2, intent_endpoint) == 'const URL = "/api/v2/deals";'
    )

    # Parameter renames
    intent_sig = ContractChangeIntent(
        repo="worker",
        target_symbol="run_task",
        action=ChangeIntentAction.MODIFY_SIGNATURE,
        param_renames={"timeout": "timeout_seconds"},
    )
    line3 = "run_task(task_id, timeout=30)"
    assert (
        engine.synthesize_replacement_line(line3, intent_sig)
        == "run_task(task_id, timeout_seconds=30)"
    )


def test_generate_migration_patches_synthetic_and_disk(tmp_path: Path) -> None:
    """Test patch synthesis without disk files and with mounted local workspace files."""
    storage = _build_test_storage()
    engine = ChangeIntentEngine(storage_manager=storage)

    intent = ContractChangeIntent(
        repo="auth-service",
        target_symbol="verify_token",
        action=ChangeIntentAction.RENAME_SYMBOL,
        new_symbol="validate_token",
    )
    sites = engine.find_downstream_call_sites(intent)

    # 1. Synthetic patches (no disk files)
    patches = engine.generate_migration_patches([intent], sites)
    assert len(patches) == 2
    repo_names = {p.repo for p in patches}
    assert repo_names == {"frontend-app", "worker-backend"}
    for p in patches:
        assert p.unified_diff
        assert "validate_token" in p.unified_diff
        assert p.breaking_changes_resolved >= 1

    # 2. Disk-based patches
    repo_dir = tmp_path / "frontend-app"
    src_dir = repo_dir / "src"
    src_dir.mkdir(parents=True)
    auth_file = src_dir / "auth.ts"
    auth_file.write_text(
        "// line 1\n"
        "// line 2\n"
        "// line 3\n"
        "// line 4\n"
        "import { verify_token } from '@portfolio/auth-service';\n"
        "export function login() {\n"
        "  return true;\n"
        "}\n",
        encoding="utf-8",
    )

    disk_patches = engine.generate_migration_patches(
        [intent],
        sites,
        base_repo_paths={"frontend-app": repo_dir},
    )
    fe_patch = next(p for p in disk_patches if p.repo == "frontend-app")
    assert fe_patch.repo_path == str(repo_dir)
    assert "--- a/src/auth.ts" in fe_patch.unified_diff
    assert "+++ b/src/auth.ts" in fe_patch.unified_diff
    assert "-import { verify_token }" in fe_patch.unified_diff
    assert "+import { validate_token }" in fe_patch.unified_diff


def test_simulate_intent_end_to_end() -> None:
    """Test full simulation report generation including blast radius and advisories."""
    storage = _build_test_storage()
    engine = ChangeIntentEngine(storage_manager=storage)

    intent = ContractChangeIntent(
        repo="auth-service",
        target_symbol="verify_token",
        action=ChangeIntentAction.RENAME_SYMBOL,
        new_symbol="validate_token",
    )

    report = engine.simulate_intent(intent, generate_patches=True)
    assert report.total_intents == 1
    assert report.total_call_sites == 3
    assert set(report.affected_repos) == {"frontend-app", "worker-backend"}
    assert report.patches_available is True
    assert len(report.migration_patches) == 2
    assert report.overall_risk_level in (
        BlastRadiusSeverity.HIGH,
        BlastRadiusSeverity.CRITICAL,
        BlastRadiusSeverity.MEDIUM,
    )
