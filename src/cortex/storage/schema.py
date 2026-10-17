"""Apache Arrow / Lance schema definitions mirroring DocumentChunk."""

from __future__ import annotations

from typing import Any

from lancedb.pydantic import LanceModel, Vector

from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    DocumentChunk,
)

# Registry to cache dynamically created model classes per dimension
_MODEL_CACHE: dict[int, type[LanceModel]] = {}


def create_chunk_record_model(dim: int) -> type[LanceModel]:
    """Dynamically generate a LanceModel schema for DocumentChunk with fixed vector dim."""
    if dim <= 0:
        msg = f"Vector dimension must be positive, got {dim}"
        raise ValueError(msg)

    if dim in _MODEL_CACHE:
        return _MODEL_CACHE[dim]

    class ChunkRecord(LanceModel):
        id: str
        repo: str
        file_path: str
        category: str
        lifecycle: str
        scope: str
        breadcrumb: str
        commit_sha: str
        tags: list[str]
        content: str
        vector: Vector(dim)  # type: ignore[valid-type]

    ChunkRecord.__name__ = f"ChunkRecord_{dim}"
    _MODEL_CACHE[dim] = ChunkRecord
    return ChunkRecord


def chunk_to_record_dict(
    chunk: DocumentChunk, default_vector: list[float] | None = None
) -> dict[str, Any]:
    """Convert a DocumentChunk to a dictionary matching the ChunkRecord schema."""
    vec = chunk.vector
    if vec is None:
        if default_vector is None:
            msg = f"Chunk '{chunk.id}' has no vector and no default_vector was supplied."
            raise ValueError(msg)
        vec = default_vector

    return {
        "id": chunk.id,
        "repo": chunk.repo,
        "file_path": chunk.file_path,
        "category": chunk.category.value,
        "lifecycle": chunk.lifecycle.value,
        "scope": chunk.scope.value,
        "breadcrumb": chunk.breadcrumb,
        "commit_sha": chunk.commit_sha,
        "tags": list(chunk.tags),
        "content": chunk.content,
        "vector": [float(x) for x in vec],
    }


def record_to_chunk(record: dict[str, Any] | LanceModel) -> DocumentChunk:
    """Convert a storage record or dictionary back to a DocumentChunk domain entity."""
    data: dict[str, Any] = record.model_dump() if isinstance(record, LanceModel) else dict(record)

    # Convert vector to list of floats if present
    raw_vec = data.get("vector")
    vector_list: list[float] | None = None
    if raw_vec is not None:
        vector_list = [float(x) for x in raw_vec]

    return DocumentChunk(
        id=str(data["id"]),
        repo=str(data["repo"]),
        file_path=str(data["file_path"]),
        category=ChunkCategory(str(data["category"])),
        lifecycle=ChunkLifecycle(str(data["lifecycle"])),
        scope=ChunkScope(str(data["scope"])),
        breadcrumb=str(data.get("breadcrumb", "")),
        commit_sha=str(data["commit_sha"]),
        tags=[str(t) for t in data.get("tags", [])],
        content=str(data["content"]),
        vector=vector_list,
    )
