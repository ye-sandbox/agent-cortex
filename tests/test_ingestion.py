"""Hermetic unit and integration tests for Git drift tracking and incremental ingestion."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from cortex.config.loader import RepositorySourceConfig
from cortex.embeddings.engine import EmbeddingEngine
from cortex.ingestion.engine import IngestionEngine
from cortex.ingestion.git import (
    get_git_common_dir,
    get_git_root,
    get_head_commit,
    is_commit_valid,
    is_git_repository,
    list_tracked_files,
    scan_git_drift,
)
from cortex.ingestion.manifest import ManifestManager, RepoSyncState
from cortex.ingestion.models import FileChangeType
from cortex.models.chunk import DocumentChunk
from cortex.storage.manager import StorageManager


def init_mock_git_repo(repo_dir: Path) -> None:
    """Initialize a bare-bones git repo with user configuration for testing."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test Agent"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "agent@cortex.test"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )


def git_commit(repo_dir: Path, message: str) -> str:
    """Stage all changes and create a git commit, returning new HEAD commit SHA."""
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_dir, check=True, capture_output=True)
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


def mock_passage_embed(texts: Sequence[str]) -> list[list[float]]:
    """Deterministic mock embedding producing 3-dim vectors."""
    return [[float(len(t) % 10), 0.5, 0.25] for t in texts]


def test_manifest_manager_lifecycle(tmp_path: Path) -> None:
    """Test loading, saving, updating, and removing states with ManifestManager."""
    manifest_file = tmp_path / "manifest.json"
    mgr = ManifestManager(manifest_file)

    # Initially empty
    manifest = mgr.load()
    assert manifest.version == 1
    assert len(manifest.repositories) == 0
    assert mgr.get_repo_state("repo-a") is None

    # Update state
    state_a = RepoSyncState(
        repo_name="repo-a",
        repo_path="/path/to/repo-a",
        last_synced_commit="c0ffee01",
        chunk_count=5,
        file_count=2,
    )
    mgr.update_repo_state("repo-a", state_a)

    assert manifest_file.is_file()
    assert mgr.get_repo_state("repo-a") == state_a

    # Reload fresh instance from disk
    mgr2 = ManifestManager(manifest_file)
    loaded = mgr2.load()
    assert "repo-a" in loaded.repositories
    assert loaded.repositories["repo-a"].last_synced_commit == "c0ffee01"

    # Remove state
    mgr2.remove_repo_state("repo-a")
    assert mgr2.get_repo_state("repo-a") is None

    # Corrupt JSON recovery
    manifest_file.write_text("invalid json content!", encoding="utf-8")
    recovered = mgr.load()
    assert recovered.version == 1
    assert len(recovered.repositories) == 0


def test_git_utils_and_drift_scanner(tmp_path: Path) -> None:
    """Test git inspection utilities and drift scanner on commit diffs."""
    repo_dir = tmp_path / "mock-repo"
    assert not is_git_repository(repo_dir)
    with pytest.raises(ValueError, match="not a valid git repository"):
        scan_git_drift(repo_dir)

    init_mock_git_repo(repo_dir)
    assert is_git_repository(repo_dir)
    assert get_git_root(repo_dir) == repo_dir.resolve()
    assert get_git_common_dir(repo_dir) == (repo_dir / ".git").resolve()

    # Commit initial files
    (repo_dir / "README.md").write_text("# Mock Project\nIntro text", encoding="utf-8")
    (repo_dir / "compose.yaml").write_text(
        "services:\n  web:\n    image: nginx:alpine\n",
        encoding="utf-8",
    )
    c1 = git_commit(repo_dir, "Initial commit")

    assert get_head_commit(repo_dir) == c1
    assert is_commit_valid(repo_dir, c1)
    assert not is_commit_valid(repo_dir, "deadbeef" * 5)

    tracked = list_tracked_files(repo_dir)
    assert "README.md" in tracked
    assert "compose.yaml" in tracked

    # Drift with base_commit=None -> all tracked files returned as ADDED
    initial_drift = scan_git_drift(repo_dir, base_commit=None, target_commit=c1)
    assert initial_drift.has_changes
    assert len(initial_drift.added_files) == 2

    # Zero drift when comparing c1 to c1
    zero_drift = scan_git_drift(repo_dir, base_commit=c1, target_commit=c1)
    assert not zero_drift.has_changes
    assert len(zero_drift.changes) == 0

    # Add a file, modify one, delete one, rename one across commits
    (repo_dir / "openapi.json").write_text('{"openapi": "3.0.0"}', encoding="utf-8")
    (repo_dir / "README.md").write_text("# Mock Project Updated\nMore details", encoding="utf-8")
    subprocess.run(["git", "mv", "compose.yaml", "docker-compose.yml"], cwd=repo_dir, check=True)
    c2 = git_commit(repo_dir, "Add openapi, modify readme, rename compose")

    drift_c1_c2 = scan_git_drift(repo_dir, base_commit=c1, target_commit=c2)
    assert drift_c1_c2.has_changes
    assert any(
        c.path == "openapi.json" and c.change_type == FileChangeType.ADDED
        for c in drift_c1_c2.changes
    )
    assert any(
        c.path == "README.md" and c.change_type == FileChangeType.MODIFIED
        for c in drift_c1_c2.changes
    )
    assert any(
        c.path == "docker-compose.yml"
        and c.old_path == "compose.yaml"
        and c.change_type == FileChangeType.RENAMED
        for c in drift_c1_c2.changes
    )

    # Delete a file
    subprocess.run(["git", "rm", "openapi.json"], cwd=repo_dir, check=True)
    c3 = git_commit(repo_dir, "Remove openapi")
    drift_c2_c3 = scan_git_drift(repo_dir, base_commit=c2, target_commit=c3)
    assert any(
        c.path == "openapi.json" and c.change_type == FileChangeType.DELETED
        for c in drift_c2_c3.changes
    )


