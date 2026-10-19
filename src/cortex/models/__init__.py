"""Core data models and schemas for agent-cortex."""

from cortex.models.chunk import (
    ChunkCategory,
    ChunkLifecycle,
    ChunkScope,
    CompactSearchResult,
    DocumentChunk,
    RepoContractChunk,
    SearchResultChunk,
    TechSummary,
    TechUsage,
    aggregate_tech_summary,
    format_contract_chunks,
    resolve_contract_categories,
)
from cortex.models.drift import (
    ChangeKind,
    ContractDriftAlert,
    ContractDriftReport,
    ContractType,
    DriftSeverity,
)
from cortex.models.graph import (
    CodeDependency,
    CodeSignature,
    CrossRepoLink,
    DependencyEdgeType,
    DependencyQueryResult,
    DependentsQueryResult,
    SignaturesQueryResult,
)
from cortex.models.profile import (
    PREDEFINED_PROFILES,
    HardwareProfile,
    HardwareProfileName,
    resolve_hardware_profile,
)

__all__ = [
    "ChangeKind",
    "ChunkCategory",
    "ChunkLifecycle",
    "ChunkScope",
    "CodeDependency",
    "CodeSignature",
    "CompactSearchResult",
    "ContractDriftAlert",
    "ContractDriftReport",
    "ContractType",
    "CrossRepoLink",
    "DependencyEdgeType",
    "DependencyQueryResult",
    "DependentsQueryResult",
    "DocumentChunk",
    "DriftSeverity",
    "HardwareProfile",
    "HardwareProfileName",
    "PREDEFINED_PROFILES",
    "RepoContractChunk",
    "SearchResultChunk",
    "SignaturesQueryResult",
    "TechSummary",
    "TechUsage",
    "aggregate_tech_summary",
    "format_contract_chunks",
    "resolve_contract_categories",
    "resolve_hardware_profile",
]
