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
from cortex.models.graph import (
    CodeDependency,
    CodeSignature,
    DependencyEdgeType,
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


class CodeSignatureRecord(LanceModel):
    """LanceDB storage schema for CodeSignature records."""

    id: str
    repo: str
    file_path: str
    language: str
    kind: str
    identifier: str
    signature: str
    docstring: str
    line_start: int
    line_end: int
    exported: bool
    calls: list[str]


def signature_to_record_dict(sig: CodeSignature) -> dict[str, Any]:
    """Convert CodeSignature to record dictionary for LanceDB."""
    return {
        "id": sig.id,
        "repo": sig.repo,
        "file_path": sig.file_path,
        "language": sig.language,
        "kind": sig.kind,
        "identifier": sig.identifier,
        "signature": sig.signature,
        "docstring": sig.docstring,
        "line_start": sig.line_start,
        "line_end": sig.line_end,
        "exported": sig.exported,
        "calls": list(sig.calls),
    }


def record_to_signature(record: dict[str, Any] | LanceModel) -> CodeSignature:
    """Convert storage record back to CodeSignature domain entity."""
    data: dict[str, Any] = record.model_dump() if isinstance(record, LanceModel) else dict(record)
    return CodeSignature(
        id=str(data["id"]),
        repo=str(data["repo"]),
        file_path=str(data["file_path"]),
        language=str(data["language"]),
        kind=str(data["kind"]),
        identifier=str(data["identifier"]),
        signature=str(data["signature"]),
        docstring=str(data.get("docstring", "")),
        line_start=int(data["line_start"]),
        line_end=int(data["line_end"]),
        exported=bool(data.get("exported", True)),
        calls=[str(c) for c in data.get("calls", [])],
    )


class CodeDependencyRecord(LanceModel):
    """LanceDB storage schema for CodeDependency edges."""

    id: str
    source_repo: str
    source_file: str
    source_symbol: str
    edge_type: str
    target_module: str
    target_symbol: str
    target_repo: str
    line_number: int
    raw_statement: str


def dependency_to_record_dict(dep: CodeDependency) -> dict[str, Any]:
    """Convert CodeDependency to record dictionary for LanceDB."""
    return {
        "id": dep.id,
        "source_repo": dep.source_repo,
        "source_file": dep.source_file,
        "source_symbol": dep.source_symbol,
        "edge_type": dep.edge_type.value,
        "target_module": dep.target_module,
        "target_symbol": dep.target_symbol,
        "target_repo": dep.target_repo or "",
        "line_number": dep.line_number,
        "raw_statement": dep.raw_statement,
    }


def record_to_dependency(record: dict[str, Any] | LanceModel) -> CodeDependency:
    """Convert storage record back to CodeDependency domain entity."""
    data: dict[str, Any] = record.model_dump() if isinstance(record, LanceModel) else dict(record)
    target_repo_val = data.get("target_repo")
    target_repo = str(target_repo_val) if target_repo_val else None
    return CodeDependency(
        id=str(data["id"]),
        source_repo=str(data["source_repo"]),
        source_file=str(data["source_file"]),
        source_symbol=str(data.get("source_symbol", "")),
        edge_type=DependencyEdgeType(str(data["edge_type"])),
        target_module=str(data["target_module"]),
        target_symbol=str(data.get("target_symbol", "")),
        target_repo=target_repo,
        line_number=int(data.get("line_number", 1)),
        raw_statement=str(data.get("raw_statement", "")),
    )
