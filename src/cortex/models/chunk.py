"""Document chunk schemas and contract invariants for agent-cortex."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ChunkCategory(StrEnum):
    """Semantic category for an indexed chunk."""

    DOC = "doc"
    CONTRACT = "contract"
    INFRA = "infra"
    INVARIANT = "invariant"
    SOLUTION = "solution"


class ChunkLifecycle(StrEnum):
    """Lifecycle state of an indexed chunk or repository artifact."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


class ChunkScope(StrEnum):
    """Data boundary and privacy isolation scope."""

    INTERNAL = "internal"
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class DocumentChunk(BaseModel):
    """Deterministic, immutable unit of indexed semantic knowledge."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    id: str = Field(
        ...,
        description="Deterministic unique ID matching {repo}:{file_path}:{chunk_index_or_hash}",
    )
    repo: str = Field(..., description="Repository identifier (e.g. 'agent-cortex')")
    file_path: str = Field(..., description="Relative file path within target repository")
    category: ChunkCategory = Field(..., description="Semantic category")
    lifecycle: ChunkLifecycle = Field(
        default=ChunkLifecycle.ACTIVE,
        description="Lifecycle state (active, archived, deprecated)",
    )
    scope: ChunkScope = Field(
        default=ChunkScope.INTERNAL,
        description="Access and confidentiality scope",
    )
    breadcrumb: str = Field(
        default="",
        description="Structural hierarchy (e.g. 'sentinel > specs/openapi.json > GET /deals')",
    )
    commit_sha: str = Field(..., description="Git commit hash at time of indexation")
    tags: list[str] = Field(
        default_factory=list,
        description="Extracted keywords and technology identifiers",
    )
    content: str = Field(..., description="Chunk content text")
    vector: list[float] | None = Field(
        default=None,
        description="Dense embedding vector representation",
    )

    @classmethod
    def build_id(cls, repo: str, file_path: str, chunk_index_or_hash: str) -> str:
        """Construct a canonical deterministic chunk ID."""
        cleaned_repo = repo.strip()
        cleaned_path = file_path.strip().lstrip("/")
        cleaned_chunk = chunk_index_or_hash.strip()
        return f"{cleaned_repo}:{cleaned_path}:{cleaned_chunk}"

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, value: str) -> str:
        """Enforce chunk ID schema: {repo}:{file_path}:{chunk_index_or_hash}."""
        parts = value.split(":")
        if len(parts) < 3 or not all(parts):
            msg = (
                f"Invalid chunk ID '{value}'. "
                "Must follow '{repo}:{file_path}:{chunk_index_or_hash}'"
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_id_consistency(self) -> Self:
        """Ensure chunk ID aligns with repo and file_path fields."""
        prefix = f"{self.repo}:{self.file_path}:"
        if not self.id.startswith(prefix):
            msg = (
                f"Chunk ID '{self.id}' does not match expected prefix '{prefix}' "
                f"(repo='{self.repo}', file_path='{self.file_path}')"
            )
            raise ValueError(msg)
        return self

    def format_anchor(self) -> str:
        """Format token-dense markdown anchor for AI agent consumption."""
        if self.breadcrumb:
            return f"[{self.repo}] {self.file_path} > {self.breadcrumb}"
        return f"[{self.repo}] {self.file_path}"


class SearchResultChunk(BaseModel):
    """Ranked search result item returned to human or agent interfaces."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    id: str = Field(..., description="Deterministic chunk ID")
    repo: str = Field(..., description="Repository identifier")
    file_path: str = Field(..., description="Relative file path within repository")
    category: ChunkCategory = Field(..., description="Semantic category")
    lifecycle: ChunkLifecycle = Field(..., description="Lifecycle status")
    scope: ChunkScope = Field(..., description="Confidentiality scope")
    breadcrumb: str = Field(default="", description="Structural hierarchy")
    score: float = Field(..., description="Relevance score (fused RRF or reranked)")
    content: str = Field(..., description="Full or snippet chunk text")
    snippet: str | None = Field(default=None, description="Concise snippet for LLM prompts")
    tags: list[str] = Field(default_factory=list, description="Associated tags")

    def format_anchor(self) -> str:
        """Format token-dense markdown anchor for AI agent consumption."""
        if self.breadcrumb:
            return f"[{self.repo}] {self.file_path} > {self.breadcrumb}"
        return f"[{self.repo}] {self.file_path}"