def test_ingestion_engine_incremental_flow(tmp_path: Path) -> None:
    """Test full incremental ingestion lifecycle in IngestionEngine."""
    storage_dir = tmp_path / "data"
    storage = StorageManager(storage_dir)
    manifest = ManifestManager(storage_dir / "manifest.json")
    embedding = EmbeddingEngine(passage_embed_fn=mock_passage_embed)

    engine = IngestionEngine(
        storage_manager=storage,
        embedding_engine=embedding,
        manifest_manager=manifest,
    )

    repo_dir = tmp_path / "demo-service"
    init_mock_git_repo(repo_dir)

    # Commit 1: Initial files
    (repo_dir / "README.md").write_text("# Demo Service\nInitial description.", encoding="utf-8")
    (repo_dir / "compose.yaml").write_text(
        "services:\n  app:\n    image: python:3.12-slim\n",
        encoding="utf-8",
    )
    (repo_dir / "ignored.txt").write_text("plain text ignored by parsers", encoding="utf-8")
    c1 = git_commit(repo_dir, "Initial commit")

    # 1. First sync -> initial full sync
    res1 = engine.sync_repository(repo_dir, repo_name="demo-service")
    assert res1.is_success
    assert res1.base_commit is None
    assert res1.target_commit == c1
    assert res1.added_chunks > 0
    assert storage.count_chunks(where="repo = 'demo-service'") == res1.added_chunks

    # Manifest should record state
    state1 = manifest.get_repo_state("demo-service")
    assert state1 is not None
    assert state1.last_synced_commit == c1
    assert state1.chunk_count == res1.added_chunks

    # 2. Sync again without any changes -> 0 chunks touched
    res2 = engine.sync_repository(repo_dir, repo_name="demo-service")
    assert res2.is_success
    assert res2.base_commit == c1
    assert res2.target_commit == c1
    assert res2.added_chunks == 0
    assert res2.updated_chunks == 0
    assert res2.deleted_chunks == 0

    # 3. Modification: Update README.md
    (repo_dir / "README.md").write_text(
        "# Demo Service\nUpdated description.\n## Features\n- Fast incremental search",
        encoding="utf-8",
    )
    c2 = git_commit(repo_dir, "Update readme with features")

    res3 = engine.sync_repository(repo_dir, repo_name="demo-service")
    assert res3.is_success
    assert res3.base_commit == c1
    assert res3.target_commit == c2
    assert res3.updated_chunks > 0

    state2 = manifest.get_repo_state("demo-service")
    assert state2 is not None
    assert state2.last_synced_commit == c2

    # 4. Rename: Rename compose.yaml -> docker-compose.yml
    subprocess.run(["git", "mv", "compose.yaml", "docker-compose.yml"], cwd=repo_dir, check=True)
    c3 = git_commit(repo_dir, "Rename compose to docker-compose")

    res4 = engine.sync_repository(repo_dir, repo_name="demo-service")
    assert res4.is_success
    assert res4.base_commit == c2
    assert res4.target_commit == c3
    assert res4.deleted_chunks >= 1  # old path pruned
    assert res4.added_chunks >= 1  # new path indexed

    # Verify old file path chunks are gone
    old_compose_chunks = storage.count_chunks(
        where="repo = 'demo-service' AND file_path = 'compose.yaml'"
    )
    assert old_compose_chunks == 0
    new_compose_chunks = storage.count_chunks(
        where="repo = 'demo-service' AND file_path = 'docker-compose.yml'"
    )
    assert new_compose_chunks > 0

    # 5. Deletion: Remove docker-compose.yml
    subprocess.run(["git", "rm", "docker-compose.yml"], cwd=repo_dir, check=True)
    c4 = git_commit(repo_dir, "Remove docker-compose")

    res5 = engine.sync_repository(repo_dir, repo_name="demo-service")
    assert res5.is_success
    assert res5.base_commit == c3
    assert res5.target_commit == c4
    assert res5.deleted_chunks >= 1

    remaining_compose_chunks = storage.count_chunks(
        where="repo = 'demo-service' AND file_path = 'docker-compose.yml'"
    )
    assert remaining_compose_chunks == 0

    # 6. Force full re-sync
    res6 = engine.sync_repository(repo_dir, repo_name="demo-service", force_full=True)
    assert res6.is_success
    assert res6.base_commit is None
    assert res6.target_commit == c4


