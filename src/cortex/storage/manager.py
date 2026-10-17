"""Safe, in-process LanceDB storage manager for agent-cortex."""

from __future__ import annotations

import logging
import os
import warnings
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import lancedb
from lancedb.db import DBConnection
from lancedb.index import FTS
from lancedb.table import Table
from pydantic import BaseModel, ConfigDict, Field

from cortex.models.chunk import DocumentChunk
from cortex.storage.schema import (
    chunk_to_record_dict,
    create_chunk_record_model,
)

logger = logging.getLogger(__name__)


class CompactionResult(BaseModel):
    """Metrics and disk space savings from a table compaction operation."""

    model_config = ConfigDict(frozen=True)

    table_name: str
    chunks_count: int
    bytes_before: int
    bytes_after: int
    bytes_freed: int = Field(default=0)
    fragments_before: int = Field(default=0)
    fragments_after: int = Field(default=0)
    versions_before: int = Field(default=0)
    versions_after: int = Field(default=0)


def _get_table_disk_size(path: Path) -> int:
    """Calculate the total on-disk size in bytes for a table directory."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def validate_storage_path(path: Path | str) -> Path:
    """Ensure storage path adheres to data isolation and repo hygiene rules.

    Raises ValueError if target path resides within an un-gitignored repository directory.
    """
    p = Path(path).expanduser().resolve()

    # If inside a temporary directory, always permit
    tmp_dir = Path("/tmp").resolve()
    if p.is_relative_to(tmp_dir):
        return p

    # Find if path is within a git repository
    current: Path | None = p
    git_root: Path | None = None
    while current and current != current.parent:
        if (current / ".git").exists():
            git_root = current
            break
        current = current.parent

    if git_root is not None:
        rel = p.relative_to(git_root)
        # Check against explicitly ignored directories in git root
        allowed_prefixes = ("data", ".tmp", "tmp", "venv", ".venv", ".cache")
        parts = rel.parts
        if not parts or not any(parts[0].startswith(prefix) for prefix in allowed_prefixes):
            msg = (
                f"Unsafe storage path '{p}'. "
                "Indexed vector data MUST NOT reside within unignored repository source trees. "
                "Use external paths (e.g. ~/.local/share/agent-cortex/data) "
                "or a gitignored 'data/' directory."
            )
            raise ValueError(msg)

    return p


class StorageManager:
    """Manages embedded LanceDB vector database connection, tables, indexes, and queries."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        """Initialize LanceDB connection at data_dir (defaulting to config / env / user share)."""
        if data_dir is not None:
            resolved_path = Path(data_dir)
        else:
            env_override = os.environ.get("AGENT_CORTEX_DATA_DIR")
            if env_override:
                resolved_path = Path(env_override)
            else:
                resolved_path = Path("~/.local/share/agent-cortex/data")

        self.data_dir = validate_storage_path(resolved_path)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._db: DBConnection = lancedb.connect(str(self.data_dir))

    @property
    def db(self) -> DBConnection:
        """Return the underlying LanceDB connection."""
        return self._db

    def table_names(self) -> list[str]:
        """Return list of existing table names."""
        res = self._db.list_tables()
        return list(res.tables)

    def get_or_create_table(
        self,
        name: str = "chunks",
        dim: int = 384,
    ) -> Table:
        """Retrieve existing table or create a new one matching DocumentChunk schema."""
        if name in self.table_names():
            return self._db.open_table(name)

        model_cls = create_chunk_record_model(dim)
        return self._db.create_table(name, schema=model_cls)

    def upsert_chunks(
        self,
        chunks: Sequence[DocumentChunk],
        table_name: str = "chunks",
        dim: int = 384,
        create_fts: bool = True,
    ) -> int:
        """Upsert document chunks into LanceDB table using deterministic IDs."""
        if not chunks:
            return 0

        # Infer dimension from first chunk vector if available
        first_vec = chunks[0].vector
        actual_dim = len(first_vec) if first_vec is not None else dim

        tbl = self.get_or_create_table(name=table_name, dim=actual_dim)

        records = [chunk_to_record_dict(c) for c in chunks]

        # Idempotent merge_insert on deterministic ID
        (
            tbl.merge_insert("id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(records)
        )

        if create_fts:
            self.create_fts_index(table_name=table_name, replace=True)

        return len(chunks)

    def create_fts_index(
        self,
        table_name: str = "chunks",
        field_name: str = "content",
        replace: bool = True,
    ) -> bool:
        """Create or rebuild full-text search (Tantivy) index on the target table."""
        if table_name not in self.table_names():
            return False
        tbl = self._db.open_table(table_name)
        try:
            tbl.create_index(field_name, config=FTS(), replace=replace)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "FTS index creation on '%s.%s' deferred or failed: %s",
                table_name,
                field_name,
                exc,
            )
            return False

    def create_vector_index(
        self,
        table_name: str = "chunks",
        column: str = "vector",
        metric: Literal["l2", "cosine", "dot", "hamming"] = "cosine",
        min_rows: int = 256,
        replace: bool = True,
    ) -> bool:
        """Create IVF-PQ vector index on target table if row count meets minimum threshold."""
        if table_name not in self.table_names():
            return False
        tbl = self._db.open_table(table_name)
        try:
            row_count = int(tbl.count_rows())
            if row_count < min_rows:
                logger.debug(
                    "Skipping vector index on '%s': row count (%d) is below threshold (%d)",
                    table_name,
                    row_count,
                    min_rows,
                )
                return False
            tbl.create_index(metric=metric, vector_column_name=column, replace=replace)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vector index creation on '%s.%s' failed: %s", table_name, column, exc)
            return False

    def delete_by_id(self, chunk_id: str, table_name: str = "chunks") -> None:
        """Delete single chunk by deterministic ID."""
        if table_name not in self.table_names():
            return
        tbl = self._db.open_table(table_name)
        # Escape single quotes in chunk_id
        safe_id = chunk_id.replace("'", "''")
        tbl.delete(f"id = '{safe_id}'")

    def delete_by_repo(self, repo: str, table_name: str = "chunks") -> None:
        """Delete all chunks belonging to a repository."""
        if table_name not in self.table_names():
            return
        tbl = self._db.open_table(table_name)
        safe_repo = repo.replace("'", "''")
        tbl.delete(f"repo = '{safe_repo}'")

    def delete_by_file(self, repo: str, file_path: str, table_name: str = "chunks") -> None:
        """Delete all chunks belonging to a specific repository file."""
        if table_name not in self.table_names():
            return
        tbl = self._db.open_table(table_name)
        safe_repo = repo.replace("'", "''")
        safe_path = file_path.replace("'", "''")
        tbl.delete(f"repo = '{safe_repo}' AND file_path = '{safe_path}'")

    def count_chunks(self, table_name: str = "chunks", where: str | None = None) -> int:
        """Count rows in target table, optionally matching a SQL where filter."""
        if table_name not in self.table_names():
            return 0
        tbl = self._db.open_table(table_name)
        return int(tbl.count_rows(filter=where))

    def vector_search(
        self,
        query_vector: Sequence[float],
        limit: int = 20,
        where: str | None = None,
        table_name: str = "chunks",
    ) -> list[dict[str, Any]]:
        """Perform dense vector distance search against target table."""
        if table_name not in self.table_names():
            return []
        tbl = self._db.open_table(table_name)
        builder = tbl.search(list(query_vector)).limit(limit)
        if where:
            builder = builder.where(where)
        results: list[dict[str, Any]] = builder.to_list()
        return results

    def fts_search(
        self,
        query_text: str,
        limit: int = 20,
        where: str | None = None,
        table_name: str = "chunks",
    ) -> list[dict[str, Any]]:
        """Perform sparse full-text search against indexed content column."""
        if table_name not in self.table_names():
            return []
        tbl = self._db.open_table(table_name)
        try:
            builder = tbl.search(query_text, query_type="fts").limit(limit)
            if where:
                builder = builder.where(where)
            results: list[dict[str, Any]] = builder.to_list()
            return results
        except Exception as exc:  # noqa: BLE001
            logger.warning("FTS search encountered error: %s", exc)
            return []

    def get_chunks(
        self,
        where: str | None = None,
        limit: int | None = None,
        table_name: str = "chunks",
    ) -> list[dict[str, Any]]:
        """Retrieve chunks directly via SQL where filter without vector search."""
        if table_name not in self.table_names():
            return []
        tbl = self._db.open_table(table_name)
        builder = tbl.search()
        if where:
            builder = builder.where(where)
        if limit is not None:
            builder = builder.limit(limit)
        results: list[dict[str, Any]] = builder.to_list()
        return results

    def get_repo_contracts(
        self,
        repo: str,
        categories: Sequence[str] | None = None,
        limit: int = 50,
        table_name: str = "chunks",
    ) -> list[dict[str, Any]]:
        """Retrieve contract, infrastructure, and invariant chunks for a repository."""
        if table_name not in self.table_names():
            return []
        safe_repo = repo.strip().replace("'", "''")
        target_categories = (
            list(categories) if categories is not None else ["contract", "infra", "invariant"]
        )
        cat_list = ", ".join(f"'{c}'" for c in target_categories)
        where = f"repo = '{safe_repo}' AND category IN ({cat_list})"
        return self.get_chunks(where=where, limit=limit, table_name=table_name)

    def get_technologies(
        self,
        repo: str | None = None,
        table_name: str = "chunks",
    ) -> list[dict[str, Any]]:
        """Retrieve technology tags and repository associations across indexed chunks."""
        if table_name not in self.table_names():
            return []
        tbl = self._db.open_table(table_name)
        builder = tbl.search().select(["repo", "tags", "file_path"])
        if repo and repo.strip():
            safe_repo = repo.strip().replace("'", "''")
            builder = builder.where(f"repo = '{safe_repo}'")
        results: list[dict[str, Any]] = builder.to_list()
        return results

    @staticmethod
    def _inspect_table_telemetry(tbl: Table) -> tuple[int, int]:
        """Extract (fragments_count, versions_count) from native LanceDB table metadata."""
        fragments = 0
        try:
            stats = tbl.stats()
            if isinstance(stats, dict):
                frag_stats = stats.get("fragment_stats")
                if isinstance(frag_stats, dict):
                    fragments = int(frag_stats.get("num_fragments", 0))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to retrieve native table stats: %s", exc)

        versions_count = 0
        try:
            versions = tbl.list_versions()
            versions_count = len(versions)
            if fragments == 0 and versions:
                latest_meta = versions[-1].get("metadata")
                if isinstance(latest_meta, dict) and "total_fragments" in latest_meta:
                    fragments = int(latest_meta["total_fragments"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to retrieve version list: %s", exc)

        return fragments, versions_count

    @staticmethod
    def _get_native_table_bytes(tbl: Table) -> int:
        """Extract total byte size reported natively by LanceDB table stats."""
        try:
            stats = tbl.stats()
            if isinstance(stats, dict):
                return int(stats.get("total_bytes", 0))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to retrieve native table total_bytes: %s", exc)
        return 0

    def inspect_table_telemetry(self, table_name: str = "chunks") -> tuple[int, int]:
        """Return (fragment_count, version_count) for target table using native metadata."""
        if table_name not in self.table_names():
            return 0, 0
        tbl = self._db.open_table(table_name)
        return self._inspect_table_telemetry(tbl)

    def compact_table(
        self,
        table_name: str = "chunks",
        cleanup_older_than: timedelta | None = None,
        delete_unverified: bool = True,
    ) -> CompactionResult:
        """Run LanceDB compaction, fragment pruning, and index optimization on a table."""
        if table_name not in self.table_names():
            msg = f"Table '{table_name}' does not exist in database at '{self.data_dir}'."
            raise ValueError(msg)

        tbl = self._db.open_table(table_name)
        fragments_before, versions_before = self._inspect_table_telemetry(tbl)

        table_dir = self.data_dir / f"{table_name}.lance"
        bytes_before = _get_table_disk_size(table_dir)
        if bytes_before == 0:
            bytes_before = self._get_native_table_bytes(tbl)

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*removes every version except the latest.*")
            tbl.optimize(cleanup_older_than=cleanup_older_than, delete_unverified=delete_unverified)

        fragments_after, versions_after = self._inspect_table_telemetry(tbl)
        bytes_after = _get_table_disk_size(table_dir)
        if bytes_after == 0:
            bytes_after = self._get_native_table_bytes(tbl)

        bytes_freed = max(0, bytes_before - bytes_after)
        chunks_count = int(tbl.count_rows())

        return CompactionResult(
            table_name=table_name,
            chunks_count=chunks_count,
            bytes_before=bytes_before,
            bytes_after=bytes_after,
            bytes_freed=bytes_freed,
            fragments_before=fragments_before,
            fragments_after=fragments_after,
            versions_before=versions_before,
            versions_after=versions_after,
        )

    def compact_all(
        self,
        cleanup_older_than: timedelta | None = None,
        delete_unverified: bool = True,
    ) -> list[CompactionResult]:
        """Run compaction and optimization across all existing tables."""
        tables = self.table_names()
        results: list[CompactionResult] = []
        for name in tables:
            res = self.compact_table(
                table_name=name,
                cleanup_older_than=cleanup_older_than,
                delete_unverified=delete_unverified,
            )
            results.append(res)
        return results

    def get_indexed_repos(self, table_name: str = "chunks") -> list[str]:
        """Return sorted list of unique repository names present in the target table."""
        if table_name not in self.table_names():
            return []
        tbl = self._db.open_table(table_name)
        try:
            results = tbl.search().select(["repo"]).to_list()
            return sorted({str(r["repo"]) for r in results if "repo" in r and r["repo"]})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to retrieve indexed repos for table '%s': %s", table_name, exc)
            return []

    def cleanup_orphan_repos(
        self,
        active_repos: Sequence[str],
        table_name: str = "chunks",
    ) -> int:
        """Purge chunks belonging to repositories not present in active_repos list.

        Returns the number of deleted orphan chunks.
        """
        if table_name not in self.table_names():
            return 0
        if not active_repos:
            logger.warning(
                "cleanup_orphan_repos called with empty active_repos; skipping deletion."
            )
            return 0

        tbl = self._db.open_table(table_name)
        count_before = int(tbl.count_rows())

        safe_repos = list(
            dict.fromkeys(r.strip().replace("'", "''") for r in active_repos if r.strip())
        )
        if not safe_repos:
            return 0

        repo_list = ", ".join(f"'{r}'" for r in safe_repos)
        tbl.delete(f"repo NOT IN ({repo_list})")

        count_after = int(tbl.count_rows())
        deleted = max(0, count_before - count_after)
        logger.info(
            "Purged %d orphan chunk(s) from table '%s' not belonging to active repos: %s",
            deleted,
            table_name,
            safe_repos,
        )
        return deleted

    def cleanup_all_orphan_repos(self, active_repos: Sequence[str]) -> dict[str, int]:
        """Purge orphan chunks across all tables in storage database."""
        results: dict[str, int] = {}
        for name in self.table_names():
            results[name] = self.cleanup_orphan_repos(active_repos, table_name=name)
        return results
