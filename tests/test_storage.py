"""Unit tests for LanceDB storage manager and Apache Arrow schemas."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    DocumentChunk,
)
from cortex.storage.manager import StorageManager, validate_storage_path
from cortex.storage.schema import (
    chunk_to_record_dict,
    create_chunk_record_model,
    record_to_chunk,
)


def test_validate_storage_path_safety() -> None:
    """Ensure unsafe storage paths inside repository source trees raise ValueError."""
    with TemporaryDirectory() as tmpdir:
        # Tmp paths are always allowed
        valid_tmp = Path(tmpdir) / "test_db"
        assert validate_storage_path(valid_tmp) == valid_tmp.resolve()

    # Paths inside repo root that are not ignored must raise ValueError
    repo_root = Path.cwd().resolve()
    unsafe_path = repo_root / "src" / "cortex" / "leak_data"
    with pytest.raises(ValueError, match="Unsafe storage path"):
        validate_storage_path(unsafe_path)

    # Paths inside gitignored 'data/' are allowed
    safe_data_path = repo_root / "data" / "lancedb"
    assert validate_storage_path(safe_data_path) == safe_data_path.resolve()


def test_schema_model_generation_and_caching() -> None:
    """Ensure dynamic ChunkRecord schemas are generated and cached per dimension."""
    model_384 = create_chunk_record_model(384)
    model_384_again = create_chunk_record_model(384)
    assert model_384 is model_384_again
    assert model_384.__name__ == "ChunkRecord_384"

    model_1024 = create_chunk_record_model(1024)
    assert model_1024 is not model_384
    assert model_1024.__name__ == "ChunkRecord_1024"

    with pytest.raises(ValueError, match="Vector dimension must be positive"):
        create_chunk_record_model(0)


def test_chunk_and_record_conversion() -> None:
    """Ensure bidirectional fidelity between DocumentChunk and LanceDB record dict."""
    chunk = DocumentChunk(
        id="sentinel:specs/openapi.json:get_deals",
        repo="sentinel",
        file_path="specs/openapi.json",
        category=ChunkCategory.CONTRACT,
        lifecycle=ChunkLifecycle.ACTIVE,
        scope=ChunkScope.INTERNAL,
        breadcrumb="GET /deals",
        commit_sha="a1b2c3d4",
        tags=["deals", "openapi"],
        content="Endpoint returning list of active deals",
        vector=[0.1, 0.2, 0.3],
    )

    record_dict = chunk_to_record_dict(chunk)
    assert record_dict["id"] == chunk.id
    assert record_dict["category"] == "contract"
    assert record_dict["vector"] == [0.1, 0.2, 0.3]

    reconstructed = record_to_chunk(record_dict)
    assert reconstructed.id == chunk.id
    assert reconstructed.repo == chunk.repo
    assert reconstructed.category == chunk.category
    assert reconstructed.vector == chunk.vector

    # Without vector and no default raises ValueError
    chunk_no_vec = chunk.model_copy(update={"vector": None})
    with pytest.raises(ValueError, match="has no vector"):
        chunk_to_record_dict(chunk_no_vec)

    # With default vector succeeds
    record_with_default = chunk_to_record_dict(chunk_no_vec, default_vector=[0.0, 0.0, 0.0])
    assert record_with_default["vector"] == [0.0, 0.0, 0.0]


def test_storage_manager_crud_and_idempotency() -> None:
    """Test table creation, idempotent upsert, and queries in StorageManager."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        assert storage.table_names() == []

        chunks = [
            DocumentChunk(
                id="cortex:README.md:c0",
                repo="cortex",
                file_path="README.md",
                category=ChunkCategory.DOC,
                lifecycle=ChunkLifecycle.ACTIVE,
                scope=ChunkScope.PUBLIC,
                breadcrumb="Overview",
                commit_sha="111111",
                tags=["overview"],
                content="Agent cortex semantic memory engine",
                vector=[0.1, 0.2, 0.3, 0.4],
            ),
            DocumentChunk(
                id="sentinel:compose.yaml:c0",
                repo="sentinel",
                file_path="compose.yaml",
                category=ChunkCategory.INFRA,
                lifecycle=ChunkLifecycle.ACTIVE,
                scope=ChunkScope.INTERNAL,
                breadcrumb="services > redis",
                commit_sha="222222",
                tags=["redis", "cache"],
                content="Redis cache service container definition",
                vector=[0.4, 0.3, 0.2, 0.1],
            ),
        ]

        count = storage.upsert_chunks(chunks)
        assert count == 2
        assert storage.count_chunks() == 2

        # Test idempotent upsert (update existing chunk)
        updated_chunk = chunks[0].model_copy(
            update={"content": "Agent cortex semantic memory updated"}
        )
        storage.upsert_chunks([updated_chunk])
        assert storage.count_chunks() == 2

        # Verify vector search
        vec_hits = storage.vector_search([0.1, 0.2, 0.3, 0.4], limit=2)
        assert len(vec_hits) == 2
        assert vec_hits[0]["id"] == "cortex:README.md:c0"
        assert vec_hits[0]["content"] == "Agent cortex semantic memory updated"

        # Verify FTS search
        fts_hits = storage.fts_search("redis", limit=2)
        assert len(fts_hits) >= 1
        assert any(h["id"] == "sentinel:compose.yaml:c0" for h in fts_hits)

        # Test delete by ID
        storage.delete_by_id("cortex:README.md:c0")
        assert storage.count_chunks() == 1

        # Test delete by repo
        storage.delete_by_repo("sentinel")
        assert storage.count_chunks() == 0


