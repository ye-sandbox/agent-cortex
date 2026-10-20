"""Dual-mode client for agent-cortex.

Provides seamless switching and fallback between local in-process retrieval (Stage 1 & 2
LanceDB + FastEmbed) and remote homelab daemon querying via HTTP/NDJSON streaming.
Decomposed into domain mixins for retrieval, graph, drift, topology, impact, evolution,
intent, sync, and dynamic configuration.
"""

from __future__ import annotations

import httpx  # Re-exported for client patching and connection diagnostics

from cortex.client.base import (
    ClientMode,
    CortexAuthError,
    CortexBaseClient,
    CortexClientError,
    CortexRemoteError,
)
from cortex.client.config import ConfigClientMixin
from cortex.client.drift import DriftClientMixin
from cortex.client.evolution import EvolutionClientMixin
from cortex.client.graph import GraphClientMixin
from cortex.client.impact import ImpactClientMixin
from cortex.client.intent import IntentClientMixin
from cortex.client.search import SearchClientMixin
from cortex.client.sync import SyncClientMixin
from cortex.client.topology import TopologyClientMixin


class CortexClient(
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
):
    """Unified dual-mode client for querying agent-cortex knowledge bases."""


__all__ = [
    "ClientMode",
    "ConfigClientMixin",
    "CortexAuthError",
    "CortexBaseClient",
    "CortexClient",
    "CortexClientError",
    "CortexRemoteError",
    "DriftClientMixin",
    "EvolutionClientMixin",
    "GraphClientMixin",
    "ImpactClientMixin",
    "IntentClientMixin",
    "SearchClientMixin",
    "SyncClientMixin",
    "TopologyClientMixin",
    "httpx",
]
