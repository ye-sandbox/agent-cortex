"""Repository discovery utilities for auto-discovering portfolio projects."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from cortex.config.loader import CortexConfig, RepositorySourceConfig
from cortex.ingestion.git import get_git_root, is_git_repository

logger = logging.getLogger(__name__)


def is_ignored(name: str, ignore_patterns: Sequence[str]) -> bool:
    """Check if directory name or path matches any ignore patterns."""
    for pattern in ignore_patterns:
        cleaned = pattern.rstrip("/")
        if name == cleaned or name.startswith(f"{cleaned}/"):
            return True
    return False


def discover_repositories(
    roots: Sequence[Path | str],
    max_depth: int = 3,
    ignore_patterns: Sequence[str] = (),
) -> list[Path]:
    """Scan root directories up to max_depth discovering git repository worktrees.

    Once a git repository is detected, does not recurse deeper into that repository
    to prevent detecting submodules or nested worktrees.
    """
    discovered: list[Path] = []
    seen_paths: set[Path] = set()

    for root_raw in roots:
        root_path = Path(root_raw).expanduser().resolve()
        if not root_path.is_dir():
            continue

        # If the root itself is a git repository
        if is_git_repository(root_path):
            if root_path not in seen_paths:
                discovered.append(root_path)
                seen_paths.add(root_path)
            continue

        _scan_directory(
            current_dir=root_path,
            current_depth=1,
            max_depth=max_depth,
            ignore_patterns=ignore_patterns,
            discovered=discovered,
            seen_paths=seen_paths,
        )

    return discovered


def _scan_directory(
    current_dir: Path,
    current_depth: int,
    max_depth: int,
    ignore_patterns: Sequence[str],
    discovered: list[Path],
    seen_paths: set[Path],
) -> None:
    """Recursively traverse directories discovering top-level git repositories."""
    if current_depth > max_depth:
        return

    try:
        entries = sorted(current_dir.iterdir(), key=lambda p: p.name)
    except (PermissionError, OSError) as exc:
        logger.debug("Cannot list directory %s: %s", current_dir, exc)
        return

    for entry in entries:
        if not entry.is_dir():
            continue

        if entry.name.startswith(".") and entry.name != ".git":
            continue

        if is_ignored(entry.name, ignore_patterns):
            continue

        # Check if entry is a git repo
        if (entry / ".git").exists() or is_git_repository(entry):
            resolved = entry.resolve()
            if resolved not in seen_paths:
                discovered.append(resolved)
                seen_paths.add(resolved)
            # Do not recurse into discovered git repo
            continue

        _scan_directory(
            current_dir=entry,
            current_depth=current_depth + 1,
            max_depth=max_depth,
            ignore_patterns=ignore_patterns,
            discovered=discovered,
            seen_paths=seen_paths,
        )


def resolve_sync_sources(
    config: CortexConfig,
    repo_filter: str | None = None,
    all_flag: bool = False,
    cwd: Path | str | None = None,
) -> list[RepositorySourceConfig]:
    """Resolve and deduplicate target repository sources based on flags, config, and CWD.

    Priority:
    1. If `repo_filter` is specified:
       - Matches by exact repository name or path in configured sources.
       - If not in configured sources, searches auto-discovered roots.
       - If path exists and is a git repository, resolves as target.
    2. If `all_flag` is True:
       - Returns all configured sources + auto-discovered repos.
    3. If neither is specified:
       - If cwd is inside a git repo: returns that single repository.
       - Otherwise: returns all configured repositories.
    """
    configured = list(config.sources.repositories)

    # 1. Targeted repository filter
    if repo_filter:
        clean_target = repo_filter.strip()
        for src in configured:
            if src.get_repo_name() == clean_target or str(src.path) == clean_target:
                return [src]

        # Check if clean_target is a filesystem directory and git repo
        target_path = Path(clean_target).expanduser().resolve()
        if target_path.is_dir() and is_git_repository(target_path):
            git_root = get_git_root(target_path)
            return [RepositorySourceConfig(path=git_root, name=git_root.name)]

        # Search auto-discovered repositories if enabled
        if config.sources.auto_discover.roots:
            discovered = discover_repositories(
                roots=config.sources.auto_discover.roots,
                max_depth=config.sources.auto_discover.max_depth,
                ignore_patterns=config.sources.auto_discover.ignore_patterns,
            )
            for p in discovered:
                if p.name == clean_target or str(p) == clean_target:
                    return [RepositorySourceConfig(path=p, name=p.name)]

        # Not found
        return []

    # 2. --all flag
    if all_flag:
        sources: list[RepositorySourceConfig] = list(configured)
        seen_paths = {s.path.resolve() for s in sources}

        if config.sources.auto_discover.enabled and config.sources.auto_discover.roots:
            discovered = discover_repositories(
                roots=config.sources.auto_discover.roots,
                max_depth=config.sources.auto_discover.max_depth,
                ignore_patterns=config.sources.auto_discover.ignore_patterns,
            )
            for p in discovered:
                if p not in seen_paths:
                    sources.append(RepositorySourceConfig(path=p, name=p.name))
                    seen_paths.add(p)

        if not sources:
            # Fall back to CWD if git repo
            current = Path(cwd or Path.cwd()).resolve()
            if is_git_repository(current):
                git_root = get_git_root(current)
                sources.append(RepositorySourceConfig(path=git_root, name=git_root.name))

        return sources

    # 3. Default (neither --repo nor --all)
    current = Path(cwd or Path.cwd()).resolve()
    if is_git_repository(current):
        git_root = get_git_root(current)
        for src in configured:
            if src.path.resolve() == git_root:
                return [src]
        return [RepositorySourceConfig(path=git_root, name=git_root.name)]

    return list(configured)
