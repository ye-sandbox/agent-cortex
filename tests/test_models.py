"""Unit tests for DocumentChunk, HardwareProfile, and related schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cortex.models import (
    PREDEFINED_PROFILES,
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    DocumentChunk,
    HardwareProfile,
    HardwareProfileName,
    SearchResultChunk,
    resolve_hardware_profile,
)


def test_chunk_category_enum_values() -> None:
    """Verifies that all required categories exist."""
    assert set(c.value for c in ChunkCategory) == {
        "doc",
        "contract",
        "infra",
        "invariant",
        "solution",
    }


def test_chunk_lifecycle_and_scope_enums() -> None:
    """Verifies lifecycle and scope enum invariants."""
    assert set(item.value for item in ChunkLifecycle) == {"active", "archived", "deprecated"}
    assert set(s.value for s in ChunkScope) == {"internal", "public", "confidential"}


def test_document_chunk_build_id() -> None:
    """Verifies canonical chunk ID generation."""
    chunk_id = DocumentChunk.build_id(
        repo="sentinel",
        file_path="specs/openapi.json",
        chunk_index_or_hash="get_deals",
    )
    assert chunk_id == "sentinel:specs/openapi.json:get_deals"


def test_document_chunk_creation_and_anchor() -> None:
    """Verifies valid chunk creation and anchor formatting."""
    chunk_id = DocumentChunk.build_id("agent-cortex", ".agent/ECOSYSTEM.md", "c2")
    chunk = DocumentChunk(
        id=chunk_id,
        repo="agent-cortex",
        file_path=".agent/ECOSYSTEM.md",
        category=ChunkCategory.DOC,
        lifecycle=ChunkLifecycle.ACTIVE,
        scope=ChunkScope.INTERNAL,
        breadcrumb="Topology > Matrix",
        commit_sha="a1b2c3d4",
        tags=["architecture", "ecosystem"],
        content="Cross-repo semantic memory",
    )

    assert chunk.id == "agent-cortex:.agent/ECOSYSTEM.md:c2"
    assert chunk.format_anchor() == "[agent-cortex] .agent/ECOSYSTEM.md > Topology > Matrix"
    assert chunk.tags == ["architecture", "ecosystem"]


def test_document_chunk_format_anchor_without_breadcrumb() -> None:
    """Verifies anchor formatting when breadcrumb is empty."""
    chunk = DocumentChunk(
        id="repo:path/to/file.md:0",
        repo="repo",
        file_path="path/to/file.md",
        category=ChunkCategory.DOC,
        commit_sha="123456",
        content="Hello world",
    )
    assert chunk.format_anchor() == "[repo] path/to/file.md"


def test_document_chunk_id_validation_format_failure() -> None:
    """Verifies that invalid ID formats raise ValidationError."""
    with pytest.raises(ValidationError, match="Invalid chunk ID"):
        DocumentChunk(
            id="invalid_id_without_colons",
            repo="repo",
            file_path="file.md",
            category=ChunkCategory.DOC,
            commit_sha="123456",
            content="content",
        )


def test_document_chunk_id_inconsistency_failure() -> None:
    """Verifies that mismatch between ID prefix and repo/file_path raises ValidationError."""
    with pytest.raises(ValidationError, match="Chunk ID 'other:file.md:1' does not match"):
        DocumentChunk(
            id="other:file.md:1",
            repo="my-repo",
            file_path="file.md",
            category=ChunkCategory.DOC,
            commit_sha="123456",
            content="content",
        )


def test_document_chunk_immutability() -> None:
    """Verifies that DocumentChunk is frozen and cannot be mutated."""
    chunk = DocumentChunk(
        id="repo:file.md:0",
        repo="repo",
        file_path="file.md",
        category=ChunkCategory.DOC,
        commit_sha="123456",
        content="content",
    )
    with pytest.raises(ValidationError):
        chunk.content = "new content"


def test_search_result_chunk() -> None:
    """Verifies SearchResultChunk schema and anchor output."""
    result = SearchResultChunk(
        id="repo:specs/openapi.json:post_item",
        repo="repo",
        file_path="specs/openapi.json",
        category=ChunkCategory.CONTRACT,
        lifecycle=ChunkLifecycle.ACTIVE,
        scope=ChunkScope.INTERNAL,
        breadcrumb="POST /items",
        score=0.92,
        content="Create item spec",
        snippet="POST /items creates a new resource",
        tags=["items", "create"],
    )
    assert result.score == 0.92
    assert result.format_anchor() == "[repo] specs/openapi.json > POST /items"


def test_predefined_hardware_profiles() -> None:
    """Verifies predefined profile attributes match architectural specifications."""
    high = PREDEFINED_PROFILES[HardwareProfileName.HIGH]
    assert high.embedding_model == "BAAI/bge-large-en-v1.5"
    assert high.embedding_dim == 1024
    assert high.reranker_model == "BAAI/bge-reranker-large"
    assert high.reranker_enabled is True
    assert high.top_k_rerank == 30

    balanced = PREDEFINED_PROFILES[HardwareProfileName.BALANCED]
    assert balanced.embedding_model == "BAAI/bge-small-en-v1.5"
    assert balanced.embedding_dim == 384
    assert balanced.reranker_model == "BAAI/bge-reranker-base"
    assert balanced.reranker_enabled is True
    assert balanced.top_k_rerank == 20

    low = PREDEFINED_PROFILES[HardwareProfileName.LOW]
    assert low.embedding_model == "BAAI/bge-small-en-v1.5"
    assert low.embedding_dim == 384
    assert low.reranker_model is None
    assert low.reranker_enabled is False
    assert low.top_k_rerank == 0

    code = PREDEFINED_PROFILES[HardwareProfileName.CODE]
    assert code.embedding_model == "jinaai/jina-embeddings-v2-base-code"
    assert code.embedding_dim == 768
    assert code.reranker_model == "jinaai/jina-reranker-v1-turbo-en"
    assert code.reranker_enabled is True
    assert code.top_k_rerank == 25
    assert code.max_threads == 4


def test_resolve_hardware_profile() -> None:
    """Verifies profile resolution by name and case insensitivity."""
    prof = resolve_hardware_profile("balanced")
    assert prof.name == "balanced"

    prof_high = resolve_hardware_profile("HIGH")
    assert prof_high.name == "high"

    prof_low = resolve_hardware_profile(HardwareProfileName.LOW)
    assert prof_low.name == "low"

    prof_code = resolve_hardware_profile("code")
    assert prof_code.name == "code"
    assert prof_code.embedding_dim == 768


def test_resolve_hardware_profile_custom() -> None:
    """Verifies custom profile handling."""
    custom_profile = HardwareProfile(
        name="my-custom",
        embedding_model="custom/model",
        embedding_dim=512,
        reranker_model="custom/reranker",
        reranker_enabled=True,
        top_k_rerank=15,
        max_threads=8,
    )
    resolved = resolve_hardware_profile("custom", custom=custom_profile)
    assert resolved.name == "my-custom"
    assert resolved.embedding_dim == 512

    with pytest.raises(ValueError, match="no custom profile definition was provided"):
        resolve_hardware_profile("custom", custom=None)


def test_resolve_hardware_profile_invalid() -> None:
    """Verifies that unknown profile names raise ValueError."""
    with pytest.raises(ValueError, match="Unknown hardware profile 'super_ultra'"):
        resolve_hardware_profile("super_ultra")


def test_hardware_profile_validation_invalid_reranker() -> None:
    """Verifies validation when reranker_enabled is True but reranker_model is None."""
    with pytest.raises(ValidationError, match="reranker_model must be specified"):
        HardwareProfile(
            name="broken",
            embedding_model="some/model",
            embedding_dim=384,
            reranker_model=None,
            reranker_enabled=True,
        )
