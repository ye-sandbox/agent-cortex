"""Data models for Git drift tracking and incremental portfolio sync."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from cortex.models.drift import ContractDriftAlert


class FileChangeType(StrEnum):
    """Git file status codes for working tree and commit drift."""

    ADDED = "A"
    MODIFIED = "M"
    DELETED = "D"
    RENAMED = "R"
    COPIED = "C"


class FileChange(BaseModel):
    """Represents a single changed file detected via git status or diff."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    change_type: FileChangeType = Field(..., description="Type of git change")
    path: str = Field(..., description="Target relative file path within repository")
    old_path: str | None = Field(
        default=None,
        description="Original relative file path if the file was renamed or copied",
    )


class GitDriftSummary(BaseModel):
    """Summary of changes between base commit and target commit (or HEAD)."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str = Field(..., description="Logical repository name")
    repo_path: Path = Field(..., description="Filesystem path to repository root")
    base_commit: str | None = Field(
        default=None,
        description="Starting commit SHA (None for initial scan)",
    )
    target_commit: str = Field(..., description="Ending commit SHA (typically HEAD)")
    changes: list[FileChange] = Field(
        default_factory=list,
        description="List of detected file-level changes",
    )

    @property
    def has_changes(self) -> bool:
        """Return True if any files changed between commits."""
        return len(self.changes) > 0

    @property
    def added_files(self) -> list[FileChange]:
        """Return list of files marked as ADDED or COPIED."""
        return [
            c
            for c in self.changes
            if c.change_type in (FileChangeType.ADDED, FileChangeType.COPIED)
        ]

    @property
    def modified_files(self) -> list[FileChange]:
        """Return list of files marked as MODIFIED."""
        return [c for c in self.changes if c.change_type == FileChangeType.MODIFIED]

    @property
    def deleted_files(self) -> list[FileChange]:
        """Return list of files marked as DELETED."""
        return [c for c in self.changes if c.change_type == FileChangeType.DELETED]

    @property
    def renamed_files(self) -> list[FileChange]:
        """Return list of files marked as RENAMED."""
        return [c for c in self.changes if c.change_type == FileChangeType.RENAMED]


class SyncResult(BaseModel):
    """Result of an incremental or full ingestion sync run for a repository."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str = Field(..., description="Logical repository name")
    base_commit: str | None = Field(
        default=None,
        description="Commit SHA prior to sync, or None if first sync",
    )
    target_commit: str = Field(..., description="Commit SHA after sync")
    added_chunks: int = Field(default=0, description="Number of newly indexed chunks")
    updated_chunks: int = Field(default=0, description="Number of updated chunks")
    deleted_chunks: int = Field(default=0, description="Number of deleted orphan chunks")
    processed_files: int = Field(default=0, description="Total number of modified files parsed")
    duration_seconds: float = Field(default=0.0, description="Total execution time in seconds")
    errors: list[str] = Field(
        default_factory=list,
        description="Error messages encountered during sync",
    )
    drift_alerts: list[ContractDriftAlert] = Field(
        default_factory=list,
        description="Architectural contract drift alerts detected during sync",
    )

    @property
    def is_success(self) -> bool:
        """Return True if sync completed without errors."""
        return len(self.errors) == 0

    @property
    def has_changes(self) -> bool:
        """Return True if any chunks were added, updated, or deleted."""
        return (self.added_chunks + self.updated_chunks + self.deleted_chunks) > 0
