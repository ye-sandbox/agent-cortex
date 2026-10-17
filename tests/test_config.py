"""Unit tests for CortexConfig and configuration loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from cortex.config import (
    AutoDiscoverConfig,
    CortexConfig,
    RemoteConfig,
    RepositorySourceConfig,
    RetrievalConfig,
    SourcesConfig,
    StorageConfig,
    load_config,
    resolve_config_path,
    save_config,
)
from cortex.models import ChunkScope, HardwareProfile, HardwareProfileName


def test_default_config_initialization() -> None:
    """Verifies that default CortexConfig produces valid, expected default values."""
    config = CortexConfig()
    assert config.profile == HardwareProfileName.BALANCED
    assert config.custom_profile is None
    assert config.storage.data_dir == Path("~/.local/share/agent-cortex/data").expanduser()
    assert config.sources.repositories == []
    assert config.sources.auto_discover.enabled is False
    assert config.retrieval.k == 60
    assert config.retrieval.weight_dense == 0.65
    assert config.retrieval.weight_sparse == 0.35
    assert config.retrieval.archived_penalty == 0.6

    active_profile = config.get_active_profile()
    assert active_profile.name == "balanced"
    assert active_profile.embedding_dim == 384


def test_repository_source_config_derived_name(tmp_path: Path) -> None:
    """Verifies that repository name defaults to directory name when omitted."""
    repo_dir = tmp_path / "my-service"
    repo_dir.mkdir()

    source_default = RepositorySourceConfig(path=repo_dir)
    assert source_default.get_repo_name() == "my-service"
    assert source_default.default_scope == ChunkScope.INTERNAL

    source_explicit = RepositorySourceConfig(path=repo_dir, name="custom-name")
    assert source_explicit.get_repo_name() == "custom-name"


def test_save_and_load_config_roundtrip(tmp_path: Path) -> None:
    """Verifies configuration serialization to YAML and roundtrip loading."""
    repo_path = tmp_path / "repo1"
    repo_path.mkdir()

    cfg = CortexConfig(
        profile=HardwareProfileName.HIGH,
        storage=StorageConfig(data_dir=tmp_path / "custom_data"),
        sources=SourcesConfig(
            repositories=[
                RepositorySourceConfig(
                    path=repo_path,
                    name="repo-one",
                    enabled=True,
                    default_scope=ChunkScope.PUBLIC,
                )
            ],
            auto_discover=AutoDiscoverConfig(
                enabled=True,
                roots=[tmp_path],
                max_depth=2,
            ),
        ),
        retrieval=RetrievalConfig(
            k=50,
            weight_dense=0.7,
            weight_sparse=0.3,
            archived_penalty=0.5,
            default_limit=20,
        ),
        remote=RemoteConfig(
            hub_url="http://hub.internal:8000",
            api_key="secret-token",
        ),
    )

    dest = tmp_path / "config.yaml"
    saved_path = save_config(cfg, dest)
    assert saved_path.is_file()

    loaded = load_config(saved_path)
    assert loaded.profile == HardwareProfileName.HIGH
    assert loaded.storage.data_dir == tmp_path / "custom_data"
    assert len(loaded.sources.repositories) == 1
    assert loaded.sources.repositories[0].name == "repo-one"
    assert loaded.sources.repositories[0].default_scope == ChunkScope.PUBLIC
    assert loaded.sources.auto_discover.enabled is True
    assert loaded.retrieval.k == 50
    assert loaded.retrieval.default_limit == 20
    assert loaded.remote.hub_url == "http://hub.internal:8000"
    assert loaded.remote.api_key == "secret-token"


def test_resolve_config_path_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that config resolution honors explicit path and env vars."""
    # Clear any ambient env vars
    monkeypatch.delenv("AGENT_CORTEX_CONFIG", raising=False)
    monkeypatch.delenv("CORTEX_CONFIG", raising=False)

    explicit_cfg = tmp_path / "explicit.yaml"
    explicit_cfg.write_text("profile: low\n", encoding="utf-8")

    env_cfg = tmp_path / "env.yaml"
    env_cfg.write_text("profile: high\n", encoding="utf-8")

    # Explicit argument takes top priority
    assert resolve_config_path(explicit_cfg) == explicit_cfg.resolve()

    # Environment variable priority
    monkeypatch.setenv("AGENT_CORTEX_CONFIG", str(env_cfg))
    assert resolve_config_path() == env_cfg.resolve()


def test_resolve_config_path_workspace_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies workspace candidate discovery in CWD (.cortex/config.yaml)."""
    monkeypatch.delenv("AGENT_CORTEX_CONFIG", raising=False)
    monkeypatch.delenv("CORTEX_CONFIG", raising=False)

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    cortex_dir = workspace_dir / ".cortex"
    cortex_dir.mkdir()
    config_file = cortex_dir / "config.yaml"
    config_file.write_text("profile: balanced\n", encoding="utf-8")

    monkeypatch.chdir(workspace_dir)
    assert resolve_config_path() == config_file.resolve()


def test_environment_variable_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies overlaying environment variables on config."""
    config_file = tmp_path / "base.yaml"
    config_file.write_text(
        "profile: low\nstorage:\n  data_dir: /tmp/base_data\n",
        encoding="utf-8",
    )

    override_dir = tmp_path / "env_data"
    monkeypatch.setenv("AGENT_CORTEX_DATA_DIR", str(override_dir))
    monkeypatch.setenv("CORTEX_PROFILE", "high")
    monkeypatch.setenv("CORTEX_API_KEY", "env-secret-key")
    monkeypatch.setenv("CORTEX_HUB_URL", "https://cortex.corp.internal")

    loaded = load_config(config_file)
    assert loaded.profile == HardwareProfileName.HIGH
    assert loaded.storage.data_dir == override_dir.resolve()
    assert loaded.remote.api_key == "env-secret-key"
    assert loaded.remote.hub_url == "https://cortex.corp.internal"


def test_config_validation_failure_on_invalid_yaml(tmp_path: Path) -> None:
    """Verifies that invalid schema raises validation error."""
    bad_config = tmp_path / "invalid.yaml"
    bad_config.write_text(
        "profile: non_existent_profile\nretrieval:\n  k: -5\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_config(bad_config)


def test_custom_profile_in_config() -> None:
    """Verifies custom hardware profile configuration loading and resolution."""
    cfg = CortexConfig(
        profile=HardwareProfileName.CUSTOM,
        custom_profile=HardwareProfile(
            name="homelab-cluster",
            embedding_model="intfloat/multilingual-e5-small",
            embedding_dim=384,
            reranker_model="BAAI/bge-reranker-base",
            reranker_enabled=True,
            top_k_rerank=25,
            max_threads=8,
        ),
    )
    profile = cfg.get_active_profile()
    assert profile.name == "homelab-cluster"
    assert profile.top_k_rerank == 25
    assert profile.max_threads == 8
