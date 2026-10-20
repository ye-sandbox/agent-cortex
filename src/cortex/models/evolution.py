"""Architectural contract evolution timeline and changelog synthesis domain models."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cortex.models.drift import ChangeKind, ContractType, DriftSeverity


class ContractEvolutionEvent(BaseModel):
    """An event recording an architectural contract mutation across commit checkpoints."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    id: str = Field(
        ...,
        description=(
            "Deterministic unique ID matching "
            "{repo}:{commit_sha}:{contract_type}:{change_kind}:{slug}"
        ),
    )
    repo: str = Field(..., description="Repository where the contract changed")
    commit_sha: str = Field(..., description="Commit SHA where change was introduced")
    commit_date: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp of commit or event recording",
    )
    author: str = Field(default="", description="Author of commit or initiating agent")
    version_tag: str | None = Field(default=None, description="Associated release or SemVer tag")
    contract_type: ContractType = Field(..., description="Category of architectural contract")
    change_kind: ChangeKind = Field(..., description="Nature of contract mutation")
    severity: DriftSeverity = Field(..., description="Severity classification")
    identifier: str = Field(..., description="Contract symbol or path identifier")
    file_path: str = Field(..., description="Relative file path defining the contract")
    summary: str = Field(..., description="Concise human/agent-readable summary of the mutation")
    details: str = Field(default="", description="Technical diff or signature modification")
    impacted_repos: list[str] = Field(
        default_factory=list,
        description="Downstream portfolio repositories directly affected",
    )
    impacted_callers: list[str] = Field(
        default_factory=list,
        description="Specific cross-repo callers or dependents referencing this contract",
    )

    @classmethod
    def build_id(
        cls,
        repo: str,
        commit_sha: str,
        contract_type: ContractType | str,
        change_kind: ChangeKind | str,
        identifier: str,
    ) -> str:
        """Construct deterministic evolution event ID."""
        cleaned_repo = repo.strip()
        cleaned_commit = commit_sha.strip()[:12] or "unknown"
        c_type = (
            contract_type.value
            if isinstance(contract_type, ContractType)
            else str(contract_type).lower().strip()
        )
        c_kind = (
            change_kind.value
            if isinstance(change_kind, ChangeKind)
            else str(change_kind).lower().strip()
        )
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", identifier.strip()).strip("_") or "root"
        return f"{cleaned_repo}:{cleaned_commit}:{c_type}:{c_kind}:{slug}"

    @model_validator(mode="after")
    def validate_id_prefix(self) -> Self:
        """Verify that ID contains repo prefix."""
        prefix = f"{self.repo}:"
        if not self.id.startswith(prefix):
            msg = f"Event ID '{self.id}' does not start with repo prefix '{prefix}'"
            raise ValueError(msg)
        return self


class ContractEvolutionTimeline(BaseModel):
    """Aggregated timeline of architectural contract mutations across time."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str | None = Field(
        default=None,
        description="Target repository name, or None for portfolio-wide timeline",
    )
    total_events: int = Field(default=0, description="Total count of recorded evolution events")
    breaking_count: int = Field(default=0, description="Count of CRITICAL and HIGH breaking events")
    warning_count: int = Field(default=0, description="Count of MEDIUM severity events")
    info_count: int = Field(default=0, description="Count of LOW and INFO severity events")
    events: list[ContractEvolutionEvent] = Field(
        default_factory=list,
        description="Chronological or reverse-chronological evolution events",
    )
    impacted_repos_summary: dict[str, int] = Field(
        default_factory=dict,
        description="Count of impacted events per downstream repository",
    )

    @classmethod
    def from_events(
        cls,
        events: Sequence[ContractEvolutionEvent],
        repo: str | None = None,
    ) -> ContractEvolutionTimeline:
        """Construct timeline aggregating severity counts and downstream impacts."""
        event_list = list(events)
        breaking = sum(1 for e in event_list if e.severity.is_breaking)
        warning = sum(1 for e in event_list if e.severity == DriftSeverity.MEDIUM)
        info = sum(1 for e in event_list if e.severity in (DriftSeverity.LOW, DriftSeverity.INFO))

        impact_counter: Counter[str] = Counter()
        for e in event_list:
            for r in e.impacted_repos:
                impact_counter[r] += 1

        return cls(
            repo=repo,
            total_events=len(event_list),
            breaking_count=breaking,
            warning_count=warning,
            info_count=info,
            events=event_list,
            impacted_repos_summary=dict(impact_counter.most_common()),
        )


class ChangelogSection(BaseModel):
    """A subsection within a release grouping contract changes by nature."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    title: str = Field(..., description="Section title (e.g. '🚨 Breaking Changes')")
    change_kind: ChangeKind | None = Field(
        default=None,
        description="Specific change kind or None for composite",
    )
    events: list[ContractEvolutionEvent] = Field(
        default_factory=list,
        description="Events belonging to this section",
    )


