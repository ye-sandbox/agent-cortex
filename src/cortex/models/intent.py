"""Cross-repository portfolio change intent simulation and contract patch models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cortex.models.graph import DependencyEdgeType
from cortex.models.impact import BlastRadiusSeverity, BlastRadiusSimulationReport


class ChangeIntentAction(StrEnum):
    """Categorized action type for contract change intents."""

    RENAME_SYMBOL = "RENAME_SYMBOL"
    MODIFY_SIGNATURE = "MODIFY_SIGNATURE"
    CHANGE_ENDPOINT = "CHANGE_ENDPOINT"
    REPLACE_CONTRACT = "REPLACE_CONTRACT"
    REMOVE_CONTRACT = "REMOVE_CONTRACT"
    DEPRECATE_CONTRACT = "DEPRECATE_CONTRACT"

    @property
    def is_breaking(self) -> bool:
        """Whether this action typically introduces breaking contract changes."""
        return self in (
            ChangeIntentAction.RENAME_SYMBOL,
            ChangeIntentAction.MODIFY_SIGNATURE,
            ChangeIntentAction.CHANGE_ENDPOINT,
            ChangeIntentAction.REPLACE_CONTRACT,
            ChangeIntentAction.REMOVE_CONTRACT,
        )


class ContractChangeIntent(BaseModel):
    """Individual declaration of an intended architectural change to a contract."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    intent_id: str = Field(
        default="",
        description="Deterministic or provided ID of this intent",
    )
    repo: str = Field(..., description="Target repository where contract originates")
    file_path: str | None = Field(
        default=None,
        description="Relative file path in repository (optional if inferred by symbol)",
    )
    target_symbol: str = Field(
        ...,
        description="Target contract symbol, function, class, type, or endpoint path",
    )
    action: ChangeIntentAction = Field(
        default=ChangeIntentAction.RENAME_SYMBOL,
        description="Type of mutation intended",
    )
    new_symbol: str | None = Field(
        default=None,
        description="New symbol name, replacement identifier, or new endpoint path",
    )
    param_renames: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of old parameter names to new parameter names",
    )
    replacement_snippet: str | None = Field(
        default=None,
        description="Optional replacement definition or code snippet",
    )
    description: str = Field(
        default="",
        description="Human or agent rationale for this architectural change",
    )

    @model_validator(mode="before")
    @classmethod
    def populate_intent_id(cls, data: Any) -> Any:
        """Generate deterministic intent_id if missing."""
        if not isinstance(data, dict):
            return data
        if not data.get("intent_id"):
            repo = str(data.get("repo", "unknown")).replace("-", "_")
            sym = str(data.get("target_symbol", "symbol")).replace("/", "_").replace(" ", "_")
            act = str(data.get("action", ChangeIntentAction.RENAME_SYMBOL)).lower()
            data["intent_id"] = f"intent_{repo}_{sym}_{act}"
        return data


class PortfolioChangePlan(BaseModel):
    """Batch of cross-repository contract change intents representing a planned migration."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    plan_id: str = Field(..., description="Unique plan identifier")
    title: str = Field(default="", description="Descriptive title of migration plan")
    intents: list[ContractChangeIntent] = Field(
        default_factory=list,
        description="List of declared contract change intents",
    )
    author: str = Field(
        default="cortex-agent",
        description="Agent or engineer proposing this change plan",
    )


class DownstreamCallSite(BaseModel):
    """Identified downstream consumer call site or reference in the portfolio."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str = Field(..., description="Downstream consumer repository name")
    file_path: str = Field(..., description="File path in consumer repository")
    line_number: int = Field(default=1, ge=1, description="Line number of call site")
    source_symbol: str = Field(
        default="",
        description="Scope or function symbol where call occurs",
    )
    raw_statement: str = Field(
        default="",
        description="Source code statement or import line",
    )
    matched_symbol: str = Field(..., description="Contract symbol matched")
    edge_type: DependencyEdgeType = Field(
        default=DependencyEdgeType.CALL,
        description="AST dependency relationship",
    )


class PatchHunk(BaseModel):
    """Single unified diff hunk representing an automated code modification."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    file_path: str = Field(..., description="Relative file path in repository")
    old_line_start: int = Field(default=1, ge=1)
    old_line_count: int = Field(default=1, ge=0)
    new_line_start: int = Field(default=1, ge=1)
    new_line_count: int = Field(default=1, ge=0)
    diff_text: str = Field(..., description="Unified diff hunk lines starting with @@")
    original_text: str = Field(default="", description="Original line(s) before patch")
    replacement_text: str = Field(default="", description="New line(s) after patch")
    explanation: str = Field(
        default="",
        description="Explanation of why this patch was synthesized",
    )


class RepoMigrationPatch(BaseModel):
    """Collection of synthesized patch hunks and unified diff for a single repository."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str = Field(..., description="Target consumer repository name")
    repo_path: str | None = Field(
        default=None,
        description="Absolute or relative local filesystem path if available",
    )
    total_files: int = Field(default=0, ge=0)
    hunks: list[PatchHunk] = Field(default_factory=list)
    unified_diff: str = Field(
        default="",
        description="Standard unified diff (diff -u) format compatible with git apply",
    )
    breaking_changes_resolved: int = Field(
        default=0,
        ge=0,
        description="Count of breaking call sites or references addressed by this patch",
    )

    @model_validator(mode="before")
    @classmethod
    def compute_totals(cls, data: Any) -> Any:
        """Compute file counts and unified diff if not provided."""
        if not isinstance(data, dict):
            return data
        hunks = data.get("hunks", [])
        if not data.get("total_files") and hunks:
            files = {h.file_path if isinstance(h, PatchHunk) else h.get("file_path") for h in hunks}
            data["total_files"] = len(files)
        return data


