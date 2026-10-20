"""Cross-repository portfolio change intent simulation and automated contract patch generation."""

from __future__ import annotations

import difflib
import logging
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from cortex.config.loader import CortexConfig, load_config
from cortex.models.graph import CodeDependency, DependencyEdgeType
from cortex.models.impact import (
    BlastRadiusSeverity,
    BlastRadiusSimulationReport,
    BlastRadiusSimulationRequest,
)
from cortex.models.intent import (
    ChangeIntentAction,
    ChangeIntentSimulationReport,
    ContractChangeIntent,
    DownstreamCallSite,
    PatchHunk,
    PortfolioChangePlan,
    RepoMigrationPatch,
    SimulationViolation,
)
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.retrieval.impact import ImpactAnalysisEngine
from cortex.retrieval.topology import PortfolioTopologyEngine
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)


def _build_unified_diff(
    file_path: str,
    original_lines: Sequence[str],
    modified_lines: Sequence[str],
) -> str:
    """Generate standard git-apply compatible unified diff from line sequences."""
    diff_generator = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="",
    )
    return "\n".join(diff_generator)


class ChangeIntentEngine:
    """Engine for simulating cross-repo change intents and synthesizing migration patches."""

    def __init__(
        self,
        storage_manager: StorageManager,
        graph_engine: DependencyGraphEngine | None = None,
        impact_engine: ImpactAnalysisEngine | None = None,
        topology_engine: PortfolioTopologyEngine | None = None,
    ) -> None:
        """Initialize engine with storage, graph, impact, and topology engines."""
        self.storage = storage_manager
        self.graph = graph_engine or DependencyGraphEngine(self.storage)
        self.topology = topology_engine or PortfolioTopologyEngine(
            self.storage, graph_engine=self.graph
        )
        self.impact = impact_engine or ImpactAnalysisEngine(
            storage_manager=self.storage,
            graph_engine=self.graph,
            topology_engine=self.topology,
        )

    @classmethod
    def from_config(cls, config: CortexConfig | None = None) -> ChangeIntentEngine:
        """Construct ChangeIntentEngine from configuration or defaults."""
        cfg = config or load_config()
        storage = StorageManager(data_dir=cfg.storage.data_dir)
        graph = DependencyGraphEngine(storage)
        topology = PortfolioTopologyEngine(storage, graph_engine=graph)
        impact = ImpactAnalysisEngine(
            storage_manager=storage,
            graph_engine=graph,
            topology_engine=topology,
        )
        return cls(
            storage_manager=storage,
            graph_engine=graph,
            impact_engine=impact,
            topology_engine=topology,
        )

    def find_downstream_call_sites(
        self,
        intent: ContractChangeIntent,
    ) -> list[DownstreamCallSite]:
        """Locate all downstream consumer call sites and imports referencing the target contract."""
        all_deps = self.storage.get_dependencies(limit=10000)
        target_repo = intent.repo.strip().lower()
        target_sym = intent.target_symbol.strip().lower()
        target_file = intent.file_path.strip().lower().lstrip("/") if intent.file_path else None

        call_sites: list[DownstreamCallSite] = []
        seen_keys: set[tuple[str, str, int]] = set()

        for dep in all_deps:
            # Skip if target_repo doesn't match
            if not self._is_target_repo_match(dep, target_repo):
                continue

            # Check if symbol or file matches
            if not self._is_target_symbol_or_file_match(dep, target_sym, target_file):
                continue

            dedup_key = (dep.source_repo, dep.source_file, dep.line_number)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            call_sites.append(
                DownstreamCallSite(
                    repo=dep.source_repo,
                    file_path=dep.source_file,
                    line_number=dep.line_number,
                    source_symbol=dep.source_symbol or dep.source_file,
                    raw_statement=dep.raw_statement,
                    matched_symbol=intent.target_symbol,
                    edge_type=dep.edge_type,
                )
            )

        return sorted(call_sites, key=lambda s: (s.repo, s.file_path, s.line_number))

    def _is_target_repo_match(self, dep: CodeDependency, target_repo: str) -> bool:
        """Verify whether dependency edge references target repository."""
        dep_target_repo = (dep.target_repo or "").strip().lower()
        if dep_target_repo and dep_target_repo == target_repo:
            return True
        return not dep_target_repo and target_repo in dep.target_module.lower()

    def _is_target_symbol_or_file_match(
        self,
        dep: CodeDependency,
        target_sym: str,
        target_file: str | None,
    ) -> bool:
        """Verify whether dependency edge targets the intended symbol or contract file."""
        dep_sym = dep.target_symbol.strip().lower()
        dep_mod = dep.target_module.strip().lower()
        raw = dep.raw_statement.lower()

        # Direct symbol match
        if target_sym and (
            dep_sym == target_sym
            or dep_sym.endswith(f".{target_sym}")
            or dep_mod.endswith(f".{target_sym}")
            or target_sym in raw
        ):
            return True

        # Target file fallback match
        if target_file and not target_sym:
            stem = target_file.rsplit(".", 1)[0].replace("/", ".")
            if stem in dep_mod:
                return True

        return False

    def detect_simulation_violations(
        self,
        intent: ContractChangeIntent,
        call_sites: Sequence[DownstreamCallSite],
    ) -> list[SimulationViolation]:
        """Detect architectural drift and breaking contract violations for an intended change."""
        violations: list[SimulationViolation] = []
        action = intent.action
        external_sites = [s for s in call_sites if s.repo != intent.repo]

        # 1. Removal without deprecation / ongoing consumer usage
        if action == ChangeIntentAction.REMOVE_CONTRACT:
            if external_sites:
                violations.append(
                    SimulationViolation(
                        severity=BlastRadiusSeverity.CRITICAL,
                        category="breaking_removal",
                        message=(
                            f"Contract '{intent.target_symbol}' removed in '{intent.repo}' "
                            f"is referenced by {len(external_sites)} external call site(s)."
                        ),
                    )
                )
            elif call_sites:
                violations.append(
                    SimulationViolation(
                        severity=BlastRadiusSeverity.HIGH,
                        category="dangling_reference",
                        message=(
                            f"Contract '{intent.target_symbol}' removed in '{intent.repo}' "
                            f"still has {len(call_sites)} internal call site(s)."
                        ),
                    )
                )
            return violations

        # 2. Renames / replacements without valid replacement symbol
        needs_replacement = action in (
            ChangeIntentAction.RENAME_SYMBOL,
            ChangeIntentAction.REPLACE_CONTRACT,
            ChangeIntentAction.CHANGE_ENDPOINT,
        )
        if needs_replacement and (not intent.new_symbol or not intent.new_symbol.strip()):
            violations.append(
                SimulationViolation(
                    severity=BlastRadiusSeverity.CRITICAL,
                    category="unmapped_symbol",
                    message=(
                        f"Intent '{action.value}' for '{intent.target_symbol}' "
                        "does not specify a replacement symbol ('new_symbol')."
                    ),
                )
            )

        # 3. Parameter modifications with potential missing arguments
        if action == ChangeIntentAction.MODIFY_SIGNATURE and intent.param_renames:
            renames_desc = ", ".join(intent.param_renames.keys())
            for site in external_sites:
                if site.edge_type == DependencyEdgeType.CALL:
                    violations.append(
                        SimulationViolation(
                            severity=BlastRadiusSeverity.HIGH,
                            category="signature_divergence",
                            message=f"Call site requires parameter migration ({renames_desc})",
                            call_site=site,
                        )
                    )

        # 4. Deprecations
        if action == ChangeIntentAction.DEPRECATE_CONTRACT:
            for site in external_sites:
                violations.append(
                    SimulationViolation(
                        severity=BlastRadiusSeverity.MEDIUM,
                        category="deprecated_usage",
                        message=(
                            f"Deprecated contract '{intent.target_symbol}' used in '{site.repo}'"
                        ),
                        call_site=site,
                    )
                )

        return violations

    def synthesize_replacement_line(
        self,
        raw_statement: str,
        intent: ContractChangeIntent,
    ) -> str:
        """Synthesize updated line replacement using intent rules."""
        if not raw_statement:
            return raw_statement

        action = intent.action
        old_sym = intent.target_symbol.strip()
        new_sym = (intent.new_symbol or "").strip()

        # Handle renames and contract replacements
        if (
            action
            in (
                ChangeIntentAction.RENAME_SYMBOL,
                ChangeIntentAction.REPLACE_CONTRACT,
            )
            and new_sym
        ):
            # Word boundary regex replacement
            pattern = rf"\b{re.escape(old_sym)}\b"
            replaced = re.sub(pattern, new_sym, raw_statement)
            if replaced != raw_statement:
                return replaced

        # Handle endpoint change (URLs or string routes)
        if action == ChangeIntentAction.CHANGE_ENDPOINT and new_sym and old_sym in raw_statement:
            return raw_statement.replace(old_sym, new_sym)

        # Handle signature parameter renames
        if action == ChangeIntentAction.MODIFY_SIGNATURE and intent.param_renames:
            modified = raw_statement
            for old_p, new_p in intent.param_renames.items():
                p_pattern = rf"\b{re.escape(old_p)}\s*="
                modified = re.sub(p_pattern, f"{new_p}=", modified)
            return modified

        return raw_statement

    def generate_migration_patches(
        self,
        intents: Sequence[ContractChangeIntent],
        call_sites: Sequence[DownstreamCallSite],
        base_repo_paths: Mapping[str, Path] | None = None,
    ) -> list[RepoMigrationPatch]:
        """Synthesize unified diff migration patches across downstream repositories."""
        repo_paths = base_repo_paths or {}
        # Group call sites by repo -> file_path
        sites_by_repo_file: dict[str, dict[str, list[DownstreamCallSite]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for site in call_sites:
            sites_by_repo_file[site.repo][site.file_path].append(site)

        # Map target symbols to intents for quick lookup
        intent_map = {intent.target_symbol.strip(): intent for intent in intents}

        repo_patches: list[RepoMigrationPatch] = []

        for repo, files in sorted(sites_by_repo_file.items()):
            repo_disk_path = repo_paths.get(repo)
            hunks: list[PatchHunk] = []
            diff_sections: list[str] = []
            resolved_count = 0

            for rel_file, sites in sorted(files.items()):
                file_hunks, file_diff, count = self._synthesize_file_patches(
                    repo_disk_path=repo_disk_path,
                    rel_file=rel_file,
                    sites=sites,
                    intent_map=intent_map,
                )
                hunks.extend(file_hunks)
                if file_diff:
                    diff_sections.append(file_diff)
                resolved_count += count

            if hunks:
                repo_patches.append(
                    RepoMigrationPatch(
                        repo=repo,
                        repo_path=str(repo_disk_path) if repo_disk_path else None,
                        total_files=len(files),
                        hunks=hunks,
                        unified_diff="\n\n".join(diff_sections),
                        breaking_changes_resolved=resolved_count,
                    )
                )

        return repo_patches

    def _synthesize_file_patches(
        self,
        repo_disk_path: Path | None,
        rel_file: str,
        sites: Sequence[DownstreamCallSite],
        intent_map: Mapping[str, ContractChangeIntent],
    ) -> tuple[list[PatchHunk], str, int]:
        """Synthesize hunks and unified diff for a single file."""
        full_path = (repo_disk_path / rel_file) if repo_disk_path else None
        disk_content: list[str] | None = None

        if full_path and full_path.is_file():
            try:
                disk_content = full_path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                logger.debug("Failed reading file %s: %s", full_path, exc)

        if disk_content is not None:
            return self._synthesize_from_disk_content(
                rel_file=rel_file,
                disk_content=disk_content,
                sites=sites,
                intent_map=intent_map,
            )

        return self._synthesize_synthetic_patches(
            rel_file=rel_file,
            sites=sites,
            intent_map=intent_map,
        )

    def _synthesize_from_disk_content(
        self,
        rel_file: str,
        disk_content: list[str],
        sites: Sequence[DownstreamCallSite],
        intent_map: Mapping[str, ContractChangeIntent],
    ) -> tuple[list[PatchHunk], str, int]:
        """Synthesize accurate unified diff by mutating actual file content lines."""
        modified_content = list(disk_content)
        hunks: list[PatchHunk] = []
        resolved_count = 0

        for site in sites:
            line_idx = site.line_number - 1
            if line_idx < 0 or line_idx >= len(modified_content):
                continue
            original_line = modified_content[line_idx]
            intent = intent_map.get(site.matched_symbol)
            if not intent:
                continue

            new_line = self.synthesize_replacement_line(original_line, intent)
            if new_line != original_line:
                modified_content[line_idx] = new_line
                resolved_count += 1
                header = f"@@ -{site.line_number},1 +{site.line_number},1 @@"
                hunk_diff = f"{header}\n-{original_line}\n+{new_line}"
                hunks.append(
                    PatchHunk(
                        file_path=rel_file,
                        old_line_start=site.line_number,
                        old_line_count=1,
                        new_line_start=site.line_number,
                        new_line_count=1,
                        diff_text=hunk_diff,
                        original_text=original_line,
                        replacement_text=new_line,
                        explanation=f"Migrated '{site.matched_symbol}'",
                    )
                )

        diff_str = (
            _build_unified_diff(rel_file, disk_content, modified_content)
            if resolved_count > 0
            else ""
        )
        return hunks, diff_str, resolved_count

    def _synthesize_synthetic_patches(
        self,
        rel_file: str,
        sites: Sequence[DownstreamCallSite],
        intent_map: Mapping[str, ContractChangeIntent],
    ) -> tuple[list[PatchHunk], str, int]:
        """Synthesize standalone diff hunks when repo source files are not mounted on disk."""
        hunks: list[PatchHunk] = []
        diff_hunks: list[str] = []
        resolved_count = 0

        for site in sites:
            if not site.raw_statement:
                continue
            intent = intent_map.get(site.matched_symbol)
            if not intent:
                continue

            orig_line = site.raw_statement
            new_line = self.synthesize_replacement_line(orig_line, intent)
            if new_line != orig_line:
                resolved_count += 1
                hunk_header = f"@@ -{site.line_number},1 +{site.line_number},1 @@"
                hunk_body = f"{hunk_header}\n-{orig_line}\n+{new_line}"
                hunks.append(
                    PatchHunk(
                        file_path=rel_file,
                        old_line_start=site.line_number,
                        old_line_count=1,
                        new_line_start=site.line_number,
                        new_line_count=1,
                        diff_text=hunk_body,
                        original_text=orig_line,
                        replacement_text=new_line,
                        explanation=f"Migrated '{site.matched_symbol}'",
                    )
                )
                diff_hunks.append(hunk_body)

        file_diff = ""
        if diff_hunks:
            file_diff = f"--- a/{rel_file}\n+++ b/{rel_file}\n" + "\n".join(diff_hunks)

        return hunks, file_diff, resolved_count

    def simulate_intent(
        self,
        intent_or_plan: ContractChangeIntent | PortfolioChangePlan,
        max_depth: int = 5,
        generate_patches: bool = True,
        base_repo_paths: Mapping[str, Path] | None = None,
    ) -> ChangeIntentSimulationReport:
        """Simulate change plan or intent, evaluate blast radius, and generate migration patches."""
        if isinstance(intent_or_plan, ContractChangeIntent):
            plan = PortfolioChangePlan(
                plan_id=intent_or_plan.intent_id or "plan_single_intent",
                title=f"Intent: {intent_or_plan.action.value} {intent_or_plan.target_symbol}",
                intents=[intent_or_plan],
            )
        else:
            plan = intent_or_plan

        all_call_sites: list[DownstreamCallSite] = []
        all_violations: list[SimulationViolation] = []
        blast_reports: list[BlastRadiusSimulationReport] = []
        affected_repos_set: set[str] = set()

        # Simulate each intent
        for intent in plan.intents:
            call_sites = self.find_downstream_call_sites(intent)
            all_call_sites.extend(call_sites)
            for site in call_sites:
                affected_repos_set.add(site.repo)

            violations = self.detect_simulation_violations(intent, call_sites)
            all_violations.extend(violations)

            # Perform blast-radius simulation
            change_kind = (
                "REMOVED" if intent.action == ChangeIntentAction.REMOVE_CONTRACT else "MODIFIED"
            )
            blast_rep = self.impact.simulate_blast_radius(
                BlastRadiusSimulationRequest(
                    repo=intent.repo,
                    symbol=intent.target_symbol,
                    file_path=intent.file_path,
                    change_kind=change_kind,
                    max_depth=max_depth,
                )
            )
            blast_reports.append(blast_rep)

        # Aggregate risk scores
        max_risk_score = max((b.risk_score for b in blast_reports), default=0.0)
        overall_severity = BlastRadiusSeverity.MINIMAL
        for b in blast_reports:
            if b.risk_level == BlastRadiusSeverity.CRITICAL:
                overall_severity = BlastRadiusSeverity.CRITICAL
                break
            if (
                b.risk_level == BlastRadiusSeverity.HIGH
                and overall_severity != BlastRadiusSeverity.CRITICAL
            ):
                overall_severity = BlastRadiusSeverity.HIGH
            elif b.risk_level == BlastRadiusSeverity.MEDIUM and overall_severity in (
                BlastRadiusSeverity.MINIMAL,
                BlastRadiusSeverity.LOW,
            ):
                overall_severity = BlastRadiusSeverity.MEDIUM
            elif (
                b.risk_level == BlastRadiusSeverity.LOW
                and overall_severity == BlastRadiusSeverity.MINIMAL
            ):
                overall_severity = BlastRadiusSeverity.LOW

        # Recommended staging order: leaves before root
        execution_order: list[str] = []
        if blast_reports:
            for rep in blast_reports:
                for target in rep.recommended_update_order:
                    if target not in execution_order:
                        execution_order.append(target)

        # Synthesize migration patches if requested
        patches: list[RepoMigrationPatch] = []
        if generate_patches and all_call_sites:
            patches = self.generate_migration_patches(
                intents=plan.intents,
                call_sites=all_call_sites,
                base_repo_paths=base_repo_paths,
            )

        return ChangeIntentSimulationReport(
            plan_id=plan.plan_id,
            total_intents=len(plan.intents),
            affected_repos=sorted(affected_repos_set),
            total_call_sites=len(all_call_sites),
            call_sites=all_call_sites,
            violations=all_violations,
            blast_radius_reports=blast_reports,
            overall_risk_level=overall_severity,
            overall_risk_score=max_risk_score,
            patches_available=len(patches) > 0,
            migration_patches=patches,
            execution_order=execution_order,
        )
