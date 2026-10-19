"""Cross-repository architectural contract drift detection and alerting engine."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import yaml

from cortex.config.loader import CortexConfig, RepositorySourceConfig, load_config
from cortex.ingestion.git import get_head_commit, is_git_repository, run_git, scan_git_drift
from cortex.ingestion.manifest import ManifestManager
from cortex.models.chunk import DocumentChunk
from cortex.models.drift import (
    ChangeKind,
    ContractDriftAlert,
    ContractDriftReport,
    ContractType,
    DriftSeverity,
)
from cortex.models.graph import CodeSignature
from cortex.parsers.code.extractor import extract_code_ast
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)

SUPPORTED_OPENAPI_METHODS = ("get", "post", "put", "delete", "patch", "options", "head", "trace")


def _is_signature_breaking(old_sig: str, new_sig: str) -> bool:
    """Heuristic to evaluate whether a signature modification is potentially breaking."""
    if old_sig.strip() == new_sig.strip():
        return False

    # Extract parameter section inside parentheses
    old_match = re.search(r"\((.*?)\)", old_sig, re.DOTALL)
    new_match = re.search(r"\((.*?)\)", new_sig, re.DOTALL)
    if not old_match or not new_match:
        return True

    old_params_str = old_match.group(1).strip()
    new_params_str = new_match.group(1).strip()
    if old_params_str == new_params_str:
        # Parameter list identical, return type or qualifier changed
        return True

    old_params = [p.strip() for p in old_params_str.split(",") if p.strip() and p.strip() != "self"]
    new_params = [p.strip() for p in new_params_str.split(",") if p.strip() and p.strip() != "self"]

    # Parameter count decreased (existing params removed) -> Breaking
    if len(new_params) < len(old_params):
        return True

    # Check newly added parameters
    if len(new_params) > len(old_params):
        # If any newly added parameter lacks a default value or optional marker -> Breaking
        for p in new_params[len(old_params) :]:
            is_optional = "=" in p or "?:" in p or "None" in p or "optional" in p.lower()
            if not is_optional:
                return True

    return False


class ContractDriftEngine:
    """Detects, analyzes, and correlates architectural contract drift across repositories."""

    def __init__(
        self,
        storage_manager: StorageManager,
        manifest_manager: ManifestManager | None = None,
        graph_engine: DependencyGraphEngine | None = None,
    ) -> None:
        """Initialize engine with storage, manifest, and graph query engines."""
        self.storage = storage_manager
        self.manifest = manifest_manager or ManifestManager(self.storage.data_dir / "manifest.json")
        self.graph = graph_engine or DependencyGraphEngine(self.storage)

    @classmethod
    def from_config(cls, config: CortexConfig | None = None) -> ContractDriftEngine:
        """Construct ContractDriftEngine from resolved config or system defaults."""
        cfg = config or load_config()
        storage = StorageManager(data_dir=cfg.storage.data_dir)
        manifest = ManifestManager(manifest_path=storage.data_dir / "manifest.json")
        graph = DependencyGraphEngine(storage)
        return cls(storage_manager=storage, manifest_manager=manifest, graph_engine=graph)

    def diff_openapi(
        self,
        repo: str,
        file_path: str,
        old_content: str | None,
        new_content: str | None,
    ) -> list[ContractDriftAlert]:
        """Diff two OpenAPI specifications and produce contract drift alerts."""
        alerts: list[ContractDriftAlert] = []
        old_spec = self._parse_json_or_yaml(old_content)
        new_spec = self._parse_json_or_yaml(new_content)

        old_paths = (
            cast(dict[str, Any], old_spec.get("paths", {})) if isinstance(old_spec, dict) else {}
        )
        new_paths = (
            cast(dict[str, Any], new_spec.get("paths", {})) if isinstance(new_spec, dict) else {}
        )

        # 1. Inspect existing / deleted endpoints
        for path_str, path_obj in old_paths.items():
            if not isinstance(path_obj, dict):
                continue
            new_path_obj = new_paths.get(path_str)
            for m in SUPPORTED_OPENAPI_METHODS:
                if m not in path_obj or not isinstance(path_obj[m], dict):
                    continue
                old_op = cast(dict[str, Any], path_obj[m])
                op_id = f"{m.upper()} {path_str}"

                if not isinstance(new_path_obj, dict) or m not in new_path_obj:
                    # Endpoint removed
                    alert_id = ContractDriftAlert.build_id(
                        repo, file_path, ContractType.OPENAPI, ChangeKind.REMOVED, op_id
                    )
                    alerts.append(
                        ContractDriftAlert(
                            id=alert_id,
                            repo=repo,
                            file_path=file_path,
                            contract_type=ContractType.OPENAPI,
                            change_kind=ChangeKind.REMOVED,
                            severity=DriftSeverity.HIGH,
                            identifier=op_id,
                            summary=f"OpenAPI endpoint '{op_id}' was removed",
                            details=(
                                "Endpoint existed in previous contract but was deleted "
                                f"in {file_path}"
                            ),
                        )
                    )
                    continue

                new_op = cast(dict[str, Any], new_path_obj[m])
                alerts.extend(self._diff_openapi_operation(repo, file_path, op_id, old_op, new_op))

        # 2. Inspect newly added endpoints
        for path_str, path_obj in new_paths.items():
            if not isinstance(path_obj, dict):
                continue
            old_path_obj = old_paths.get(path_str)
            for m in SUPPORTED_OPENAPI_METHODS:
                if m not in path_obj or not isinstance(path_obj[m], dict):
                    continue
                if isinstance(old_path_obj, dict) and m in old_path_obj:
                    continue
                op_id = f"{m.upper()} {path_str}"
                alert_id = ContractDriftAlert.build_id(
                    repo, file_path, ContractType.OPENAPI, ChangeKind.ADDED, op_id
                )
                alerts.append(
                    ContractDriftAlert(
                        id=alert_id,
                        repo=repo,
                        file_path=file_path,
                        contract_type=ContractType.OPENAPI,
                        change_kind=ChangeKind.ADDED,
                        severity=DriftSeverity.INFO,
                        identifier=op_id,
                        summary=f"OpenAPI endpoint '{op_id}' was added",
                        details=f"New endpoint declared in {file_path}",
                    )
                )

        return alerts

    def _diff_openapi_operation(
        self,
        repo: str,
        file_path: str,
        op_id: str,
        old_op: dict[str, Any],
        new_op: dict[str, Any],
    ) -> list[ContractDriftAlert]:
        """Detect parameter modifications and deprecations within an OpenAPI operation."""
        alerts: list[ContractDriftAlert] = []

        # Deprecation flag
        if not old_op.get("deprecated") and new_op.get("deprecated"):
            alert_id = ContractDriftAlert.build_id(
                repo, file_path, ContractType.OPENAPI, ChangeKind.DEPRECATED, f"{op_id}_deprecated"
            )
            alerts.append(
                ContractDriftAlert(
                    id=alert_id,
                    repo=repo,
                    file_path=file_path,
                    contract_type=ContractType.OPENAPI,
                    change_kind=ChangeKind.DEPRECATED,
                    severity=DriftSeverity.MEDIUM,
                    identifier=op_id,
                    summary=f"OpenAPI endpoint '{op_id}' marked deprecated",
                    details=f"Endpoint tagged deprecated=true in {file_path}",
                )
            )

        old_params = {
            str(p.get("name")): p
            for p in old_op.get("parameters", [])
            if isinstance(p, dict) and "name" in p
        }
        new_params = {
            str(p.get("name")): p
            for p in new_op.get("parameters", [])
            if isinstance(p, dict) and "name" in p
        }

        # Check for newly added required parameters (breaking change)
        for p_name, p_obj in new_params.items():
            if p_name not in old_params and p_obj.get("required") is True:
                alert_id = ContractDriftAlert.build_id(
                    repo,
                    file_path,
                    ContractType.OPENAPI,
                    ChangeKind.MODIFIED,
                    f"{op_id}_req_{p_name}",
                )
                alerts.append(
                    ContractDriftAlert(
                        id=alert_id,
                        repo=repo,
                        file_path=file_path,
                        contract_type=ContractType.OPENAPI,
                        change_kind=ChangeKind.MODIFIED,
                        severity=DriftSeverity.HIGH,
                        identifier=op_id,
                        summary=f"New required parameter '{p_name}' added to '{op_id}'",
                        details=(
                            f"Callers must now supply required parameter '{p_name}' "
                            f"(in: {p_obj.get('in')})"
                        ),
                    )
                )

        # Check for deleted parameters
        for p_name, _p_obj in old_params.items():
            if p_name not in new_params:
                alert_id = ContractDriftAlert.build_id(
                    repo,
                    file_path,
                    ContractType.OPENAPI,
                    ChangeKind.MODIFIED,
                    f"{op_id}_del_{p_name}",
                )
                alerts.append(
                    ContractDriftAlert(
                        id=alert_id,
                        repo=repo,
                        file_path=file_path,
                        contract_type=ContractType.OPENAPI,
                        change_kind=ChangeKind.MODIFIED,
                        severity=DriftSeverity.MEDIUM,
                        identifier=op_id,
                        summary=f"Parameter '{p_name}' removed from '{op_id}'",
                        details=f"Parameter was removed from operation in {file_path}",
                    )
                )

        return alerts

    def diff_compose(
        self,
        repo: str,
        file_path: str,
        old_content: str | None,
        new_content: str | None,
    ) -> list[ContractDriftAlert]:
        """Diff two Docker Compose manifests and produce infrastructure contract alerts."""
        alerts: list[ContractDriftAlert] = []
        old_spec = self._parse_json_or_yaml(old_content)
        new_spec = self._parse_json_or_yaml(new_content)

        old_svcs = (
            cast(dict[str, Any], old_spec.get("services", {})) if isinstance(old_spec, dict) else {}
        )
        new_svcs = (
            cast(dict[str, Any], new_spec.get("services", {})) if isinstance(new_spec, dict) else {}
        )

        # 1. Removed services
        for svc_name, svc_obj in old_svcs.items():
            svc_ident = f"services.{svc_name}"
            if svc_name not in new_svcs:
                alert_id = ContractDriftAlert.build_id(
                    repo, file_path, ContractType.COMPOSE, ChangeKind.REMOVED, svc_ident
                )
                alerts.append(
                    ContractDriftAlert(
                        id=alert_id,
                        repo=repo,
                        file_path=file_path,
                        contract_type=ContractType.COMPOSE,
                        change_kind=ChangeKind.REMOVED,
                        severity=DriftSeverity.HIGH,
                        identifier=svc_ident,
                        summary=f"Docker Compose service '{svc_name}' was removed",
                        details=f"Service existed previously but was deleted from {file_path}",
                    )
                )
                continue

            new_svc = new_svcs.get(svc_name)
            if isinstance(svc_obj, dict) and isinstance(new_svc, dict):
                alerts.extend(
                    self._diff_compose_service(repo, file_path, svc_name, svc_obj, new_svc)
                )

        # 2. Added services
        for svc_name in new_svcs:
            if svc_name not in old_svcs:
                svc_ident = f"services.{svc_name}"
                alert_id = ContractDriftAlert.build_id(
                    repo, file_path, ContractType.COMPOSE, ChangeKind.ADDED, svc_ident
                )
                alerts.append(
                    ContractDriftAlert(
                        id=alert_id,
                        repo=repo,
                        file_path=file_path,
                        contract_type=ContractType.COMPOSE,
                        change_kind=ChangeKind.ADDED,
                        severity=DriftSeverity.INFO,
                        identifier=svc_ident,
                        summary=f"Docker Compose service '{svc_name}' was added",
                        details=f"New service declared in {file_path}",
                    )
                )

        return alerts

    def _diff_compose_service(
        self,
        repo: str,
        file_path: str,
        svc_name: str,
        old_svc: dict[str, Any],
        new_svc: dict[str, Any],
    ) -> list[ContractDriftAlert]:
        """Inspect port bindings and environment changes for a compose service."""
        alerts: list[ContractDriftAlert] = []
        svc_ident = f"services.{svc_name}"

        # Check removed ports
        old_ports = set(str(p) for p in old_svc.get("ports", []) if p)
        new_ports = set(str(p) for p in new_svc.get("ports", []) if p)
        removed_ports = old_ports - new_ports
        for port in sorted(removed_ports):
            alert_id = ContractDriftAlert.build_id(
                repo,
                file_path,
                ContractType.COMPOSE,
                ChangeKind.MODIFIED,
                f"{svc_ident}_port_{port}",
            )
            alerts.append(
                ContractDriftAlert(
                    id=alert_id,
                    repo=repo,
                    file_path=file_path,
                    contract_type=ContractType.COMPOSE,
                    change_kind=ChangeKind.MODIFIED,
                    severity=DriftSeverity.HIGH,
                    identifier=svc_ident,
                    summary=f"Port binding '{port}' removed from service '{svc_name}'",
                    details=f"External network mapping '{port}' is no longer exposed",
                )
            )

        return alerts

    def diff_signatures(
        self,
        repo: str,
        file_path: str,
        old_signatures: Sequence[CodeSignature],
        new_signatures: Sequence[CodeSignature],
    ) -> list[ContractDriftAlert]:
        """Diff code signatures extracted from two revisions of a source file."""
        alerts: list[ContractDriftAlert] = []
        old_map = {f"{s.kind}:{s.identifier}": s for s in old_signatures if s.exported}
        new_map = {f"{s.kind}:{s.identifier}": s for s in new_signatures if s.exported}

        # 1. Removed signatures
        for key, old_sig in old_map.items():
            if key not in new_map:
                alert_id = ContractDriftAlert.build_id(
                    repo,
                    file_path,
                    ContractType.CODE_SIGNATURE,
                    ChangeKind.REMOVED,
                    old_sig.identifier,
                )
                alerts.append(
                    ContractDriftAlert(
                        id=alert_id,
                        repo=repo,
                        file_path=file_path,
                        contract_type=ContractType.CODE_SIGNATURE,
                        change_kind=ChangeKind.REMOVED,
                        severity=DriftSeverity.HIGH,
                        identifier=old_sig.identifier,
                        summary=f"Exported {old_sig.kind} '{old_sig.identifier}' was removed",
                        details=f"Previous declaration: {old_sig.signature}",
                    )
                )
                continue

            new_sig = new_map[key]
            if old_sig.signature.strip() != new_sig.signature.strip():
                is_breaking = _is_signature_breaking(old_sig.signature, new_sig.signature)
                sev = DriftSeverity.HIGH if is_breaking else DriftSeverity.MEDIUM
                alert_id = ContractDriftAlert.build_id(
                    repo,
                    file_path,
                    ContractType.CODE_SIGNATURE,
                    ChangeKind.MODIFIED,
                    new_sig.identifier,
                )
                alerts.append(
                    ContractDriftAlert(
                        id=alert_id,
                        repo=repo,
                        file_path=file_path,
                        contract_type=ContractType.CODE_SIGNATURE,
                        change_kind=ChangeKind.MODIFIED,
                        severity=sev,
                        identifier=new_sig.identifier,
                        summary=(
                            f"Exported {new_sig.kind} '{new_sig.identifier}' signature modified"
                        ),
                        details=f"Old: {old_sig.signature}\nNew: {new_sig.signature}",
                    )
                )

        # 2. Added signatures
        for key, new_sig in new_map.items():
            if key not in old_map:
                alert_id = ContractDriftAlert.build_id(
                    repo,
                    file_path,
                    ContractType.CODE_SIGNATURE,
                    ChangeKind.ADDED,
                    new_sig.identifier,
                )
                alerts.append(
                    ContractDriftAlert(
                        id=alert_id,
                        repo=repo,
                        file_path=file_path,
                        contract_type=ContractType.CODE_SIGNATURE,
                        change_kind=ChangeKind.ADDED,
                        severity=DriftSeverity.INFO,
                        identifier=new_sig.identifier,
                        summary=f"Exported {new_sig.kind} '{new_sig.identifier}' was added",
                        details=f"New declaration: {new_sig.signature}",
                    )
                )

        return alerts

    def resolve_cross_repo_impact(
        self,
        alerts: Sequence[ContractDriftAlert],
    ) -> list[ContractDriftAlert]:
        """Correlate contract breaking changes with external portfolio dependents."""
        resolved: list[ContractDriftAlert] = []
        known_repos = self.graph.get_known_repos()

        for alert in alerts:
            # Only breaking or warning alerts warrant cross-repo dependency auditing
            if not alert.severity.is_breaking and alert.severity != DriftSeverity.MEDIUM:
                resolved.append(alert)
                continue

            sym_query = alert.identifier.strip()
            # If OpenAPI operation 'GET /deals', check path or operation ID
            if " " in sym_query:
                sym_query = sym_query.split(" ", 1)[1]

            dependents_res = self.graph.get_dependents(symbol=sym_query, limit=100)
            cross_links = [
                d
                for d in dependents_res.dependents
                if d.source_repo.lower().strip() != alert.repo.lower().strip()
            ]

            # Also check direct module/package references across portfolio
            if not cross_links and alert.repo in known_repos:
                dep_res = self.storage.get_dependencies(limit=500)
                r_clean = alert.repo.lower().strip()
                for dep in dep_res:
                    if dep.source_repo.lower().strip() == r_clean:
                        continue
                    mod = dep.target_module.lower().strip()
                    matches_mod = (
                        mod == r_clean
                        or mod.startswith(f"{r_clean}.")
                        or mod.startswith(f"{r_clean}/")
                        or f"/{r_clean}/" in mod
                    )
                    matches_sym = (
                        not dep.target_symbol
                        or dep.target_symbol.lower() == sym_query.lower()
                        or sym_query.lower() in dep.raw_statement.lower()
                    )
                    if matches_mod and matches_sym:
                        cross_links.append(dep)

            if not cross_links:
                resolved.append(alert)
                continue

            impacted_repos = sorted(set(d.source_repo for d in cross_links))
            impacted_callers = [
                f"{d.source_repo}:{d.source_file}:{d.line_number}" for d in cross_links[:10]
            ]

            # Elevate severity to CRITICAL for cross-repository contract breaks
            new_severity = DriftSeverity.CRITICAL
            repo_list_str = ", ".join(impacted_repos)
            new_summary = (
                f"[BREAKING CROSS-REPO] {alert.summary} "
                f"(impacts {len(impacted_repos)} repo(s): {repo_list_str})"
            )

            escalated = ContractDriftAlert(
                id=alert.id,
                repo=alert.repo,
                file_path=alert.file_path,
                contract_type=alert.contract_type,
                change_kind=alert.change_kind,
                severity=new_severity,
                identifier=alert.identifier,
                summary=new_summary,
                details=alert.details,
                impacted_repos=impacted_repos,
                impacted_callers=impacted_callers,
            )
            resolved.append(escalated)

        return resolved

    def analyze_file_diff(
        self,
        repo: str,
        file_path: str,
        old_content: str | None,
        new_content: str | None,
    ) -> list[ContractDriftAlert]:
        """Dispatch content diff to specialized OpenAPI, Compose, or Code AST analyzer."""
        lower_path = file_path.lower()
        if (
            lower_path.endswith(("openapi.json", "openapi.yaml", "openapi.yml"))
            or "swagger" in lower_path
        ):
            return self.diff_openapi(repo, file_path, old_content, new_content)

        if lower_path.endswith(
            ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
        ):
            return self.diff_compose(repo, file_path, old_content, new_content)

        if lower_path.endswith((".py", ".ts", ".tsx", ".mts", ".cts", ".go")):
            old_sigs = (
                extract_code_ast(old_content or "", repo, file_path)[0] if old_content else []
            )
            new_sigs = (
                extract_code_ast(new_content or "", repo, file_path)[0] if new_content else []
            )
            return self.diff_signatures(repo, file_path, old_sigs, new_sigs)

        return []

    def analyze_repo_drift(
        self,
        repo_path: Path | str,
        repo_name: str | None = None,
        base_commit: str | None = None,
        target_commit: str | None = None,
    ) -> ContractDriftReport:
        """Scan repository for architectural contract drift against base commit or indexed state."""
        path = Path(repo_path).expanduser().resolve()
        name = repo_name.strip() if repo_name and repo_name.strip() else path.name

        if not is_git_repository(path):
            logger.warning("Path '%s' is not a git repository; skipping drift analysis", path)
            return ContractDriftReport(repo=name)

        head_commit = target_commit or get_head_commit(path)
        starting_commit = base_commit
        if starting_commit is None:
            repo_state = self.manifest.get_repo_state(name)
            if repo_state is not None:
                starting_commit = repo_state.last_synced_commit

        try:
            drift = scan_git_drift(
                repo_path=path,
                base_commit=starting_commit,
                target_commit=head_commit,
                repo_name=name,
            )
        except Exception as exc:
            logger.warning("Failed to scan git drift for '%s': %s", name, exc)
            return ContractDriftReport(
                repo=name, base_commit=starting_commit, target_commit=head_commit
            )

        if not drift.has_changes:
            return ContractDriftReport(
                repo=name, base_commit=starting_commit, target_commit=head_commit
            )

        raw_alerts: list[ContractDriftAlert] = []

        # 1. Modified files
        for change in drift.modified_files:
            file_disk = path / change.path
            new_text = (
                file_disk.read_text(encoding="utf-8", errors="replace")
                if file_disk.is_file()
                else None
            )
            old_text = (
                run_git(path, ["show", f"{starting_commit}:{change.path}"], check=False)
                if starting_commit
                else None
            )
            raw_alerts.extend(self.analyze_file_diff(name, change.path, old_text, new_text))

        # 2. Deleted files
        for change in drift.deleted_files:
            old_text = (
                run_git(path, ["show", f"{starting_commit}:{change.path}"], check=False)
                if starting_commit
                else None
            )
            raw_alerts.extend(self.analyze_file_diff(name, change.path, old_text, None))

        # 3. Added files
        for change in drift.added_files:
            file_disk = path / change.path
            new_text = (
                file_disk.read_text(encoding="utf-8", errors="replace")
                if file_disk.is_file()
                else None
            )
            raw_alerts.extend(self.analyze_file_diff(name, change.path, None, new_text))

        # Correlate with portfolio-wide dependencies
        correlated = self.resolve_cross_repo_impact(raw_alerts)
        return ContractDriftReport.from_alerts(
            correlated,
            repo=name,
            base_commit=starting_commit,
            target_commit=head_commit,
        )

    def analyze_portfolio_drift(
        self,
        sources: Sequence[RepositorySourceConfig],
    ) -> ContractDriftReport:
        """Scan all configured repository sources and synthesize a portfolio drift report."""
        combined_alerts: list[ContractDriftAlert] = []
        for src in sources:
            if not src.enabled:
                continue
            rep = self.analyze_repo_drift(
                repo_path=src.path,
                repo_name=src.get_repo_name(),
            )
            combined_alerts.extend(rep.alerts)

        return ContractDriftReport.from_alerts(combined_alerts)

    def analyze_storage_drift(
        self,
        repo_name: str,
        new_chunks: Sequence[DocumentChunk],
        new_signatures: Sequence[CodeSignature],
    ) -> list[ContractDriftAlert]:
        """Detect drift by comparing incoming parsed items against currently stored records."""
        safe_repo = repo_name.replace("'", "''")
        old_contracts = self.storage.get_repo_contracts(repo=repo_name, limit=5000)
        old_sigs = self.storage.get_signatures(where=f"repo = '{safe_repo}'", limit=5000)

        alerts: list[ContractDriftAlert] = []

        # Check removed contract chunks (OpenAPI and Docker Compose)
        new_chunk_ids = {c.id for c in new_chunks}
        for old in old_contracts:
            old_id = str(old.get("id", ""))
            old_file = str(old.get("file_path", ""))
            old_cat = str(old.get("category", ""))
            if old_id and old_id not in new_chunk_ids:
                c_type = (
                    ContractType.OPENAPI if "openapi" in old_file.lower() else ContractType.COMPOSE
                )
                ident = str(old.get("breadcrumb", old_id)).split(">")[-1].strip()
                alert_id = ContractDriftAlert.build_id(
                    repo_name, old_file, c_type, ChangeKind.REMOVED, ident
                )
                alerts.append(
                    ContractDriftAlert(
                        id=alert_id,
                        repo=repo_name,
                        file_path=old_file,
                        contract_type=c_type,
                        change_kind=ChangeKind.REMOVED,
                        severity=DriftSeverity.HIGH,
                        identifier=ident,
                        summary=f"Contract '{ident}' was removed from storage",
                        details=f"Was indexed under {old_cat} in {old_file}",
                    )
                )

        # Check code signatures
        sig_alerts = self.diff_signatures(
            repo=repo_name,
            file_path="src",
            old_signatures=old_sigs,
            new_signatures=new_signatures,
        )
        alerts.extend(sig_alerts)

        return self.resolve_cross_repo_impact(alerts)

    def _parse_json_or_yaml(self, text: str | None) -> dict[str, Any]:
        """Safely decode JSON or YAML content into a dictionary."""
        if not text or not text.strip():
            return {}
        try:
            val = json.loads(text)
            return cast(dict[str, Any], val) if isinstance(val, dict) else {}
        except Exception:
            try:
                val = yaml.safe_load(text)
                return cast(dict[str, Any], val) if isinstance(val, dict) else {}
            except Exception:
                return {}
