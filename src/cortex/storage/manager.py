"""Safe, in-process LanceDB storage manager for agent-cortex."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import lancedb
from lancedb.db import DBConnection
from lancedb.index import FTS
from lancedb.table import Table

from cortex.models.chunk import DocumentChunk
from cortex.storage.schema import (
    chunk_to_record_dict,
    create_chunk_record_model,
)

logger = logging.getLogger(__name__)


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
            try:
                tbl.create_index("content", config=FTS(), replace=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("FTS index creation deferred or failed: %s", exc)

        return len(chunks)

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
