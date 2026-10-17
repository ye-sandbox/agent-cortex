"""Hermetic tests for repository auto-discovery and sync source resolution."""

from __future__ import annotations

import subprocess
from pathlib import Path

from cortex.config.loader import (
    AutoDiscoverConfig,
    CortexConfig,
    RepositorySourceConfig,
    SourcesConfig,
)
from cortex.ingestion.discovery import (
    discover_repositories,
    is_ignored,
    resolve_sync_sources,
)


def _init_git_repo(path: Path) -> None:
    """Helper to initialize an empty git repo in a directory."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "agent@sandbox.local"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Agent Cortex"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def test_is_ignored() -> None:
    patterns = ["node_modules", ".venv", "dist/"]
    assert is_ignored("node_modules", patterns)
    assert is_ignored("node_modules/foo", patterns)
    assert is_ignored(".venv", patterns)
    assert is_ignored("dist", patterns)
    assert not is_ignored("src", patterns)
    assert not is_ignored("my_service", patterns)


def test_discover_repositories(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    # Create 2 valid git repos
    repo1 = root / "service-a"
    _init_git_repo(repo1)

    repo2 = root / "team" / "service-b"
    _init_git_repo(repo2)

    # Create ignored folder with git repo inside
    ignored_repo = root / "node_modules" / "some-lib"
    _init_git_repo(ignored_repo)

    # Create non-repo directory
    non_repo = root / "docs"
    non_repo.mkdir()

    discovered = discover_repositories(
        roots=[root],
        max_depth=3,
        ignore_patterns=["node_modules"],
    )

    discovered_names = {p.name for p in discovered}
    assert "service-a" in discovered_names
    assert "service-b" in discovered_names
    assert "some-lib" not in discovered_names
    assert "docs" not in discovered_names


def test_resolve_sync_sources_by_name(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo1"
    _init_git_repo(repo_dir)

    cfg = CortexConfig(
        sources=SourcesConfig(
            repositories=[
                RepositorySourceConfig(path=repo_dir, name="repo1"),
            ]
        )
    )

    sources = resolve_sync_sources(config=cfg, repo_filter="repo1")
    assert len(sources) == 1
    assert sources[0].get_repo_name() == "repo1"


def test_resolve_sync_sources_by_path(tmp_path: Path) -> None:
    repo_dir = tmp_path / "standalone-repo"
    _init_git_repo(repo_dir)

    cfg = CortexConfig()
    sources = resolve_sync_sources(config=cfg, repo_filter=str(repo_dir))
    assert len(sources) == 1
    assert sources[0].get_repo_name() == "standalone-repo"
    assert sources[0].path.resolve() == repo_dir.resolve()


def test_resolve_sync_sources_all(tmp_path: Path) -> None:
    repo1 = tmp_path / "repo1"
    repo2 = tmp_path / "discovered-repo"
    _init_git_repo(repo1)
    _init_git_repo(repo2)

    cfg = CortexConfig(
        sources=SourcesConfig(
            repositories=[RepositorySourceConfig(path=repo1, name="repo1")],
            auto_discover=AutoDiscoverConfig(
                enabled=True,
                roots=[tmp_path],
                max_depth=2,
            ),
        )
    )

    sources = resolve_sync_sources(config=cfg, all_flag=True)
    names = {s.get_repo_name() for s in sources}
    assert "repo1" in names
    assert "discovered-repo" in names


def test_resolve_sync_sources_cwd_fallback(tmp_path: Path) -> None:
    repo_dir = tmp_path / "current-repo"
    _init_git_repo(repo_dir)

    cfg = CortexConfig()
    sources = resolve_sync_sources(config=cfg, cwd=repo_dir)
    assert len(sources) == 1
    assert sources[0].get_repo_name() == "current-repo"


def test_resolve_sync_sources_not_found(tmp_path: Path) -> None:
    cfg = CortexConfig()
    sources = resolve_sync_sources(config=cfg, repo_filter="nonexistent-repo")
    assert sources == []