def test_ingestion_engine_sync_all(tmp_path: Path) -> None:
    """Test sync_all iterating through multiple configured repositories."""
    storage_dir = tmp_path / "data"
    storage = StorageManager(storage_dir)
    manifest = ManifestManager(storage_dir / "manifest.json")
    embedding = EmbeddingEngine(passage_embed_fn=mock_passage_embed)

    engine = IngestionEngine(
        storage_manager=storage,
        embedding_engine=embedding,
        manifest_manager=manifest,
    )

    repo_a = tmp_path / "repo-a"
    init_mock_git_repo(repo_a)
    (repo_a / "README.md").write_text("# Repo A", encoding="utf-8")
    git_commit(repo_a, "Init repo a")

    repo_b = tmp_path / "repo-b"
    init_mock_git_repo(repo_b)
    (repo_b / "README.md").write_text("# Repo B", encoding="utf-8")
    git_commit(repo_b, "Init repo b")

    sources = [
        RepositorySourceConfig(path=repo_a, name="repo-a", enabled=True),
        RepositorySourceConfig(path=repo_b, name="repo-b", enabled=False),
    ]

    results = engine.sync_all(sources)
    assert len(results) == 1
    assert results[0].repo == "repo-a"
    assert results[0].is_success

    assert manifest.get_repo_state("repo-a") is not None
    assert manifest.get_repo_state("repo-b") is None


def test_git_worktree_detection(tmp_path: Path) -> None:
    """Test git worktree common dir detection per ADR-006."""
    main_repo = tmp_path / "main-repo"
    init_mock_git_repo(main_repo)
    (main_repo / "README.md").write_text("# Main", encoding="utf-8")
    git_commit(main_repo, "Initial main commit")

    # Create secondary worktree
    worktree_dir = tmp_path / "worktree-repo"
    subprocess.run(
        ["git", "worktree", "add", str(worktree_dir), "-b", "feature-branch"],
        cwd=main_repo,
        check=True,
        capture_output=True,
    )

    assert is_git_repository(worktree_dir)
    assert get_git_root(worktree_dir) == worktree_dir.resolve()
    # Common dir must resolve to main repo's .git directory
    assert get_git_common_dir(worktree_dir) == (main_repo / ".git").resolve()


def test_ingestion_engine_error_handling(tmp_path: Path) -> None:
    """Test error handling in IngestionEngine for invalid repositories or parsing failures."""
    storage_dir = tmp_path / "data"
    storage = StorageManager(storage_dir)
    manifest = ManifestManager(storage_dir / "manifest.json")
    embedding = EmbeddingEngine(passage_embed_fn=mock_passage_embed)

    engine = IngestionEngine(
        storage_manager=storage,
        embedding_engine=embedding,
        manifest_manager=manifest,
    )

    # 1. Non-git directory
    not_a_repo = tmp_path / "plain_dir"
    not_a_repo.mkdir()
    res = engine.sync_repository(not_a_repo, repo_name="plain")
    assert not res.is_success
    assert len(res.errors) == 1
    assert "not a valid git repository" in res.errors[0]

    # 2. File with parsing error
    repo_dir = tmp_path / "error-repo"
    init_mock_git_repo(repo_dir)
    (repo_dir / "README.md").write_text("# Error readme\n", encoding="utf-8")
    git_commit(repo_dir, "Commit readme")

    def failing_parse(*args: object, **kwargs: object) -> list[DocumentChunk]:
        raise ValueError("Simulated parsing crash")

    from unittest.mock import patch

    with patch("cortex.ingestion.engine.parse_document", side_effect=failing_parse):
        res2 = engine.sync_repository(repo_dir, repo_name="error-repo")
        assert not res2.is_success
        assert len(res2.errors) > 0
        assert "Simulated parsing crash" in res2.errors[0]


def test_ingestion_engine_from_config(tmp_path: Path) -> None:
    """Test factory constructor IngestionEngine.from_config."""
    from cortex.config.loader import CortexConfig, StorageConfig

    config = CortexConfig(
        storage=StorageConfig(data_dir=tmp_path / "custom_data"),
    )
    engine = IngestionEngine.from_config(config)
    assert engine.storage.data_dir == (tmp_path / "custom_data").resolve()
    assert engine.manifest.manifest_path == (tmp_path / "custom_data" / "manifest.json").resolve()
