"""Hardware profile models and resolution engine for agent-cortex."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HardwareProfileName(StrEnum):
    """Supported hardware profile tiers."""

    HIGH = "high"
    BALANCED = "balanced"
    LOW = "low"
    CODE = "code"
    CUSTOM = "custom"


class HardwareProfile(BaseModel):
    """Hardware profile configuration defining model selection and resource bounds."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    name: str = Field(..., description="Profile identifier")
    embedding_model: str = Field(..., description="FastEmbed ONNX embedding model identifier")
    embedding_dim: int = Field(..., gt=0, description="Embedding vector dimensionality")
    reranker_model: str | None = Field(
        default=None,
        description="FastEmbed Cross-Encoder reranker model (None if disabled)",
    )
    reranker_enabled: bool = Field(default=True, description="Whether 2-stage reranking is active")
    top_k_rerank: int = Field(
        default=20,
        ge=0,
        description="Candidate pool size passed from Stage 1 to Stage 2 reranker",
    )
    max_threads: int = Field(
        default=4,
        gt=0,
        description="Maximum CPU threads allocated for ONNX inference to avoid contention",
    )

    @model_validator(mode="after")
    def validate_reranker_configuration(self) -> Self:
        """Validate that reranker settings are coherent."""
        if self.reranker_enabled and not self.reranker_model:
            raise ValueError("reranker_model must be specified when reranker_enabled is True")
        if not self.reranker_enabled and self.top_k_rerank > 0:
            # Normalize top_k_rerank when disabled
            object.__setattr__(self, "top_k_rerank", 0)
        return self


PREDEFINED_PROFILES: dict[HardwareProfileName, HardwareProfile] = {
    HardwareProfileName.HIGH: HardwareProfile(
        name=HardwareProfileName.HIGH.value,
        embedding_model="BAAI/bge-large-en-v1.5",
        embedding_dim=1024,
        reranker_model="BAAI/bge-reranker-large",
        reranker_enabled=True,
        top_k_rerank=30,
        max_threads=4,
    ),
    HardwareProfileName.BALANCED: HardwareProfile(
        name=HardwareProfileName.BALANCED.value,
        embedding_model="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        reranker_model="BAAI/bge-reranker-base",
        reranker_enabled=True,
        top_k_rerank=20,
        max_threads=4,
    ),
    HardwareProfileName.LOW: HardwareProfile(
        name=HardwareProfileName.LOW.value,
        embedding_model="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        reranker_model=None,
        reranker_enabled=False,
        top_k_rerank=0,
        max_threads=2,
    ),
    HardwareProfileName.CODE: HardwareProfile(
        name=HardwareProfileName.CODE.value,
        embedding_model="jinaai/jina-embeddings-v2-base-code",
        embedding_dim=768,
        reranker_model="jinaai/jina-reranker-v1-turbo-en",
        reranker_enabled=True,
        top_k_rerank=25,
        max_threads=4,
    ),
}


def resolve_hardware_profile(
    name: HardwareProfileName | str,
    custom: HardwareProfile | None = None,
) -> HardwareProfile:
    """Resolve a hardware profile by name or return custom configuration."""
    if isinstance(name, str):
        try:
            profile_name = HardwareProfileName(name.lower())
        except ValueError:
            valid_names = ", ".join([p.value for p in HardwareProfileName])
            raise ValueError(
                f"Unknown hardware profile '{name}'. Choose from: {valid_names}"
            ) from None
    else:
        profile_name = name

    if profile_name == HardwareProfileName.CUSTOM:
        if custom is None:
            raise ValueError(
                "Custom profile selected but no custom profile definition was provided"
            )
        return custom

    profile = PREDEFINED_PROFILES.get(profile_name)
    if profile is None:
        raise ValueError(f"Predefined profile '{profile_name.value}' not found in registry")
    return profile
