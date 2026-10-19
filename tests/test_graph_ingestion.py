"""Hermetic tests for incremental ingestion of AST code signatures and dependencies."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from cortex.embeddings.engine import EmbeddingEngine
from cortex.ingestion.engine import IngestionEngine
from cortex.ingestion.manifest import ManifestManager
from cortex.storage.manager import StorageManager


def init_mock_git_repo(repo_dir: Path) -> None:
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
    return [[float(len(t) % 10), 0.5, 0.25] for t in texts]


def test_ingestion_code_signatures_and_dependencies(tmp_path: Path) -> None:
    storage_dir = tmp_path / "data"
    storage = StorageManager(storage_dir)
    manifest = ManifestManager(storage_dir / "manifest.json")
    embedding = EmbeddingEngine(passage_embed_fn=mock_passage_embed)

    engine = IngestionEngine(
        storage_manager=storage,
        embedding_engine=embedding,
        manifest_manager=manifest,
    )

    repo_dir = tmp_path / "demo-repo"
    init_mock_git_repo(repo_dir)

    # Initial code file
    py_code = (
        "import os\n"
        "from cortex import StorageManager\n\n"
        "class Pipeline:\n"
        "    def run(self) -> None:\n"
        "        StorageManager()\n"
    )
    (repo_dir / "pipeline.py").write_text(py_code, encoding="utf-8")
    git_commit(repo_dir, "Add pipeline.py")

    # 1. Sync
    res1 = engine.sync_repository(repo_dir, repo_name="demo-repo")
    assert res1.is_success

    # Verify signatures and dependencies indexed
    sigs = storage.get_signatures(where="repo = 'demo-repo'")
    assert len(sigs) >= 2  # Pipeline and Pipeline.run
    sig_ids = [s.identifier for s in sigs]
    assert "Pipeline" in sig_ids
    assert "Pipeline.run" in sig_ids

    deps = storage.get_dependencies(where="source_repo = 'demo-repo'")
    assert len(deps) >= 2  # import os, from cortex import StorageManager, and call
    target_mods = [d.target_module for d in deps]
    assert "os" in target_mods
    assert "cortex" in target_mods

    # 2. Modify code file
    updated_py = "import sys\n\ndef new_function() -> str:\n    return 'hello'\n"
    (repo_dir / "pipeline.py").write_text(updated_py, encoding="utf-8")
    git_commit(repo_dir, "Update pipeline.py")

    res2 = engine.sync_repository(repo_dir, repo_name="demo-repo")
    assert res2.is_success

    # Old signatures and dependencies should be purged, new ones present
    updated_sigs = storage.get_signatures(where="repo = 'demo-repo'")
    updated_sig_ids = [s.identifier for s in updated_sigs]
    assert "Pipeline" not in updated_sig_ids
    assert "new_function" in updated_sig_ids

    updated_deps = storage.get_dependencies(where="source_repo = 'demo-repo'")
    updated_mods = [d.target_module for d in updated_deps]
    assert "os" not in updated_mods
    assert "sys" in updated_mods

    # 3. Delete code file
    subprocess.run(["git", "rm", "pipeline.py"], cwd=repo_dir, check=True)
    git_commit(repo_dir, "Delete pipeline.py")

    res3 = engine.sync_repository(repo_dir, repo_name="demo-repo")
    assert res3.is_success

    # Cleaned up from LanceDB
    assert len(storage.get_signatures(where="repo = 'demo-repo'")) == 0
    assert len(storage.get_dependencies(where="source_repo = 'demo-repo'")) == 0
