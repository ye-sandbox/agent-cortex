"""Cross-repository portfolio topology synthesis, dependency matrix, and graph export engine."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from cortex.config.loader import CortexConfig, load_config
from cortex.models.graph import CodeDependency, CrossRepoLink
from cortex.models.topology import (
    DependencyCycle,
    PortfolioDependencyEdge,
    PortfolioDependencyMatrix,
    PortfolioMatrixRow,
    PortfolioRepoNode,
    PortfolioTopologyGraph,
    TopologyExportFormat,
)
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)


def _sanitize_mermaid_id(name: str) -> str:
    """Produce a safe, alphanumeric Mermaid node identifier."""
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())
    return f"repo_{cleaned}" if cleaned and cleaned[0].isdigit() else (cleaned or "repo_unknown")


class PortfolioTopologyEngine:
    """Synthesizes cross-repository topology graphs, coupling metrics, and dependency matrices."""

    def __init__(
        self,
        storage_manager: StorageManager,
        graph_engine: DependencyGraphEngine | None = None,
    ) -> None:
        """Initialize engine with storage and dependency graph query components."""
        self.storage = storage_manager
        self.graph = graph_engine or DependencyGraphEngine(self.storage)

    @classmethod
    def from_config(cls, config: CortexConfig | None = None) -> PortfolioTopologyEngine:
        """Construct PortfolioTopologyEngine from resolved config or system defaults."""
        cfg = config or load_config()
        storage = StorageManager(data_dir=cfg.storage.data_dir)
        graph = DependencyGraphEngine(storage)
        return cls(storage_manager=storage, graph_engine=graph)

    def get_known_repos(self) -> list[str]:
        """Discover all unique repository names across indexed storage tables."""
        repos: set[str] = set()

        # Discover from graph engine (signatures and chunks)
        for r in self.graph.get_known_repos():
            if r.strip():
                repos.add(r.strip())

        # Discover from chunks table
        if "chunks" in self.storage.table_names():
            for r in self.storage.get_indexed_repos():
                if r.strip():
                    repos.add(r.strip())

        # Discover from code_dependencies table
        if "code_dependencies" in self.storage.table_names():
            deps = self.storage.get_dependencies(limit=10000)
            for d in deps:
                if d.source_repo.strip():
                    repos.add(d.source_repo.strip())
                if d.target_repo and d.target_repo.strip():
                    repos.add(d.target_repo.strip())

        return sorted(repos)

    def detect_cycles(self, edges: Sequence[PortfolioDependencyEdge]) -> list[DependencyCycle]:
        """Detect all unique elementary cycles in the directed portfolio graph."""
        adj: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            adj[edge.source_repo].append(edge.target_repo)

        found_cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: list[str] = []

        def dfs(node: str) -> None:
            rec_stack.append(node)
            for neighbor in sorted(adj.get(node, [])):
                if neighbor in rec_stack:
                    cycle_start_idx = rec_stack.index(neighbor)
                    cycle = rec_stack[cycle_start_idx:] + [neighbor]
                    found_cycles.append(cycle)
                elif neighbor not in visited:
                    dfs(neighbor)
            rec_stack.pop()
            visited.add(node)

        all_nodes = sorted(adj.keys())
        for n in all_nodes:
            if n not in visited:
                dfs(n)

        # Deduplicate cycles by rotating to lexicographically smallest node
        unique_cycles: list[DependencyCycle] = []
        seen: set[tuple[str, ...]] = set()

        for raw_cycle in found_cycles:
            nodes = raw_cycle[:-1]  # Exclude closing duplicate
            if len(nodes) < 2:
                continue
            min_idx = nodes.index(min(nodes))
            canonical = tuple(nodes[min_idx:] + nodes[:min_idx])
            if canonical not in seen:
                seen.add(canonical)
                unique_cycles.append(
                    DependencyCycle(
                        path=list(canonical) + [canonical[0]],
                        length=len(canonical),
                    )
                )

        return sorted(unique_cycles, key=lambda c: (c.length, c.path))

    def build_topology(
        self,
        include_internal: bool = False,
        min_weight: int = 1,
    ) -> PortfolioTopologyGraph:
        """Synthesize portfolio topology graph with coupling metrics and architectural bridges."""
        known_repos = self.get_known_repos()
        all_deps: list[CodeDependency] = []
        if "code_dependencies" in self.storage.table_names():
            all_deps = self.storage.get_dependencies(limit=25000)

        # Resolve cross-repo bridges
        cross_links = self.graph.resolve_cross_repo_links(all_deps, known_repos=known_repos)
        link_map: dict[tuple[str, str], list[CrossRepoLink]] = defaultdict(list)
        for link in cross_links:
            link_map[(link.source_repo, link.target_repo)].append(link)

        # Aggregate directed edges between repos
        edge_map: dict[
            tuple[str, str],
            dict[str, Any],
        ] = defaultdict(
            lambda: {
                "weight": 0,
                "edge_types": defaultdict(int),
                "symbols": set(),
                "bridges": [],
            }
        )

        # Map dependency occurrences
        for dep in all_deps:
            source = dep.source_repo.strip()
            # If target_repo not explicitly populated, check cross_links match
            target = dep.target_repo
            if not target:
                matching_links = [
                    lnk
                    for lnk in cross_links
                    if lnk.source_repo == source
                    and lnk.source_file == dep.source_file
                    and (lnk.symbol == dep.target_symbol or lnk.symbol == dep.target_module)
                ]
                if matching_links:
                    target = matching_links[0].target_repo

            if not target:
                continue

            target = target.strip()
            if not include_internal and source == target:
                continue

            edge_key = (source, target)
            edge_map[edge_key]["weight"] += 1
            edge_map[edge_key]["edge_types"][dep.edge_type.value] += 1
            sym = dep.target_symbol or dep.target_module
            if sym:
                edge_map[edge_key]["symbols"].add(sym)

        # Attach resolved cross-repo bridges
        for (src, tgt), bridges in link_map.items():
            if not include_internal and src == tgt:
                continue
            edge_key = (src, tgt)
            edge_map[edge_key]["bridges"] = bridges
            if edge_map[edge_key]["weight"] == 0:
                edge_map[edge_key]["weight"] = len(bridges)
                for b in bridges:
                    edge_map[edge_key]["edge_types"][b.edge_type.value] += 1
                    if b.symbol:
                        edge_map[edge_key]["symbols"].add(b.symbol)

        # Construct PortfolioDependencyEdge objects
        edges: list[PortfolioDependencyEdge] = []
        for (src, tgt), data in sorted(edge_map.items()):
            weight = int(data["weight"])
            if weight < min_weight:
                continue
            edge_types_dict: dict[str, int] = dict(data["edge_types"])
            symbols_list: list[str] = sorted(data["symbols"])[:20]
            bridges_list: list[CrossRepoLink] = data["bridges"]
            edges.append(
                PortfolioDependencyEdge(
                    source_repo=src,
                    target_repo=tgt,
                    weight=weight,
                    edge_types=edge_types_dict,
                    symbols=symbols_list,
                    bridges=bridges_list,
                )
            )

        # Calculate coupling metrics
        afferent_map: dict[str, set[str]] = defaultdict(set)
        efferent_map: dict[str, set[str]] = defaultdict(set)

        for edge in edges:
            if edge.source_repo != edge.target_repo:
                efferent_map[edge.source_repo].add(edge.target_repo)
                afferent_map[edge.target_repo].add(edge.source_repo)

        # Retrieve per-repository languages, technologies, and contracts
        nodes: list[PortfolioRepoNode] = []
        for repo in known_repos:
            safe_repo = repo.replace("'", "''")

            # Languages
            languages: set[str] = set()
            sig_count = 0
            if "code_signatures" in self.storage.table_names():
                sigs = self.storage.get_signatures(where=f"repo = '{safe_repo}'", limit=2000)
                sig_count = len(sigs)
                for s in sigs:
                    if s.language:
                        languages.add(s.language.lower())

            # Technologies
            technologies: set[str] = set()
            contract_count = 0
            if "chunks" in self.storage.table_names():
                tech_records = self.storage.get_technologies(repo=repo)
                for rec in tech_records:
                    tags = rec.get("tags")
                    if isinstance(tags, list):
                        for t in tags:
                            if isinstance(t, str) and t.strip():
                                technologies.add(t.strip())
                contracts = self.storage.get_repo_contracts(repo=repo, limit=500)
                contract_count = len(contracts)

            ca = len(afferent_map.get(repo, set()))
            ce = len(efferent_map.get(repo, set()))
            instability = round(float(ce) / float(ca + ce), 2) if (ca + ce) > 0 else 0.0

            nodes.append(
                PortfolioRepoNode(
                    repo=repo,
                    languages=sorted(languages),
                    technologies=sorted(technologies)[:15],
                    total_signatures=sig_count,
                    total_contracts=contract_count,
                    afferent_coupling=ca,
                    efferent_coupling=ce,
                    instability=instability,
                    is_leaf=(ce == 0),
                    is_root=(ca == 0),
                )
            )

        # Detect circular dependencies
        cycles = self.detect_cycles(edges)

        # Compute graph density
        v = len(nodes)
        e = len(edges)
        density = round(float(e) / float(v * (v - 1)), 4) if v > 1 else 0.0
        total_references = sum(edge.weight for edge in edges)

        return PortfolioTopologyGraph(
            nodes=nodes,
            edges=edges,
            cycles=cycles,
            total_repos=v,
            total_cross_repo_edges=e,
            total_cross_repo_references=total_references,
            density=density,
        )

    def build_matrix(self, min_weight: int = 0) -> PortfolioDependencyMatrix:
        """Synthesize NxN cross-repository dependency matrix representation."""
        graph = self.build_topology(include_internal=False, min_weight=max(1, min_weight))
        repos = [node.repo for node in graph.nodes]
        repo_node_map = {node.repo: node for node in graph.nodes}

        # Build lookup of edge weights: (source, target) -> weight
        edge_weight_map: dict[tuple[str, str], int] = {}
        for edge in graph.edges:
            edge_weight_map[(edge.source_repo, edge.target_repo)] = edge.weight

        rows: list[PortfolioMatrixRow] = []
        for src in repos:
            targets_dict: dict[str, int] = {}
            for tgt in repos:
                targets_dict[tgt] = edge_weight_map.get((src, tgt), 0)

            node = repo_node_map[src]
            rows.append(
                PortfolioMatrixRow(
                    source_repo=src,
                    targets=targets_dict,
                    afferent_coupling=node.afferent_coupling,
                    efferent_coupling=node.efferent_coupling,
                    instability=node.instability,
                )
            )

        # Identify most coupled repositories
        most_depended = max(graph.nodes, key=lambda n: n.afferent_coupling, default=None)
        most_dependent = max(graph.nodes, key=lambda n: n.efferent_coupling, default=None)

        summary: dict[str, Any] = {
            "total_repositories": graph.total_repos,
            "total_cross_repo_edges": graph.total_cross_repo_edges,
            "total_cross_repo_references": graph.total_cross_repo_references,
            "density": graph.density,
            "cycle_count": len(graph.cycles),
            "most_depended_repository": (
                most_depended.repo
                if most_depended and most_depended.afferent_coupling > 0
                else None
            ),
            "most_dependent_repository": (
                most_dependent.repo
                if most_dependent and most_dependent.efferent_coupling > 0
                else None
            ),
        }

        return PortfolioDependencyMatrix(
            repos=repos,
            rows=rows,
            cycles=graph.cycles,
            summary=summary,
        )

    def export_mermaid(
        self,
        graph: PortfolioTopologyGraph,
        direction: str = "LR",
        highlight_cycles: bool = True,
    ) -> str:
        """Generate a GitHub Flavored Markdown-compatible Mermaid flowchart."""
        lines: list[str] = [f"flowchart {direction}"]

        cycle_repos: set[str] = set()
        if highlight_cycles:
            for c in graph.cycles:
                cycle_repos.update(c.path)

        # Declare nodes
        for node in graph.nodes:
            nid = _sanitize_mermaid_id(node.repo)
            lang_str = f" ({', '.join(node.languages)})" if node.languages else ""
            ca, ce, inst = node.afferent_coupling, node.efferent_coupling, node.instability
            metrics_str = f"Ca:{ca} Ce:{ce} I:{inst:.2f}"
            label = f'"{node.repo}{lang_str}<br/>[{metrics_str}]"'
            lines.append(f"    {nid}[{label}]")

        # Declare edges
        for edge in graph.edges:
            src_id = _sanitize_mermaid_id(edge.source_repo)
            tgt_id = _sanitize_mermaid_id(edge.target_repo)
            edge_label = f"|{edge.weight} refs|" if edge.weight > 1 else ""
            lines.append(f"    {src_id} -->{edge_label} {tgt_id}")

        # Highlight cycle nodes
        if highlight_cycles and cycle_repos:
            lines.append("    %% Cycle Warnings")
            for cr in sorted(cycle_repos):
                cid = _sanitize_mermaid_id(cr)
                lines.append(f"    style {cid} stroke:#ff0000,stroke-width:2px,fill:#ffebeb")

        return "\n".join(lines)

    def export_dot(self, graph: PortfolioTopologyGraph) -> str:
        """Generate Graphviz DOT digraph markup."""
        lines: list[str] = [
            "digraph PortfolioTopology {",
            "  rankdir=LR;",
            (
                '  node [shape=box, style="rounded,filled", fillcolor="#f8fafc", '
                'fontname="Helvetica", fontsize=10];'
            ),
            '  edge [fontname="Helvetica", fontsize=9, color="#64748b"];',
            "",
        ]

        cycle_repos: set[str] = set()
        for c in graph.cycles:
            cycle_repos.update(c.path)

        for node in graph.nodes:
            fill = "#fee2e2" if node.repo in cycle_repos else "#f8fafc"
            stroke = "#ef4444" if node.repo in cycle_repos else "#cbd5e1"
            lang_str = f"\\n({', '.join(node.languages)})" if node.languages else ""
            n_ca, n_ce, n_inst = node.afferent_coupling, node.efferent_coupling, node.instability
            label = f"{node.repo}{lang_str}\\nCa: {n_ca} | Ce: {n_ce} | I: {n_inst:.2f}"
            lines.append(
                f'  "{node.repo}" [label="{label}", fillcolor="{fill}", color="{stroke}"];'
            )

        lines.append("")
        for edge in graph.edges:
            types_str = ", ".join(edge.edge_types.keys()) if edge.edge_types else "REF"
            label = f"{edge.weight} ({types_str})"
            lines.append(f'  "{edge.source_repo}" -> "{edge.target_repo}" [label="{label}"];')

        lines.append("}")
        return "\n".join(lines)

    @staticmethod
    def export_cytoscape(graph: PortfolioTopologyGraph) -> dict[str, Any]:
        """Generate Cytoscape.js standard JSON elements structure."""
        cycle_repos: set[str] = set()
        for c in graph.cycles:
            cycle_repos.update(c.path)

        nodes: list[dict[str, Any]] = []
        for node in graph.nodes:
            nodes.append(
                {
                    "data": {
                        "id": node.repo,
                        "label": node.repo,
                        "languages": node.languages,
                        "technologies": node.technologies,
                        "signatures": node.total_signatures,
                        "contracts": node.total_contracts,
                        "afferent_coupling": node.afferent_coupling,
                        "efferent_coupling": node.efferent_coupling,
                        "instability": node.instability,
                        "is_leaf": node.is_leaf,
                        "is_root": node.is_root,
                        "in_cycle": node.repo in cycle_repos,
                    }
                }
            )

        edges: list[dict[str, Any]] = []
        for edge in graph.edges:
            edges.append(
                {
                    "data": {
                        "id": f"{edge.source_repo}->{edge.target_repo}",
                        "source": edge.source_repo,
                        "target": edge.target_repo,
                        "weight": edge.weight,
                        "edge_types": edge.edge_types,
                        "symbols": edge.symbols,
                    }
                }
            )

        return {
            "elements": {
                "nodes": nodes,
                "edges": edges,
            },
            "meta": {
                "total_repos": graph.total_repos,
                "total_edges": graph.total_cross_repo_edges,
                "density": graph.density,
                "cycle_count": len(graph.cycles),
            },
        }

    def export(
        self,
        format_type: TopologyExportFormat | str = TopologyExportFormat.MERMAID,
        direction: str = "LR",
        include_internal: bool = False,
        min_weight: int = 1,
    ) -> str | dict[str, Any]:
        """Export portfolio topology in the specified serialization format."""
        graph = self.build_topology(include_internal=include_internal, min_weight=min_weight)
        fmt = (
            format_type
            if isinstance(format_type, TopologyExportFormat)
            else TopologyExportFormat(format_type.lower())
        )

        match fmt:
            case TopologyExportFormat.MERMAID:
                return self.export_mermaid(graph, direction=direction)
            case TopologyExportFormat.DOT:
                return self.export_dot(graph)
            case TopologyExportFormat.CYTOSCAPE:
                return self.export_cytoscape(graph)
            case TopologyExportFormat.JSON:
                return graph.model_dump(mode="json")