def test_storage_manager_delete_by_file() -> None:
    """Test targeted deletion by file path within a repository."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        chunks = [
            DocumentChunk(
                id="repo1:doc1.md:c0",
                repo="repo1",
                file_path="doc1.md",
                category=ChunkCategory.DOC,
                commit_sha="aaa",
                content="doc 1 content",
                vector=[0.1, 0.1],
            ),
            DocumentChunk(
                id="repo1:doc2.md:c0",
                repo="repo1",
                file_path="doc2.md",
                category=ChunkCategory.DOC,
                commit_sha="bbb",
                content="doc 2 content",
                vector=[0.2, 0.2],
            ),
        ]
        storage.upsert_chunks(chunks, dim=2)
        assert storage.count_chunks() == 2

        storage.delete_by_file("repo1", "doc1.md")
        assert storage.count_chunks() == 1
        remaining = storage.vector_search([0.1, 0.1], limit=5)
        assert remaining[0]["id"] == "repo1:doc2.md:c0"


def test_storage_manager_fts_and_vector_indexing() -> None:
    """Test explicit create_fts_index and create_vector_index methods."""
    with TemporaryDirectory() as tmpdir:
        storage = StorageManager(data_dir=tmpdir)
        # Nonexistent table returns False
        assert not storage.create_fts_index("nonexistent")
        assert not storage.create_vector_index("nonexistent")

        # Upsert with create_fts=False
        words = ["apple", "banana", "cherry", "durian", "elderberry"]
        chunks = [
            DocumentChunk(
                id=f"repo:doc.md:c{i}",
                repo="repo",
                file_path="doc.md",
                category=ChunkCategory.DOC,
                commit_sha="abc",
                content=f"indexing payload keyword {words[i]}",
                vector=[0.1 * i, 0.2 * i],
            )
            for i in range(5)
        ]
        storage.upsert_chunks(chunks, dim=2, create_fts=False)
        assert storage.count_chunks() == 5

        # Create FTS index explicitly
        created = storage.create_fts_index()
        assert created is True

        hits = storage.fts_search("durian")
        assert len(hits) == 1
        assert hits[0]["id"] == "repo:doc.md:c3"

        # Vector index threshold (5 rows < 256 default)
        skipped = storage.create_vector_index()
        assert skipped is False
