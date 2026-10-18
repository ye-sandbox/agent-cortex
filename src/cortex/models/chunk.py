"""Document chunk schemas and contract invariants for agent-cortex."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Self

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


class CompactSearchResult(BaseModel):
    """Token-dense semantic search result item for AI agent consumption."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    anchor: str = Field(..., description="Compact markdown anchor: [repo] path > breadcrumb")
    repo: str = Field(..., description="Repository name")
    file_path: str = Field(..., description="Relative file path")
    category: str = Field(
        ...,
        description="Semantic category (doc, contract, infra, invariant, solution)",
    )
    scope: str = Field(..., description="Access scope (internal, public, confidential)")
    score: float = Field(..., description="Fused relevance score")
    snippet: str = Field(..., description="Concise text snippet")
    tags: list[str] = Field(default_factory=list, description="Associated technology tags")
    content: str = Field(..., description="Full chunk content")


class RepoContractChunk(BaseModel):
    """Targeted contract or architectural invariant definition for a repository."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    anchor: str = Field(..., description="Compact markdown anchor")
    repo: str = Field(..., description="Repository name")
    file_path: str = Field(..., description="Contract or manifest file path")
    category: str = Field(..., description="Semantic category (contract, infra, invariant)")
    breadcrumb: str = Field(..., description="Operation or service hierarchy")
    tags: list[str] = Field(default_factory=list, description="Technology and endpoint tags")
    content: str = Field(..., description="Contract or service definition content")


class TechUsage(BaseModel):
    """Aggregate usage metadata for a technology across repositories."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    technology: str = Field(..., description="Normalized technology tag or framework name")
    repositories: list[str] = Field(
        default_factory=list,
        description="Repositories utilizing this technology",
    )
    chunk_count: int = Field(
        ...,
        description="Total occurrences or references in indexed portfolio",
    )


class TechSummary(BaseModel):
    """Portfolio technology discovery summary."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    total_technologies: int = Field(..., description="Total unique technologies identified")
    technologies: list[TechUsage] = Field(
        default_factory=list,
        description="List of technologies with repo mappings",
    )


def resolve_contract_categories(contract_type: str | None) -> list[str]:
    """Normalize a user-provided contract_type string into storage category values."""
    if not contract_type:
        return ["contract", "infra", "invariant"]
    ct = contract_type.strip().lower()
    if ct in ("openapi", "api", "contract"):
        return ["contract"]
    if ct in ("compose", "docker", "infra"):
        return ["infra"]
    if ct in ("invariant", "rule", "invariants"):
        return ["invariant"]
    if ct == "all":
        return ["contract", "infra", "invariant"]
    return [ct]


def format_contract_chunks(
    repo: str,
    records: Sequence[dict[str, Any]],
) -> list[RepoContractChunk]:
    """Convert raw LanceDB contract records into typed RepoContractChunk models."""
    cleaned_repo = repo.strip()
    results: list[RepoContractChunk] = []
    for rec in records:
        file_path = str(rec.get("file_path", ""))
        breadcrumb = str(rec.get("breadcrumb", ""))
        anchor = (
            f"[{cleaned_repo}] {file_path} > {breadcrumb}"
            if breadcrumb
            else f"[{cleaned_repo}] {file_path}"
        )
        raw_tags = rec.get("tags")
        tags = (
            [str(t) for t in raw_tags]
            if isinstance(raw_tags, Sequence) and not isinstance(raw_tags, (str, bytes))
            else []
        )
        results.append(
            RepoContractChunk(
                anchor=anchor,
                repo=cleaned_repo,
                file_path=file_path,
                category=str(rec.get("category", "contract")),
                breadcrumb=breadcrumb,
                tags=tags,
                content=str(rec.get("content", "")),
            )
        )
    return results


def aggregate_tech_summary(
    records: Sequence[dict[str, Any]],
    tech_name: str | None = None,
) -> TechSummary:
    """Aggregate technology tags and repository associations from raw LanceDB records."""
    repo_map: dict[str, set[str]] = defaultdict(set)
    count_map: dict[str, int] = defaultdict(int)

    filter_tech = tech_name.strip().lower() if tech_name and tech_name.strip() else None

    for rec in records:
        r_repo = str(rec.get("repo", "")).strip()
        raw_tags = rec.get("tags")
        if not isinstance(raw_tags, Sequence) or isinstance(raw_tags, (str, bytes)):
            continue

        for tag in raw_tags:
            clean_tag = str(tag).strip()
            if not clean_tag:
                continue

            if filter_tech and filter_tech not in clean_tag.lower():
                continue

            repo_map[clean_tag].add(r_repo)
            count_map[clean_tag] += 1

    sorted_keys = sorted(count_map.keys(), key=lambda k: (-count_map[k], k.lower()))
    tech_items = [
        TechUsage(
            technology=t,
            repositories=sorted(repo_map[t]),
            chunk_count=count_map[t],
        )
        for t in sorted_keys
    ]

    return TechSummary(
        total_technologies=len(tech_items),
        technologies=tech_items,
    )
