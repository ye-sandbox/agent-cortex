"""Architectural contract drift and breaking change domain models."""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DriftSeverity(StrEnum):
    """Severity classification for architectural contract drift."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @property
    def is_breaking(self) -> bool:
        """Return True if severity indicates a breaking change."""
        return self in (DriftSeverity.CRITICAL, DriftSeverity.HIGH)


class ContractType(StrEnum):
    """Category of architectural contract undergoing drift."""

    OPENAPI = "openapi"
    COMPOSE = "compose"
    CODE_SIGNATURE = "code_signature"
    CROSS_REPO_DEPENDENCY = "cross_repo_dependency"


class ChangeKind(StrEnum):
    """Nature of contract alteration."""

    REMOVED = "removed"
    MODIFIED = "modified"
    ADDED = "added"
    DEPRECATED = "deprecated"


class ContractDriftAlert(BaseModel):
    """Alert record for a detected architectural contract modification or violation."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    id: str = Field(
        ...,
        description=(
            "Deterministic unique ID matching "
            "{repo}:{file_path}:{contract_type}:{change_kind}:{slug}"
        ),
    )
    repo: str = Field(..., description="Repository where the contract changed")
    file_path: str = Field(..., description="Relative file path defining the contract")
    contract_type: ContractType = Field(..., description="Type of contract")
    change_kind: ChangeKind = Field(..., description="Type of contract modification")
    severity: DriftSeverity = Field(..., description="Severity classification")
    identifier: str = Field(
        ...,
        description=(
            "Identifying label (e.g. 'GET /api/v1/deals', 'services.db', 'func ProcessPayment')"
        ),
    )
    summary: str = Field(..., description="Concise human/agent-readable summary of the alert")
    details: str = Field(
        default="",
        description="Technical diff details, parameters changed, or signature diff",
    )
    impacted_repos: list[str] = Field(
        default_factory=list,
        description="List of downstream portfolio repositories directly impacted by this change",
    )
    impacted_callers: list[str] = Field(
        default_factory=list,
        description="Specific cross-repo callers or dependents referencing this contract",
    )

    @classmethod
    def build_id(
        cls,
        repo: str,
        file_path: str,
        contract_type: ContractType | str,
        change_kind: ChangeKind | str,
        identifier: str,
    ) -> str:
        """Construct deterministic contract drift alert ID."""
        cleaned_repo = repo.strip()
        cleaned_path = file_path.strip().lstrip("/")
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
        # Slugify identifier to guarantee clean ID
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", identifier.strip()).strip("_") or "root"
        return f"{cleaned_repo}:{cleaned_path}:{c_type}:{c_kind}:{slug}"

    @model_validator(mode="after")
    def validate_id_consistency(self) -> Self:
        """Ensure ID format consistency with repo and file_path."""
        prefix = f"{self.repo}:{self.file_path}:"
        if not self.id.startswith(prefix):
            msg = f"Alert ID '{self.id}' does not start with expected prefix '{prefix}'"
            raise ValueError(msg)
        return self


class ContractDriftReport(BaseModel):
    """Aggregated portfolio or repository contract drift report."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    repo: str | None = Field(
        default=None,
        description="Target repository name, or None for multi-repo report",
    )
    base_commit: str | None = Field(default=None, description="Starting commit SHA")
    target_commit: str | None = Field(default=None, description="Target/HEAD commit SHA")
    total_alerts: int = Field(default=0, description="Total number of alerts")
    breaking_count: int = Field(default=0, description="Count of CRITICAL and HIGH alerts")
    warning_count: int = Field(default=0, description="Count of MEDIUM alerts")
    info_count: int = Field(default=0, description="Count of LOW and INFO alerts")
    alerts: list[ContractDriftAlert] = Field(
        default_factory=list,
        description="List of detected contract drift alerts",
    )

    @classmethod
    def from_alerts(
        cls,
        alerts: Sequence[ContractDriftAlert],
        repo: str | None = None,
        base_commit: str | None = None,
        target_commit: str | None = None,
    ) -> ContractDriftReport:
        """Construct aggregated report calculating alert severity counts automatically."""
        alert_list = list(alerts)
        breaking = sum(1 for a in alert_list if a.severity.is_breaking)
        warning = sum(1 for a in alert_list if a.severity == DriftSeverity.MEDIUM)
        info = sum(1 for a in alert_list if a.severity in (DriftSeverity.LOW, DriftSeverity.INFO))
        return cls(
            repo=repo,
            base_commit=base_commit,
            target_commit=target_commit,
            total_alerts=len(alert_list),
            breaking_count=breaking,
            warning_count=warning,
            info_count=info,
            alerts=alert_list,
        )
