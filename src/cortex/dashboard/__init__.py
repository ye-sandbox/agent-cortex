"""Offline portfolio topology dashboard renderer."""

from __future__ import annotations

import json
from importlib.resources import files

from cortex.models.topology import PortfolioTopologyGraph
from cortex.retrieval.topology import PortfolioTopologyEngine


def render_dashboard(graph: PortfolioTopologyGraph) -> str:
    """Render a self-contained HTML dashboard from an indexed topology snapshot."""
    payload = {
        "topology": PortfolioTopologyEngine.export_cytoscape(graph),
        "cycles": [cycle.path for cycle in graph.cycles],
    }
    safe_json = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    resources = files("cortex.dashboard")
    template = resources.joinpath("template.html").read_text(encoding="utf-8")
    cytoscape_js = resources.joinpath("vendor", "cytoscape.min.js").read_text(encoding="utf-8")
    safe_js = cytoscape_js.replace("</", "<\\/")
    return template.replace("<!-- CORTEX_VENDOR -->", f"<script>{safe_js}</script>").replace(
        "<!-- CORTEX_PAYLOAD -->",
        f'<script id="cortex-data" type="application/json">{safe_json}</script>',
    )
