"""Cross-repository transitive blast-radius simulation and impact tracing domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cortex.models.graph import DependencyEdgeType


class BlastRadiusSeverity(StrEnum):
    """Categorized severity level of blast radius risk."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    MINIMAL = "MINIMAL"

    @property
    def is_breaking(self) -> bool:
        """Whether severity represents a breaking or high-risk impact."""
        return self in (BlastRadiusSeverity.CRITICAL, BlastRadiusSeverity.HIGH)


class CallerChainHop(BaseModel):
    """Single step / hop along an incoming transitive caller chain."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str = Field(..., description="Repository containing caller")
    file_path: str = Field(..., description="Relative file path containing caller")
    symbol: str = Field(..., description="Calling symbol or function scope")
    line_number: int = Field(default=1, ge=1, description="Line number of call site")
    edge_type: DependencyEdgeType = Field(
        default=DependencyEdgeType.CALL,
        description="Dependency relationship type",
    )
    depth: int = Field(default=1, ge=1, description="Hop depth distance from root target")


class CallerChain(BaseModel):
    """Complete path of transitive caller hops from target to upstream caller."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    hops: list[CallerChainHop] = Field(
        default_factory=list,
        description="Sequential hops from target outwards to leaf caller",
    )
    path_str: str = Field(
        default="",
        description="Formatted string representation: repoA:fileA:symA -> repoB:fileB:symB",
    )
    depth: int = Field(default=1, ge=1, description="Total hop depth of this chain")
    cross_repo: bool = Field(
        default=False,
        description="True if chain crosses repository boundaries",
    )
    repos_involved: list[str] = Field(
        default_factory=list,
        description="Distinct repositories participating in this caller chain",
    )


class ImpactedNode(BaseModel):
    """Unique code location or symbol affected within blast radius."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str = Field(..., description="Repository of impacted component")
    file_path: str = Field(..., description="File path of impacted component")
    symbol: str = Field(..., description="Symbol identifier or module path")
    depth: int = Field(default=1, ge=1, description="Shortest hop distance from root target")
    direct: bool = Field(default=True, description="True if direct 1-hop dependent")
    caller_count: int = Field(
        default=1,
        ge=1,
        description="Number of distinct paths leading to this node",
    )


class ImpactAdvisory(BaseModel):
    """Actionable recommendation for autonomous AI agent planning."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    severity: BlastRadiusSeverity = Field(..., description="Advisory severity tier")
    category: str = Field(
        ...,
        description="Category: 'migration_order', 'breaking_contract', 'cycle_risk', 'test_scope'",
    )
    message: str = Field(..., description="Diagnostic explanation of architectural risk")
    recommended_action: str = Field(..., description="Concrete instruction for agent planner")