class ChangelogRelease(BaseModel):
    """Release or temporal checkpoint grouping architectural contract mutations."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    tag_or_period: str = Field(
        ...,
        description="Tag identifier (e.g. 'v1.2.0') or date interval / commit range",
    )
    date: str | None = Field(default=None, description="Release date or period end")
    repo: str | None = Field(default=None, description="Target repository or portfolio-wide")
    breaking_count: int = Field(default=0, description="Number of breaking contract changes")
    total_changes: int = Field(default=0, description="Total contract changes in this release")
    sections: list[ChangelogSection] = Field(
        default_factory=list,
        description="Sections categorized by change type",
    )
    impacted_repos: list[str] = Field(
        default_factory=list,
        description="Distinct downstream portfolio repositories affected",
    )


class ArchitecturalChangelog(BaseModel):
    """Synthesized portfolio architectural contract changelog."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    title: str = Field(default="Portfolio Architectural Changelog", description="Document title")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp of generation",
    )
    repo: str | None = Field(default=None, description="Specific repository or portfolio-wide")
    releases: list[ChangelogRelease] = Field(
        default_factory=list,
        description="Ordered list of releases/checkpoints",
    )
    total_breaking: int = Field(default=0, description="Cumulative count of breaking changes")
    total_changes: int = Field(default=0, description="Cumulative count of all contract changes")

    def to_markdown(self) -> str:
        """Render synthesized changelog into clean Technical Markdown."""
        lines: list[str] = []
        scope_suffix = f" — `{self.repo}`" if self.repo else " — Portfolio-Wide"
        lines.append(f"# {self.title}{scope_suffix}\n")
        lines.append(
            f"> Generated: `{self.generated_at}` | Total Changes: `{self.total_changes}` | "
            f"Breaking Mutations: `{self.total_breaking}`\n"
        )

        if not self.releases:
            lines.append("_No architectural contract changes recorded._\n")
            return "\n".join(lines)

        for release in self.releases:
            date_str = f" ({release.date})" if release.date else ""
            lines.append(f"## [{release.tag_or_period}]{date_str}\n")

            if release.impacted_repos:
                impacted_str = ", ".join(f"`{r}`" for r in sorted(release.impacted_repos))
                lines.append(f"> ⚠️ **Downstream Portfolio Impact:** {impacted_str}\n")

            if not release.sections:
                lines.append("_No classified mutations in this release._\n")
                continue

            for sec in release.sections:
                if not sec.events:
                    continue
                lines.append(f"### {sec.title}\n")
                for evt in sec.events:
                    badge = f"**[{evt.severity.value}]**"
                    repo_prefix = f"[`{evt.repo}`] " if not self.repo else ""
                    lines.append(f"- {badge} {repo_prefix}`{evt.identifier}`: {evt.summary}")
                    if evt.details:
                        lines.append(f"  - *Details:* {evt.details}")
                    if evt.impacted_repos:
                        impact_joined = ", ".join(f"`{ir}`" for ir in evt.impacted_repos)
                        lines.append(f"  - *Impacted Repos:* {impact_joined}")
                    if evt.impacted_callers:
                        caller_joined = ", ".join(f"`{c}`" for c in evt.impacted_callers[:5])
                        lines.append(f"  - *Impacted Callers:* {caller_joined}")
                lines.append("")

        return "\n".join(lines).strip() + "\n"
