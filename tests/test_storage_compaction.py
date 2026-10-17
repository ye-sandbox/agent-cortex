"""Tests for LanceDB storage compaction, optimization, and orphan cleanup."""

from datetime import timedelta
from tempfile import TemporaryDirectory

import pytest

from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    DocumentChunk,
)
from cortex.storage.manager import CompactionResult, StorageManager


def _make_dummy_chunks(repo: str, count: int, dim: int = 4) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for i in range(count):
        chunks.append(
            DocumentChunk(
                id=f"{repo}:file_{i}.py:c0",
                repo=repo,
                file_path=f"file_{i}.py",
                category=ChunkCategory.DOC,
                lifecycle=ChunkLifecycle.ACTIVE,
                scope=ChunkScope.INTERNAL,
                breadcrumb=f"Section {i}",
                commit_sha="abcdef12",
                tags=["test", repo],
                content=f"Content for chunk {i} in {repo}",
                vector=[0.1 * ((i + j) % 10) for j in range(dim)],
            )
        )
    return chunks


def test_compact_table_success() -> None:
    """Ensure compact_table optimizes files and returns CompactionResult."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        chunks = _make_dummy_chunks("repo-a", 10, dim=4)
        storage.upsert_chunks(chunks, table_name="chunks", dim=4)

        result = storage.compact_table(table_name="chunks")

        assert isinstance(result, CompactionResult)
        assert result.table_name == "chunks"
        assert result.chunks_count == 10
        assert result.bytes_before >= 0
        assert result.bytes_after >= 0
        assert result.bytes_freed >= 0


def test_compact_table_nonexistent_raises() -> None:
    """Ensure compact_table on missing table raises ValueError."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        with pytest.raises(ValueError, match="does not exist"):
            storage.compact_table(table_name="nonexistent")


def test_compact_table_prune_older_than() -> None:
    """Ensure compact_table accepts explicit cleanup_older_than and delete_unverified."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        chunks = _make_dummy_chunks("repo-b", 5, dim=4)
        storage.upsert_chunks(chunks, table_name="chunks", dim=4)

        result = storage.compact_table(
            table_name="chunks",
            cleanup_older_than=timedelta(days=0),
            delete_unverified=True,
        )
        assert result.chunks_count == 5


def test_compact_all_tables() -> None:
    """Ensure compact_all optimizes all tables in the database."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        chunks1 = _make_dummy_chunks("repo-1", 4, dim=4)
        chunks2 = _make_dummy_chunks("repo-2", 6, dim=4)
        storage.upsert_chunks(chunks1, table_name="t1", dim=4)
        storage.upsert_chunks(chunks2, table_name="t2", dim=4)

        results = storage.compact_all()
        assert len(results) == 2
        table_names = {r.table_name for r in results}
        assert table_names == {"t1", "t2"}
        counts = {r.table_name: r.chunks_count for r in results}
        assert counts["t1"] == 4
        assert counts["t2"] == 6


def test_cleanup_orphan_repos() -> None:
    """Ensure cleanup_orphan_repos purges chunks from unregistered repositories."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        chunks_a = _make_dummy_chunks("active-repo", 5, dim=4)
        chunks_b = _make_dummy_chunks("orphan-repo", 3, dim=4)
        storage.upsert_chunks(chunks_a + chunks_b, table_name="chunks", dim=4)

        assert storage.count_chunks() == 8

        # Purge chunks not in active-repo
        deleted = storage.cleanup_orphan_repos(["active-repo"], table_name="chunks")
        assert deleted == 3
        assert storage.count_chunks() == 5

        # Calling again should delete 0
        deleted_again = storage.cleanup_orphan_repos(["active-repo"], table_name="chunks")
        assert deleted_again == 0


def test_cleanup_orphan_repos_edge_cases() -> None:
    """Ensure edge cases (empty list, missing table) are handled safely."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        # Missing table returns 0
        assert storage.cleanup_orphan_repos(["repo-a"], table_name="missing") == 0

        # Empty active_repos returns 0 and does not delete
        chunks = _make_dummy_chunks("repo-a", 2, dim=4)
        storage.upsert_chunks(chunks, table_name="chunks", dim=4)
        assert storage.cleanup_orphan_repos([], table_name="chunks") == 0
        assert storage.count_chunks() == 2