class BlastRadiusSimulationRequest(BaseModel):
    """Request payload for simulating change blast radius."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str = Field(..., description="Target repository name")
    symbol: str | None = Field(
        default=None,
        description="Optional symbol or exported signature identifier to simulate modifying",
    )
    file_path: str | None = Field(
        default=None,
        description="Optional target file path to simulate modifying",
    )
    change_kind: str = Field(
        default="MODIFIED",
        description="Proposed change type: 'MODIFIED', 'REMOVED', 'ADDED', 'DEPRECATED'",
    )
    max_depth: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum transitive hop search depth",
    )


class BlastRadiusSimulationReport(BaseModel):
    """Comprehensive blast-radius simulation report for AI agent planning."""

    model_config = ConfigDict(frozen=True)

    target_repo: str = Field(..., description="Repository evaluated")
    target_symbol: str | None = Field(default=None, description="Target symbol analyzed")
    target_file: str | None = Field(default=None, description="Target file analyzed")
    change_kind: str = Field(default="MODIFIED", description="Proposed change kind")
    max_depth: int = Field(default=5, ge=1, description="Evaluated traversal depth")
    risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Composite architectural risk score (0.0 to 100.0)",
    )
    risk_level: BlastRadiusSeverity = Field(
        default=BlastRadiusSeverity.MINIMAL,
        description="Categorical risk tier",
    )
    total_impacted_repos: int = Field(default=0, ge=0)
    impacted_repos: list[str] = Field(default_factory=list)
    total_impacted_files: int = Field(default=0, ge=0)
    impacted_files: list[str] = Field(default_factory=list)
    total_impacted_symbols: int = Field(default=0, ge=0)
    impacted_nodes: list[ImpactedNode] = Field(default_factory=list)
    caller_chains: list[CallerChain] = Field(default_factory=list)
    cycles_detected: list[list[str]] = Field(
        default_factory=list,
        description="Circular dependency paths traversed",
    )
    advisories: list[ImpactAdvisory] = Field(default_factory=list)
    recommended_update_order: list[str] = Field(
        default_factory=list,
        description="Topological order for staging modifications (leaves before root)",
    )
    suggested_test_suites: list[str] = Field(
        default_factory=list,
        description="List of repository test suites requiring regression execution",
    )

    @property
    def is_breaking(self) -> bool:
        """Whether blast radius carries breaking or critical risk."""
        return self.risk_level.is_breaking

    @model_validator(mode="before")
    @classmethod
    def populate_counts(cls, data: Any) -> Any:
        """Ensure count fields match list lengths if unpopulated."""
        if not isinstance(data, dict):
            return data

        nodes = data.get("impacted_nodes", [])
        repos = set(data.get("impacted_repos", []))
        files = set(data.get("impacted_files", []))
        for node in nodes:
            if isinstance(node, ImpactedNode):
                repos.add(node.repo)
                files.add(f"{node.repo}:{node.file_path}")
            elif isinstance(node, dict):
                r = node.get("repo")
                fp = node.get("file_path")
                if r:
                    repos.add(str(r))
                if r and fp:
                    files.add(f"{r}:{fp}")

        if not data.get("total_impacted_repos") and repos:
            data["total_impacted_repos"] = len(repos)
            data["impacted_repos"] = sorted(repos)
        if not data.get("total_impacted_files") and files:
            data["total_impacted_files"] = len(files)
            data["impacted_files"] = sorted(files)
        if not data.get("total_impacted_symbols") and nodes:
            data["total_impacted_symbols"] = len(nodes)

        return data

    def to_markdown_summary(self) -> str:
        """Format a token-dense markdown summary for LLM agent planners."""
        lines = [
            f"### Blast Radius Simulation: `{self.target_repo}`"
            + (f" :: `{self.target_symbol}`" if self.target_symbol else ""),
            f"- **Risk Level:** `{self.risk_level.value}` (Score: {self.risk_score:.1f}/100.0)",
            f"- **Change Kind:** `{self.change_kind}` | Max Depth: {self.max_depth}",
            (
                f"- **Impact Scope:** {self.total_impacted_repos} repo(s), "
                f"{self.total_impacted_files} file(s), {self.total_impacted_symbols} symbol(s)"
            ),
        ]
        if self.impacted_repos:
            lines.append(f"- **Impacted Repos:** {', '.join(self.impacted_repos)}")
        if self.cycles_detected:
            lines.append(f"- **Cycles Traversed:** {len(self.cycles_detected)} cycle(s)")

        if self.advisories:
            lines.append("\n#### Planning Advisories")
            for adv in self.advisories:
                lines.append(
                    f"- **[{adv.severity.value}] {adv.category}:** "
                    f"{adv.message} -> *{adv.recommended_action}*"
                )

        if self.recommended_update_order:
            lines.append("\n#### Recommended Staging Sequence")
            for idx, item in enumerate(self.recommended_update_order, 1):
                lines.append(f"{idx}. `{item}`")

        if self.suggested_test_suites:
            lines.append("\n#### Required Test Suites")
            for ts in self.suggested_test_suites:
                lines.append(f"- [ ] `{ts}`")

        return "\n".join(lines)


class ImpactTraceResult(BaseModel):
    """Response payload for transitive caller tracing queries."""

    model_config = ConfigDict(frozen=True)

    target_repo: str = Field(..., description="Target repository evaluated")
    symbol: str | None = Field(default=None, description="Target symbol queried")
    file_path: str | None = Field(default=None, description="Target file queried")
    total_chains: int = Field(default=0, ge=0)
    caller_chains: list[CallerChain] = Field(default_factory=list)
    total_impacted_nodes: int = Field(default=0, ge=0)
    impacted_nodes: list[ImpactedNode] = Field(default_factory=list)
    cycles_detected: list[list[str]] = Field(default_factory=list)
