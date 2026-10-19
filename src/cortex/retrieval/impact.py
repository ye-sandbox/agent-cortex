"""Cross-repository transitive blast-radius simulation and impact tracing engine."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from collections.abc import Sequence

from cortex.config.loader import CortexConfig, load_config
from cortex.models.graph import CodeDependency
from cortex.models.impact import (
    BlastRadiusSeverity,
    BlastRadiusSimulationReport,
    BlastRadiusSimulationRequest,
    CallerChain,
    CallerChainHop,
    ImpactAdvisory,
    ImpactedNode,
)
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.retrieval.topology import PortfolioTopologyEngine
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)


def _sanitize_sql_str(val: str) -> str:
    """Escape single quotes for LanceDB SQL filter clauses."""
    return val.replace("'", "''")


class ImpactAnalysisEngine:
    """Engine for transitive caller tracing, blast-radius simulation, and agent planning advice."""

    def __init__(
        self,
        storage_manager: StorageManager,
        graph_engine: DependencyGraphEngine | None = None,
        topology_engine: PortfolioTopologyEngine | None = None,
    ) -> None:
        """Initialize engine with storage, graph, and topology query engines."""
        self.storage = storage_manager
        self.graph = graph_engine or DependencyGraphEngine(self.storage)
        self.topology = topology_engine or PortfolioTopologyEngine(
            self.storage, graph_engine=self.graph
        )

    @classmethod
    def from_config(cls, config: CortexConfig | None = None) -> ImpactAnalysisEngine:
        """Construct ImpactAnalysisEngine from resolved config or system defaults."""
        cfg = config or load_config()
        storage = StorageManager(data_dir=cfg.storage.data_dir)
        graph = DependencyGraphEngine(storage)
        topology = PortfolioTopologyEngine(storage, graph_engine=graph)
        return cls(storage_manager=storage, graph_engine=graph, topology_engine=topology)

    def trace_transitive_callers(
        self,
        target_repo: str,
        symbol: str | None = None,
        file_path: str | None = None,
        max_depth: int = 5,
        max_chains: int = 100,
    ) -> tuple[list[CallerChain], list[ImpactedNode], list[list[str]]]:
        """Perform bounded BFS traversal tracing callers transitively across repositories."""
        caller_chains: list[CallerChain] = []
        cycles_detected: list[list[str]] = []
        known_repos = self.graph.get_known_repos()

        # Map (repo, file_path, symbol) to shortest depth and hit count
        node_stats: dict[tuple[str, str, str], dict[str, int]] = {}

        # Initial frontier callers (depth 1)
        direct_callers = self._find_direct_dependents(
            target_repo=target_repo,
            symbol=symbol,
            file_path=file_path,
            known_repos=known_repos,
        )

        if not direct_callers:
            return [], [], []

        # Queue item: (dep, current_chain: list[CallerChainHop], current_path_keys: list[str])
        queue: deque[tuple[CodeDependency, list[CallerChainHop], list[str]]] = deque()

        root_key = f"{target_repo}:{file_path or '*'}:{symbol or '*'}"

        for dep in direct_callers:
            hop_symbol = dep.source_symbol or dep.source_file
            hop = CallerChainHop(
                repo=dep.source_repo,
                file_path=dep.source_file,
                symbol=hop_symbol,
                line_number=dep.line_number,
                edge_type=dep.edge_type,
                depth=1,
            )
            node_key = (dep.source_repo, dep.source_file, hop_symbol)
            if node_key not in node_stats:
                node_stats[node_key] = {"depth": 1, "count": 1}
            else:
                node_stats[node_key]["count"] += 1

            caller_path = [root_key, f"{dep.source_repo}:{dep.source_file}:{hop_symbol}"]
            queue.append((dep, [hop], caller_path))

        seen_chain_signatures: set[str] = set()

        while queue and len(caller_chains) < max_chains:
            current_dep, chain_hops, path_keys = queue.popleft()
            depth = len(chain_hops)

            # Record completed caller chain
            path_str = " -> ".join([f"{h.repo}:{h.file_path}:{h.symbol}" for h in chain_hops])
            if path_str not in seen_chain_signatures:
                seen_chain_signatures.add(path_str)
                repos_in_chain = list(dict.fromkeys([h.repo for h in chain_hops]))
                is_cross = len(repos_in_chain) > 1 or any(h.repo != target_repo for h in chain_hops)
                caller_chains.append(
                    CallerChain(
                        hops=chain_hops,
                        path_str=path_str,
                        depth=depth,
                        cross_repo=is_cross,
                        repos_involved=repos_in_chain,
                    )
                )

            if depth >= max_depth:
                continue

            last_hop = chain_hops[-1]
            # Search upstream callers calling last_hop's symbol or file
            upstream = self._find_direct_dependents(
                target_repo=last_hop.repo,
                symbol=last_hop.symbol if last_hop.symbol != last_hop.file_path else None,
                file_path=last_hop.file_path,
                known_repos=known_repos,
            )

            for next_dep in upstream:
                next_symbol = next_dep.source_symbol or next_dep.source_file
                next_key_str = f"{next_dep.source_repo}:{next_dep.source_file}:{next_symbol}"

                # Cycle check: is next_key_str already in our current traversal path?
                if next_key_str in path_keys:
                    cycle_path = path_keys[path_keys.index(next_key_str) :] + [next_key_str]
                    if cycle_path not in cycles_detected:
                        cycles_detected.append(cycle_path)
                    continue

                next_node_key = (next_dep.source_repo, next_dep.source_file, next_symbol)
                next_depth = depth + 1

                if next_node_key not in node_stats:
                    node_stats[next_node_key] = {"depth": next_depth, "count": 1}
                else:
                    node_stats[next_node_key]["count"] += 1
                    if next_depth < node_stats[next_node_key]["depth"]:
                        node_stats[next_node_key]["depth"] = next_depth

                next_hop = CallerChainHop(
                    repo=next_dep.source_repo,
                    file_path=next_dep.source_file,
                    symbol=next_symbol,
                    line_number=next_dep.line_number,
                    edge_type=next_dep.edge_type,
                    depth=next_depth,
                )
                queue.append(
                    (
                        next_dep,
                        [*chain_hops, next_hop],
                        [*path_keys, next_key_str],
                    )
                )

        # Synthesize impacted nodes
        impacted_nodes: list[ImpactedNode] = [
            ImpactedNode(
                repo=key[0],
                file_path=key[1],
                symbol=key[2],
                depth=stats["depth"],
                direct=(stats["depth"] == 1),
                caller_count=stats["count"],
            )
            for key, stats in node_stats.items()
        ]
        # Sort nodes by depth asc, then repo, then symbol
        impacted_nodes.sort(key=lambda n: (n.depth, n.repo, n.file_path, n.symbol))

        return caller_chains, impacted_nodes, cycles_detected

    def _find_direct_dependents(
        self,
        target_repo: str,
        symbol: str | None = None,
        file_path: str | None = None,
        known_repos: Sequence[str] | None = None,
    ) -> list[CodeDependency]:
        """Query direct incoming dependencies targeting target_repo/symbol/file."""
        all_deps = self.storage.get_dependencies(limit=5000)
        target_clean = target_repo.strip().lower()
        symbol_clean = symbol.strip().lower() if symbol and symbol.strip() else None
        file_clean = (
            file_path.strip().lower().lstrip("/") if file_path and file_path.strip() else None
        )

        repos = list(known_repos) if known_repos is not None else self.graph.get_known_repos()
        matching_deps: list[CodeDependency] = []

        for dep in all_deps:
            # 1. Check target_repo match
            dep_target_repo = (dep.target_repo or "").strip().lower()

            if not dep_target_repo:
                target_mod = dep.target_module.strip().lower()
                for r in repos:
                    r_clean = r.strip().lower()
                    if (
                        target_mod == r_clean
                        or target_mod.startswith(f"{r_clean}.")
                        or target_mod.startswith(f"{r_clean}/")
                        or f"/{r_clean}/" in target_mod
                        or target_mod.replace("-", "_") == r_clean.replace("-", "_")
                    ):
                        dep_target_repo = r_clean
                        break

            # If target repo specified, must match resolved target repo or module
            if dep_target_repo and dep_target_repo != target_clean:
                continue

            if not dep_target_repo and target_clean not in dep.target_module.lower():
                continue

            # 2. Check symbol match
            if symbol_clean:
                target_sym = dep.target_symbol.strip().lower()
                target_mod = dep.target_module.strip().lower()
                if not (
                    target_sym == symbol_clean
                    or target_sym.endswith(f".{symbol_clean}")
                    or target_mod.endswith(f".{symbol_clean}")
                    or symbol_clean in dep.raw_statement.lower()
                ):
                    continue

            # 3. Check file match (if specified and no symbol, or verifying module name)
            if file_clean and not symbol_clean:
                # E.g. target_module matches path or file
                stem = file_clean.rsplit(".", 1)[0].replace("/", ".")
                if stem not in dep.target_module.lower():
                    continue

            matching_deps.append(dep)

        return matching_deps

    def calculate_risk_score(
        self,
        target_repo: str,
        change_kind: str,
        impacted_nodes: Sequence[ImpactedNode],
        cycles_detected: Sequence[Sequence[str]],
        afferent_coupling: int = 0,
    ) -> tuple[float, BlastRadiusSeverity]:
        """Compute normalized architectural risk score (0.0 to 100.0) and severity category."""
        kind_multipliers = {
            "REMOVED": 1.0,
            "MODIFIED": 0.85,
            "DEPRECATED": 0.5,
            "ADDED": 0.15,
        }
        multiplier = kind_multipliers.get(change_kind.upper().strip(), 0.75)

        direct_callers = sum(1 for n in impacted_nodes if n.direct)
        transitive_callers = sum(1 for n in impacted_nodes if not n.direct)

        external_repos = {n.repo for n in impacted_nodes if n.repo != target_repo}
        num_external = len(external_repos)

        unique_files = {f"{n.repo}:{n.file_path}" for n in impacted_nodes}
        num_files = len(unique_files)

        # Base components
        caller_score = (direct_callers * 5.0) + (transitive_callers * 2.5)
        external_repo_score = min(40.0, num_external * 15.0)
        file_spread_score = min(20.0, num_files * 2.0)
        cycle_penalty = 15.0 if cycles_detected else 0.0
        coupling_weight = min(15.0, afferent_coupling * 3.0)

        raw_score = multiplier * (
            caller_score + external_repo_score + file_spread_score + cycle_penalty + coupling_weight
        )
        normalized_score = round(max(0.0, min(100.0, raw_score)), 1)

        # Determine severity level
        is_breaking_kind = change_kind.upper() in ("REMOVED", "MODIFIED")
        if (num_external >= 2 and is_breaking_kind) or normalized_score >= 70.0:
            severity = BlastRadiusSeverity.CRITICAL
        elif (num_external >= 1 and is_breaking_kind) or normalized_score >= 45.0:
            severity = BlastRadiusSeverity.HIGH
        elif normalized_score >= 20.0:
            severity = BlastRadiusSeverity.MEDIUM
        elif normalized_score > 5.0:
            severity = BlastRadiusSeverity.LOW
        else:
            severity = BlastRadiusSeverity.MINIMAL

        return normalized_score, severity

    def generate_advisories(
        self,
        target_repo: str,
        target_symbol: str | None,
        change_kind: str,
        impacted_nodes: Sequence[ImpactedNode],
        cycles: Sequence[Sequence[str]],
        severity: BlastRadiusSeverity,
    ) -> list[ImpactAdvisory]:
        """Synthesize concrete, actionable planning advisories for Dev Trinity autonomous agents."""
        advisories: list[ImpactAdvisory] = []
        external_repos = sorted(set(n.repo for n in impacted_nodes if n.repo != target_repo))

        sym_display = f"'{target_symbol}'" if target_symbol else f"contracts in '{target_repo}'"

        # 1. Breaking Cross-Repository Contract Advisory
        if external_repos and change_kind.upper() in ("REMOVED", "MODIFIED"):
            repo_list = ", ".join(f"'{r}'" for r in external_repos)
            advisories.append(
                ImpactAdvisory(
                    severity=BlastRadiusSeverity.CRITICAL,
                    category="breaking_contract",
                    message=(
                        f"Proposed change ({change_kind.upper()}) to {sym_display} directly "
                        f"impacts {len(external_repos)} external portfolio repositories: "
                        f"{repo_list}."
                    ),
                    recommended_action=(
                        "Implement an expand-and-contract phase: preserve backward-compatible "
                        "interface/shim in the target repo before deprecating or updating callers."
                    ),
                )
            )

        # 2. Cycle Risk Advisory
        if cycles:
            sample_cycle = " -> ".join(cycles[0])
            advisories.append(
                ImpactAdvisory(
                    severity=BlastRadiusSeverity.HIGH,
                    category="cycle_risk",
                    message=(
                        f"Transitive circular dependency detected: {sample_cycle}. Changes to "
                        f"{sym_display} may cause recursive regression loops."
                    ),
                    recommended_action=(
                        "Refactor circular boundary or introduce an architectural interface "
                        "bridge to decouple cyclic callers before modifying."
                    ),
                )
            )

        # 3. Migration Sequence Advisory
        if impacted_nodes:
            max_depth = max(n.depth for n in impacted_nodes)
            advisories.append(
                ImpactAdvisory(
                    severity=severity,
                    category="migration_order",
                    message=(
                        f"Blast radius spans {len(impacted_nodes)} caller site(s) across "
                        f"{max_depth} transitive hop level(s)."
                    ),
                    recommended_action=(
                        "Stage modifications in topological order: update deepest leaf consumer "
                        "callers first, verify backward compatibility, and refactor target last."
                    ),
                )
            )

        # 4. Regression Test Scope Advisory
        test_repos = sorted(set([target_repo, *external_repos]))
        advisories.append(
            ImpactAdvisory(
                severity=BlastRadiusSeverity.MEDIUM,
                category="test_scope",
                message=f"Regression test coverage required across {len(test_repos)} repositories.",
                recommended_action=(
                    f"Execute targeted automated test suites for: {', '.join(test_repos)}."
                ),
            )
        )

        return advisories

    def simulate_blast_radius(
        self,
        request: BlastRadiusSimulationRequest,
    ) -> BlastRadiusSimulationReport:
        """Run complete blast-radius simulation and synthesize planning report."""
        target_repo = request.repo.strip()
        target_symbol = request.symbol.strip() if request.symbol else None
        target_file = request.file_path.strip() if request.file_path else None
        change_kind = request.change_kind.upper().strip()

        # 1. Transitive caller traversal
        chains, nodes, cycles = self.trace_transitive_callers(
            target_repo=target_repo,
            symbol=target_symbol,
            file_path=target_file,
            max_depth=request.max_depth,
        )

        # 2. Retrieve target repo coupling metrics
        afferent_coupling = 0
        try:
            topo = self.topology.build_topology(min_weight=1)
            for node in topo.nodes:
                if node.repo == target_repo:
                    afferent_coupling = node.afferent_coupling
                    break
        except Exception as exc:
            logger.debug(
                "Could not compute topology coupling metrics for '%s': %s", target_repo, exc
            )

        # 3. Compute risk score
        risk_score, severity = self.calculate_risk_score(
            target_repo=target_repo,
            change_kind=change_kind,
            impacted_nodes=nodes,
            cycles_detected=cycles,
            afferent_coupling=afferent_coupling,
        )

        # 4. Advisories
        advisories = self.generate_advisories(
            target_repo=target_repo,
            target_symbol=target_symbol,
            change_kind=change_kind,
            impacted_nodes=nodes,
            cycles=cycles,
            severity=severity,
        )

        # 5. Recommended update order (deepest leaf nodes first, then down to root)
        nodes_by_depth = defaultdict(list)
        for n in nodes:
            nodes_by_depth[n.depth].append(f"{n.repo}:{n.file_path}::{n.symbol}")

        staging_order: list[str] = []
        for d in sorted(nodes_by_depth.keys(), reverse=True):
            for item in sorted(nodes_by_depth[d]):
                staging_order.append(f"[Hop {d}] {item}")

        root_target_str = f"{target_repo}:{target_file or '*'}" + (
            f"::{target_symbol}" if target_symbol else ""
        )
        staging_order.append(f"[Root Target] {root_target_str}")

        # 6. Test suites
        all_repos = sorted(set([target_repo, *(n.repo for n in nodes)]))
        suggested_tests = [f"{r}: uv run pytest tests/" for r in all_repos]

        impacted_repos = sorted(set(n.repo for n in nodes))
        impacted_files = sorted(set(f"{n.repo}:{n.file_path}" for n in nodes))

        return BlastRadiusSimulationReport(
            target_repo=target_repo,
            target_symbol=target_symbol,
            target_file=target_file,
            change_kind=change_kind,
            max_depth=request.max_depth,
            risk_score=risk_score,
            risk_level=severity,
            total_impacted_repos=len(impacted_repos),
            impacted_repos=impacted_repos,
            total_impacted_files=len(impacted_files),
            impacted_files=impacted_files,
            total_impacted_symbols=len(nodes),
            impacted_nodes=nodes,
            caller_chains=chains,
            cycles_detected=cycles,
            advisories=advisories,
            recommended_update_order=staging_order,
            suggested_test_suites=suggested_tests,
        )