class SimulationViolation(BaseModel):
    """Specific architectural or contract violation identified during change simulation."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    severity: BlastRadiusSeverity = Field(..., description="Risk severity tier")
    category: str = Field(
        ...,
        description="Violation category (e.g. 'unmapped_symbol', 'breaking_removal')",
    )
    message: str = Field(..., description="Detailed description of violation")
    call_site: DownstreamCallSite | None = Field(
        default=None,
        description="Call site associated with this violation, if applicable",
    )


class ChangeIntentSimulationReport(BaseModel):
    """Comprehensive portfolio-wide simulation report for an intended change plan."""

    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(..., description="Simulated change plan identifier")
    total_intents: int = Field(default=0, ge=0)
    affected_repos: list[str] = Field(default_factory=list)
    total_call_sites: int = Field(default=0, ge=0)
    call_sites: list[DownstreamCallSite] = Field(default_factory=list)
    violations: list[SimulationViolation] = Field(default_factory=list)
    blast_radius_reports: list[BlastRadiusSimulationReport] = Field(default_factory=list)
    overall_risk_level: BlastRadiusSeverity = Field(
        default=BlastRadiusSeverity.MINIMAL,
        description="Composite portfolio risk tier",
    )
    overall_risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Normalized risk score (0.0 to 100.0)",
    )
    patches_available: bool = Field(
        default=False,
        description="True if automated contract migration patches were synthesized",
    )
    migration_patches: list[RepoMigrationPatch] = Field(
        default_factory=list,
        description="List of per-repository migration patches",
    )
    execution_order: list[str] = Field(
        default_factory=list,
        description="Recommended topological staging order (leaves before root)",
    )

    @model_validator(mode="before")
    @classmethod
    def populate_counts(cls, data: Any) -> Any:
        """Sync count fields from lists if not provided."""
        if not isinstance(data, dict):
            return data
        sites = data.get("call_sites", [])
        if not data.get("total_call_sites") and sites:
            data["total_call_sites"] = len(sites)

        repos = set(data.get("affected_repos", []))
        for site in sites:
            if isinstance(site, DownstreamCallSite):
                repos.add(site.repo)
            elif isinstance(site, dict) and site.get("repo"):
                repos.add(str(site["repo"]))
        if repos:
            data["affected_repos"] = sorted(repos)

        patches = data.get("migration_patches", [])
        if patches:
            data["patches_available"] = True
        return data

    def to_markdown_summary(self) -> str:
        """Format a token-dense markdown summary for Dev Trinity AI agents."""
        lines = [
            f"### Portfolio Change Intent Simulation: `{self.plan_id}`",
            (
                f"- **Overall Risk Level:** `{self.overall_risk_level.value}` "
                f"(Score: {self.overall_risk_score:.1f}/100.0)"
            ),
            f"- **Intents Declared:** {self.total_intents}",
            (
                f"- **Impacted Scope:** {len(self.affected_repos)} repo(s), "
                f"{self.total_call_sites} call site(s)"
            ),
        ]
        if self.affected_repos:
            lines.append(f"- **Affected Repositories:** {', '.join(self.affected_repos)}")

        if self.violations:
            lines.append("\n#### Contract Violations & Drift Risks")
            for viol in self.violations:
                site_info = ""
                if viol.call_site:
                    cs = viol.call_site
                    site_info = f" in `{cs.repo}:{cs.file_path}:{cs.line_number}`"
                lines.append(
                    f"- **[{viol.severity.value}] {viol.category}:** {viol.message}{site_info}"
                )

        if self.migration_patches:
            lines.append("\n#### Automated Migration Patches")
            for patch in self.migration_patches:
                lines.append(
                    f"- **`{patch.repo}`:** {patch.total_files} file(s) patched, "
                    f"{patch.breaking_changes_resolved} breaking reference(s) resolved"
                )

        if self.execution_order:
            lines.append("\n#### Recommended Staging Order")
            for idx, repo in enumerate(self.execution_order, 1):
                lines.append(f"{idx}. `{repo}`")

        return "\n".join(lines)
