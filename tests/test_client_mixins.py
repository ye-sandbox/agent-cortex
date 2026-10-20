"""Hermetic unit tests for CortexClient domain mixin decomposition."""

from __future__ import annotations

import cortex.client
from cortex.client import (
    ClientMode,
    ConfigClientMixin,
    CortexAuthError,
    CortexBaseClient,
    CortexClient,
    CortexClientError,
    CortexRemoteError,
    DriftClientMixin,
    EvolutionClientMixin,
    GraphClientMixin,
    ImpactClientMixin,
    IntentClientMixin,
    SearchClientMixin,
    SyncClientMixin,
    TopologyClientMixin,
)


def test_cortex_client_inheritance_hierarchy() -> None:
    """Verify CortexClient composes all domain mixins cleanly without MRO conflicts."""
    expected_mixins = [
        SearchClientMixin,
        GraphClientMixin,
        DriftClientMixin,
        TopologyClientMixin,
        ImpactClientMixin,
        EvolutionClientMixin,
        IntentClientMixin,
        SyncClientMixin,
        ConfigClientMixin,
        CortexBaseClient,
    ]

    for mixin in expected_mixins:
        assert issubclass(CortexClient, mixin), f"CortexClient must subclass {mixin.__name__}"


def test_domain_mixin_method_bindings() -> None:
    """Verify methods reside in their designated domain mixins."""
    assert hasattr(SearchClientMixin, "search")
    assert hasattr(SearchClientMixin, "search_stream")
    assert hasattr(SearchClientMixin, "get_repo_contracts")
    assert hasattr(SearchClientMixin, "list_technologies")

    assert hasattr(GraphClientMixin, "get_dependencies")
    assert hasattr(GraphClientMixin, "get_dependents")
    assert hasattr(GraphClientMixin, "get_signatures")

    assert hasattr(DriftClientMixin, "get_contract_drift")

    assert hasattr(TopologyClientMixin, "get_portfolio_topology")
    assert hasattr(TopologyClientMixin, "get_dependency_matrix")
    assert hasattr(TopologyClientMixin, "get_topology_cycles")

    assert hasattr(ImpactClientMixin, "simulate_blast_radius")
    assert hasattr(ImpactClientMixin, "trace_impact")

    assert hasattr(EvolutionClientMixin, "get_contract_timeline")
    assert hasattr(EvolutionClientMixin, "synthesize_changelog")

    assert hasattr(IntentClientMixin, "simulate_change_intent")
    assert hasattr(IntentClientMixin, "generate_contract_patches")

    assert hasattr(SyncClientMixin, "sync")

    assert hasattr(ConfigClientMixin, "get_config")
    assert hasattr(ConfigClientMixin, "set_config")
    assert hasattr(ConfigClientMixin, "delete_config")
    assert hasattr(ConfigClientMixin, "list_tenants")

    assert hasattr(CortexBaseClient, "health")
    assert hasattr(CortexBaseClient, "close")


def test_cortex_client_public_exports_and_httpx_patchability() -> None:
    """Verify backwards-compatible module exports and httpx attribute accessibility."""
    assert hasattr(cortex.client, "httpx")
    assert hasattr(cortex.client.httpx, "Client")
    assert issubclass(CortexAuthError, CortexRemoteError)
    assert issubclass(CortexRemoteError, CortexClientError)
    assert issubclass(CortexClientError, Exception)

    # Check __all__ consistency
    all_exports = set(cortex.client.__all__)
    assert "CortexClient" in all_exports
    assert "CortexBaseClient" in all_exports
    assert "SearchClientMixin" in all_exports
    assert "ClientMode" in all_exports
    assert "httpx" in all_exports
    # Verify ClientMode type alias usage
    mode: ClientMode = "auto"
    assert mode in ("in_process", "remote", "auto")
