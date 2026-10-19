"""Multi-repo portfolio topology and dependency matrix domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cortex.models.graph import CrossRepoLink


class TopologyExportFormat(StrEnum):
    """Supported graph serialization formats."""

    MERMAID = "mermaid"
    DOT = "dot"
    CYTOSCAPE = "cytoscape"
    JSON = "json"


class PortfolioRepoNode(BaseModel):
    """Repository node in the portfolio topology graph."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str = Field(..., description="Repository identifier")
    languages: list[str] = Field(default_factory=list, description="Primary detected languages")
    technologies: list[str] = Field(
        default_factory=list,
        description="Detected technologies and frameworks",
    )
    total_signatures: int = Field(default=0, ge=0, description="Total AST signatures indexed")
    total_contracts: int = Field(default=0, ge=0, description="Total architectural contracts")
    afferent_coupling: int = Field(
        default=0,
        ge=0,
        description="Incoming dependencies from other portfolio repositories (Ca)",
    )
    efferent_coupling: int = Field(
        default=0,
        ge=0,
        description="Outgoing dependencies to other portfolio repositories (Ce)",
    )
    instability: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Architectural instability index: Ce / (Ca + Ce)",
    )
    is_leaf: bool = Field(
        default=False,
        description="True if repository has zero outgoing dependencies (Ce == 0)",
    )
    is_root: bool = Field(
        default=False,
        description="True if repository has zero incoming dependencies (Ca == 0)",
    )


class PortfolioDependencyEdge(BaseModel):
    """Directional dependency edge between two portfolio repositories."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    source_repo: str = Field(..., description="Source (caller/consumer) repository")
    target_repo: str = Field(..., description="Target (provider/callee) repository")
    weight: int = Field(default=1, ge=1, description="Total number of cross-repo references")
    edge_types: dict[str, int] = Field(
        default_factory=dict,
        description="Breakdown of reference types (IMPORT, CALL, etc.)",
    )
    symbols: list[str] = Field(
        default_factory=list,
        description="Distinct referenced symbols or module paths",
    )
    bridges: list[CrossRepoLink] = Field(
        default_factory=list,
        description="Individual cross-repository bridge details",
    )


class DependencyCycle(BaseModel):
    """Detected circular dependency path across portfolio repositories."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    path: list[str] = Field(..., min_length=2, description="Cycle path: [A, B, C, A]")
    length: int = Field(..., ge=2, description="Number of distinct hops in the cycle")


class PortfolioTopologyGraph(BaseModel):
    """Comprehensive portfolio dependency topology graph."""

    model_config = ConfigDict(frozen=True)

    nodes: list[PortfolioRepoNode] = Field(
        default_factory=list,
        description="Repository nodes with coupling metrics",
    )
    edges: list[PortfolioDependencyEdge] = Field(
        default_factory=list,
        description="Cross-repository dependency edges",
    )
    cycles: list[DependencyCycle] = Field(
        default_factory=list,
        description="Detected circular dependency paths",
    )
    total_repos: int = Field(default=0, ge=0)
    total_cross_repo_edges: int = Field(default=0, ge=0)
    total_cross_repo_references: int = Field(default=0, ge=0)
    density: float = Field(default=0.0, ge=0.0, description="Directed graph density")


class PortfolioMatrixRow(BaseModel):
    """Single row in the portfolio dependency matrix."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    source_repo: str = Field(..., description="Source repository name")
    targets: dict[str, int] = Field(
        default_factory=dict,
        description="Mapping from target repository name to reference count",
    )
    afferent_coupling: int = Field(default=0, ge=0, description="Incoming dependencies (Ca)")
    efferent_coupling: int = Field(default=0, ge=0, description="Outgoing dependencies (Ce)")
    instability: float = Field(default=0.0, ge=0.0, le=1.0, description="Instability index")


class PortfolioDependencyMatrix(BaseModel):
    """NxN cross-repository dependency matrix representation."""

    model_config = ConfigDict(frozen=True)

    repos: list[str] = Field(
        default_factory=list,
        description="Ordered list of portfolio repository names",
    )
    rows: list[PortfolioMatrixRow] = Field(
        default_factory=list,
        description="Matrix rows matching repo order",
    )
    cycles: list[DependencyCycle] = Field(
        default_factory=list,
        description="Detected circular dependencies",
    )
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description="High-level matrix aggregate metrics",
    )
