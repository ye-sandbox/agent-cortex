"""Cross-language code signature and dependency graph domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DependencyEdgeType(StrEnum):
    """Directional relationship between code artifacts."""

    IMPORT = "IMPORT"
    CALL = "CALL"
    EXTENDS = "EXTENDS"
    IMPLEMENTS = "IMPLEMENTS"


class CodeSignature(BaseModel):
    """AST-extracted code contract with typed signature and metadata."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    id: str = Field(
        ...,
        description="Deterministic unique ID matching {repo}:{file_path}:{kind}:{identifier}",
    )
    repo: str = Field(..., description="Repository identifier")
    file_path: str = Field(..., description="Relative file path within repository")
    language: str = Field(..., description="Programming language ('python', 'typescript', 'go')")
    kind: str = Field(
        ...,
        description="AST symbol kind ('function', 'method', 'class', 'interface', 'struct', etc.)",
    )
    identifier: str = Field(..., description="Unique symbol identifier or qualified name")
    signature: str = Field(..., description="Exact typed declaration string")
    docstring: str = Field(default="", description="Normalized docstring or leading comments")
    line_start: int = Field(..., ge=1, description="1-based start line")
    line_end: int = Field(..., ge=1, description="1-based end line")
    exported: bool = Field(default=True, description="Whether symbol is exported/public")
    calls: list[str] = Field(
        default_factory=list,
        description="Outgoing symbol identifiers called within this signature body",
    )

    @classmethod
    def build_id(cls, repo: str, file_path: str, kind: str, identifier: str) -> str:
        """Construct deterministic code signature ID."""
        cleaned_repo = repo.strip()
        cleaned_path = file_path.strip().lstrip("/")
        cleaned_kind = kind.strip().lower()
        cleaned_id = identifier.strip()
        return f"{cleaned_repo}:{cleaned_path}:{cleaned_kind}:{cleaned_id}"

    @model_validator(mode="after")
    def validate_id_consistency(self) -> Self:
        """Ensure ID format consistency with repo and file_path."""
        prefix = f"{self.repo}:{self.file_path}:"
        if not self.id.startswith(prefix):
            msg = f"Signature ID '{self.id}' does not start with expected prefix '{prefix}'"
            raise ValueError(msg)
        return self


class CodeDependency(BaseModel):
    """Directional dependency edge between code artifacts."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    id: str = Field(
        ...,
        description=(
            "Deterministic ID matching "
            "{source_repo}:{source_file}:{edge_type}:{target_module}:{target_symbol}:{line_number}"
        ),
    )
    source_repo: str = Field(..., description="Source repository identifier")
    source_file: str = Field(..., description="Relative source file path")
    source_symbol: str = Field(
        default="",
        description="Containing symbol or function scope in source file",
    )
    edge_type: DependencyEdgeType = Field(..., description="Edge relation type")
    target_module: str = Field(
        ...,
        description="Target imported module, package, or namespace",
    )
    target_symbol: str = Field(
        default="",
        description="Specific target symbol imported or called",
    )
    target_repo: str | None = Field(
        default=None,
        description="Resolved target portfolio repository name, if matched",
    )
    line_number: int = Field(default=1, ge=1, description="Source line number")
    raw_statement: str = Field(
        default="",
        description="Raw verbatim source statement",
    )

    @classmethod
    def build_id(
        cls,
        source_repo: str,
        source_file: str,
        edge_type: DependencyEdgeType | str,
        target_module: str,
        target_symbol: str,
        line_number: int,
    ) -> str:
        """Construct deterministic code dependency edge ID."""
        c_repo = source_repo.strip()
        c_file = source_file.strip().lstrip("/")
        c_edge = (
            edge_type.value if isinstance(edge_type, DependencyEdgeType) else str(edge_type).upper()
        )
        c_mod = target_module.strip()
        c_sym = target_symbol.strip()
        return f"{c_repo}:{c_file}:{c_edge}:{c_mod}:{c_sym}:{line_number}"

    @model_validator(mode="after")
    def validate_id_consistency(self) -> Self:
        """Ensure ID format consistency with source_repo and source_file."""
        prefix = f"{self.source_repo}:{self.source_file}:"
        if not self.id.startswith(prefix):
            msg = f"Dependency ID '{self.id}' does not start with expected prefix '{prefix}'"
            raise ValueError(msg)
        return self


class CrossRepoLink(BaseModel):
    """Resolved architectural bridge between two portfolio repositories."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    source_repo: str
    source_file: str
    target_repo: str
    edge_type: DependencyEdgeType
    symbol: str
    detail: str = ""


class DependencyQueryResult(BaseModel):
    """Response payload for outgoing dependency queries."""

    model_config = ConfigDict(frozen=True)

    repo: str
    file_path: str | None = None
    symbol: str | None = None
    total_dependencies: int
    dependencies: list[CodeDependency]
    cross_repo_links: list[CrossRepoLink] = Field(default_factory=list)


class DependentsQueryResult(BaseModel):
    """Response payload for incoming caller/dependent queries."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    module: str | None = None
    total_dependents: int
    dependents: list[CodeDependency]
    cross_repo_links: list[CrossRepoLink] = Field(default_factory=list)


class SignaturesQueryResult(BaseModel):
    """Response payload for code signature queries."""

    model_config = ConfigDict(frozen=True)

    query: str
    total_signatures: int
    signatures: list[CodeSignature]
