"""Configuration loader and schema definitions for agent-cortex."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from cortex.models.chunk import ChunkScope
from cortex.models.profile import (
    HardwareProfile,
    HardwareProfileName,
    resolve_hardware_profile,
)

DEFAULT_IGNORE_PATTERNS: list[str] = [
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "target",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
]


class RepositorySourceConfig(BaseModel):
    """Configuration for an individual repository source."""

    model_config = ConfigDict(str_strip_whitespace=True)

    path: Path = Field(..., description="Filesystem path to repository root")
    name: str | None = Field(
        default=None,
        description="Logical repository name (defaults to directory name if omitted)",
    )
    enabled: bool = Field(default=True, description="Whether this repository is active for sync")
    default_scope: ChunkScope = Field(
        default=ChunkScope.INTERNAL,
        description="Default privacy/access scope for chunks in this repository",
    )

    @field_validator("path")
    @classmethod
    def expand_path(cls, value: Path) -> Path:
        """Expand user home directory (~)."""
        return value.expanduser()

    def get_repo_name(self) -> str:
        """Return explicit repository name or derive from folder basename."""
        if self.name and self.name.strip():
            return self.name.strip()
        return self.path.name


class AutoDiscoverConfig(BaseModel):
    """Configuration for portfolio-wide automatic repository discovery."""

    model_config = ConfigDict(str_strip_whitespace=True)

    enabled: bool = Field(default=False, description="Whether repository auto-discovery is enabled")
    roots: list[Path] = Field(
        default_factory=list,
        description="Root directories scanned for git repositories",
    )
    max_depth: int = Field(default=3, ge=1, le=10, description="Maximum directory traversal depth")
    ignore_patterns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS),
        description="Directory patterns ignored during scanning",
    )

    @field_validator("roots")
    @classmethod
    def expand_roots(cls, values: list[Path]) -> list[Path]:
        """Expand user paths for all root discovery directories."""
        return [p.expanduser() for p in values]


class SourcesConfig(BaseModel):
    """Aggregate configuration for all ingestion sources."""

    model_config = ConfigDict(str_strip_whitespace=True)

    repositories: list[RepositorySourceConfig] = Field(
        default_factory=list,
        description="List of explicitly configured repositories",
    )
    auto_discover: AutoDiscoverConfig = Field(
        default_factory=AutoDiscoverConfig,
        description="Auto-discovery settings for discovering satellite repositories",
    )


class StorageConfig(BaseModel):
    """Vector database and persistence storage configuration."""

    model_config = ConfigDict(str_strip_whitespace=True)

    data_dir: Path = Field(
        default_factory=lambda: Path("~/.local/share/agent-cortex/data").expanduser(),
        description="Directory for local LanceDB storage and indexes (never inside git repo)",
    )

    @field_validator("data_dir")
    @classmethod
    def expand_data_dir(cls, value: Path) -> Path:
        """Expand user home directory (~)."""
        return value.expanduser()


class RetrievalConfig(BaseModel):
    """Stage 1 and Stage 2 retrieval and scoring formulas."""

    model_config = ConfigDict(str_strip_whitespace=True)

    k: int = Field(default=60, ge=1, description="RRF rank constant")
    weight_dense: float = Field(default=0.65, ge=0.0, le=1.0, description="RRF dense weight")
    weight_sparse: float = Field(default=0.35, ge=0.0, le=1.0, description="RRF sparse weight")
    archived_penalty: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Score multiplier applied to archived chunks",
    )
    default_limit: int = Field(default=10, ge=1, le=100, description="Default search result count")


class RemoteConfig(BaseModel):
    """Configuration for Dual-Mode homelab hub client."""

    model_config = ConfigDict(str_strip_whitespace=True)

    hub_url: str | None = Field(
        default=None,
        description="Remote agent-cortex hub endpoint (e.g. 'http://homelab:8000')",
    )
    api_key: str | None = Field(
        default=None,
        description="Bearer token for remote hub authentication",
    )


class CortexConfig(BaseModel):
    """Root configuration for agent-cortex."""

    model_config = ConfigDict(str_strip_whitespace=True)

    profile: HardwareProfileName = Field(
        default=HardwareProfileName.BALANCED,
        description="Active hardware profile tier (high, balanced, low, custom)",
    )
    custom_profile: HardwareProfile | None = Field(
        default=None,
        description="User-defined hardware profile (required if profile=custom)",
    )
    storage: StorageConfig = Field(
        default_factory=StorageConfig,
        description="Storage and vector DB directory configuration",
    )
    sources: SourcesConfig = Field(
        default_factory=SourcesConfig,
        description="Ingestion sources and auto-discovery settings",
    )
    retrieval: RetrievalConfig = Field(
        default_factory=RetrievalConfig,
        description="Retrieval weights, RRF constants, and ranking formulas",
    )
    remote: RemoteConfig = Field(
        default_factory=RemoteConfig,
        description="Dual-Mode remote hub configuration",
    )

    def get_active_profile(self) -> HardwareProfile:
        """Resolve the active hardware profile model."""
        return resolve_hardware_profile(self.profile, self.custom_profile)

    def to_yaml(self) -> str:
        """Serialize configuration to clean YAML string."""
        raw_dict = self.model_dump(mode="json")
        dumped: str = yaml.safe_dump(raw_dict, sort_keys=False, default_flow_style=False)
        return dumped


def get_default_config_path() -> Path:
    """Return standard global user configuration path."""
    return Path("~/.config/agent-cortex/config.yaml").expanduser()


def resolve_config_path(custom_path: Path | str | None = None) -> Path | None:
    """Find configuration file following priority order:
    1. Explicit path parameter
    2. AGENT_CORTEX_CONFIG or CORTEX_CONFIG env var
    3. Workspace override (.cortex/config.yaml or cortex.yaml in CWD)
    4. Global user config (~/.config/agent-cortex/config.yaml)
    """
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        return p if p.is_file() else None

    # Check env vars
    for env_var in ("AGENT_CORTEX_CONFIG", "CORTEX_CONFIG"):
        env_val = os.environ.get(env_var)
        if env_val:
            p = Path(env_val).expanduser().resolve()
            if p.is_file():
                return p

    # Check workspace overrides in current directory
    cwd = Path.cwd()
    workspace_candidates = [
        cwd / ".cortex" / "config.yaml",
        cwd / ".cortex" / "config.yml",
        cwd / "cortex.yaml",
        cwd / "cortex.yml",
    ]
    for candidate in workspace_candidates:
        if candidate.is_file():
            return candidate.resolve()

    # Check global user configuration
    global_path = get_default_config_path()
    if global_path.is_file():
        return global_path.resolve()

    return None


def apply_env_overrides(config_data: dict[str, Any]) -> dict[str, Any]:
    """Overlay environment variables on top of raw configuration data."""
    # Data directory override
    env_data_dir = os.environ.get("AGENT_CORTEX_DATA_DIR")
    if env_data_dir:
        storage_section = config_data.setdefault("storage", {})
        if isinstance(storage_section, dict):
            storage_section["data_dir"] = env_data_dir

    # Profile override
    env_profile = os.environ.get("CORTEX_PROFILE")
    if env_profile:
        config_data["profile"] = env_profile.lower()

    # Remote API Key override
    env_api_key = os.environ.get("CORTEX_API_KEY")
    if env_api_key:
        remote_section = config_data.setdefault("remote", {})
        if isinstance(remote_section, dict):
            remote_section["api_key"] = env_api_key

    # Remote Hub URL override
    env_hub_url = os.environ.get("CORTEX_HUB_URL")
    if env_hub_url:
        remote_section = config_data.setdefault("remote", {})
        if isinstance(remote_section, dict):
            remote_section["hub_url"] = env_hub_url

    return config_data


def load_config(config_path: Path | str | None = None) -> CortexConfig:
    """Load and validate CortexConfig from resolved path or defaults with env overrides."""
    resolved_path = resolve_config_path(config_path)

    raw_data: dict[str, Any] = {}
    if resolved_path and resolved_path.is_file():
        content = resolved_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        if isinstance(parsed, dict):
            raw_data = parsed

    # Apply environment overrides on top of parsed file (or defaults)
    overridden_data = apply_env_overrides(raw_data)

    return CortexConfig.model_validate(overridden_data)


def save_config(config: CortexConfig, destination: Path | str) -> Path:
    """Write CortexConfig to YAML file, creating parent directories if needed."""
    dest_path = Path(destination).expanduser().resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(config.to_yaml(), encoding="utf-8")
    return dest_path
