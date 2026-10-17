"""State manifest management for tracking repository sync commits and metadata."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class RepoSyncState(BaseModel):
    """Sync state and commit checkpoint for an individual repository."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo_name: str = Field(..., description="Unique repository name")
    repo_path: str = Field(..., description="Absolute or normalized path to repository")
    last_synced_commit: str = Field(..., description="Commit SHA recorded at last successful sync")
    last_synced_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp of last successful sync",
    )
    chunk_count: int = Field(default=0, description="Total active chunks indexed for this repo")
    file_count: int = Field(default=0, description="Total files indexed for this repo")


class SyncManifest(BaseModel):
    """Root persistence model recording sync checkpoints across portfolio repositories."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    version: int = Field(default=1, description="Manifest schema version")
    repositories: dict[str, RepoSyncState] = Field(
        default_factory=dict,
        description="Map of repository name to sync state",
    )


class ManifestManager:
    """Manages loading, updating, and atomically saving the sync state manifest."""

    def __init__(self, manifest_path: Path | str) -> None:
        """Initialize manifest manager with destination file path."""
        self.manifest_path = Path(manifest_path).expanduser().resolve()
        self._manifest: SyncManifest | None = None

    def load(self) -> SyncManifest:
        """Load manifest from disk or initialize empty manifest if file does not exist."""
        if not self.manifest_path.is_file():
            self._manifest = SyncManifest()
            return self._manifest

        try:
            content = self.manifest_path.read_text(encoding="utf-8")
            raw_data = json.loads(content)
            self._manifest = SyncManifest.model_validate(raw_data)
            return self._manifest
        except Exception as exc:
            logger.warning(
                "Failed to parse manifest at '%s' (%s). Re-initializing fresh manifest.",
                self.manifest_path,
                exc,
            )
            self._manifest = SyncManifest()
            return self._manifest

    def save(self, manifest: SyncManifest | None = None) -> None:
        """Atomically persist manifest to disk via temporary file rename."""
        target_manifest = manifest if manifest is not None else self._manifest
        if target_manifest is None:
            target_manifest = SyncManifest()

        self._manifest = target_manifest
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

        payload = target_manifest.model_dump_json(indent=2)
        dir_name = self.manifest_path.parent

        # Atomic write to prevent partial corruption on crash
        fd, temp_file_path = tempfile.mkstemp(dir=dir_name, prefix="manifest_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file_path, self.manifest_path)
        except Exception:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            raise

    def get_repo_state(self, repo_name: str) -> RepoSyncState | None:
        """Retrieve recorded sync state for a repository."""
        manifest = self._manifest or self.load()
        return manifest.repositories.get(repo_name)

    def update_repo_state(self, repo_name: str, state: RepoSyncState) -> None:
        """Update or insert repository sync state and persist manifest."""
        manifest = self._manifest or self.load()
        updated_repos = dict(manifest.repositories)
        updated_repos[repo_name] = state
        new_manifest = SyncManifest(version=manifest.version, repositories=updated_repos)
        self.save(new_manifest)

    def remove_repo_state(self, repo_name: str) -> None:
        """Remove repository from manifest if present and persist changes."""
        manifest = self._manifest or self.load()
        if repo_name in manifest.repositories:
            updated_repos = {k: v for k, v in manifest.repositories.items() if k != repo_name}
            new_manifest = SyncManifest(version=manifest.version, repositories=updated_repos)
            self.save(new_manifest)
