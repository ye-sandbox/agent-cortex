"""Architectural contract evolution timeline and changelog synthesis engine."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from cortex.config.loader import CortexConfig, load_config
from cortex.ingestion.git import is_git_repository, run_git, scan_git_drift
from cortex.models.drift import (
    ChangeKind,
    ContractDriftAlert,
    ContractType,
)
from cortex.models.evolution import (
    ArchitecturalChangelog,
    ChangelogRelease,
    ChangelogSection,
    ContractEvolutionEvent,
    ContractEvolutionTimeline,
)
from cortex.retrieval.drift import ContractDriftEngine
from cortex.retrieval.graph import DependencyGraphEngine
from cortex.storage.manager import StorageManager

logger = logging.getLogger(__name__)


class ContractEvolutionEngine:
    """Manages contract mutation history, evolution timelines, and changelog synthesis."""

    def __init__(
        self,
        storage_manager: StorageManager,
        drift_engine: ContractDriftEngine | None = None,
        graph_engine: DependencyGraphEngine | None = None,
    ) -> None:
        """Initialize evolution engine with storage, drift, and graph engines."""
        self.storage = storage_manager
        self.graph = graph_engine or DependencyGraphEngine(self.storage)
        self.drift_engine = drift_engine or ContractDriftEngine(
            storage_manager=self.storage,
            graph_engine=self.graph,
        )

    @classmethod
    def from_config(cls, config: CortexConfig | None = None) -> ContractEvolutionEngine:
        """Construct ContractEvolutionEngine from resolved config or system defaults."""
        cfg = config or load_config()
        storage = StorageManager(data_dir=cfg.storage.data_dir)
        graph = DependencyGraphEngine(storage)
        drift = ContractDriftEngine(storage_manager=storage, graph_engine=graph)
        return cls(storage_manager=storage, drift_engine=drift, graph_engine=graph)

    def record_alerts(
        self,
        repo: str,
        commit_sha: str,
        alerts: Sequence[ContractDriftAlert],
        commit_date: str | None = None,
        author: str | None = None,
        version_tag: str | None = None,
    ) -> list[ContractEvolutionEvent]:
        """Convert detected contract drift alerts into evolution events and persist them."""
        if not alerts:
            return []

        ts = commit_date or datetime.now(UTC).isoformat()
        auth = author or ""
        events: list[ContractEvolutionEvent] = []

        for alert in alerts:
            event_id = ContractEvolutionEvent.build_id(
                repo=repo,
                commit_sha=commit_sha,
                contract_type=alert.contract_type,
                change_kind=alert.change_kind,
                identifier=alert.identifier,
            )
            evt = ContractEvolutionEvent(
                id=event_id,
                repo=repo,
                commit_sha=commit_sha,
                commit_date=ts,
                author=auth,
                version_tag=version_tag,
                contract_type=alert.contract_type,
                change_kind=alert.change_kind,
                severity=alert.severity,
                identifier=alert.identifier,
                file_path=alert.file_path,
                summary=alert.summary,
                details=alert.details,
                impacted_repos=list(alert.impacted_repos),
                impacted_callers=list(alert.impacted_callers),
            )
            events.append(evt)

        self.storage.upsert_evolution_events(events)
        return events

    def get_timeline(
        self,
        repo: str | None = None,
        contract_type: ContractType | str | None = None,
        change_kind: ChangeKind | str | None = None,
        breaking_only: bool = False,
        since_date: str | None = None,
        until_date: str | None = None,
        limit: int = 100,
    ) -> ContractEvolutionTimeline:
        """Query contract evolution events from storage and construct sorted timeline."""
        clauses: list[str] = []

        if repo and repo.strip():
            safe_repo = repo.strip().replace("'", "''")
            clauses.append(f"repo = '{safe_repo}'")

        if contract_type is not None:
            c_type = (
                contract_type.value
                if isinstance(contract_type, ContractType)
                else str(contract_type).lower().strip()
            )
            clauses.append(f"contract_type = '{c_type}'")

        if change_kind is not None:
            c_kind = (
                change_kind.value
                if isinstance(change_kind, ChangeKind)
                else str(change_kind).lower().strip()
            )
            clauses.append(f"change_kind = '{c_kind}'")

        if breaking_only:
            clauses.append("severity IN ('CRITICAL', 'HIGH')")

        if since_date and since_date.strip():
            safe_since = since_date.strip().replace("'", "''")
            clauses.append(f"commit_date >= '{safe_since}'")

        if until_date and until_date.strip():
            safe_until = until_date.strip().replace("'", "''")
            clauses.append(f"commit_date <= '{safe_until}'")

        where_stmt = " AND ".join(clauses) if clauses else None
        raw_events = self.storage.get_evolution_events(where=where_stmt, limit=limit)

        # Sort reverse chronologically (latest date and SHA first)
        events = sorted(
            raw_events,
            key=lambda e: (e.commit_date, e.commit_sha),
            reverse=True,
        )

        return ContractEvolutionTimeline.from_events(events, repo=repo)

    def scan_git_history(
        self,
        repo_path: Path | str,
        repo_name: str | None = None,
        max_commits: int = 20,
        since_commit: str | None = None,
    ) -> list[ContractEvolutionEvent]:
        """Scan repository git commit log to detect and record historical contract mutations."""
        p = Path(repo_path).expanduser().resolve()
        name = repo_name.strip() if repo_name and repo_name.strip() else p.name

        if not is_git_repository(p):
            logger.warning("Target '%s' is not a git repository; cannot scan history.", p)
            return []

        git_args = ["log", f"-n{max_commits}", "--format=%H|%cI|%an|%s"]
        if since_commit:
            git_args.append(f"{since_commit}..HEAD")

        try:
            log_output = run_git(p, git_args, check=False)
        except Exception as exc:
            logger.warning("Failed to retrieve git log for '%s': %s", name, exc)
            return []

        if not log_output.strip():
            return []

        # Parse commit records
        commit_lines = [line.strip() for line in log_output.splitlines() if line.strip()]
        all_events: list[ContractEvolutionEvent] = []

        for line in commit_lines:
            parts = line.split("|", 3)
            if len(parts) < 3:
                continue
            sha = parts[0].strip()
            commit_date = parts[1].strip()
            author = parts[2].strip()

            # Check for tags pointing at this commit
            tag_name: str | None = None
            try:
                tag_out = run_git(p, ["tag", "-l", "--points-at", sha], check=False)
                if tag_out.strip():
                    tag_name = tag_out.splitlines()[0].strip()
            except Exception:  # noqa: S110
                pass

            # Detect drift between parent commit and target commit
            parent_ref = f"{sha}^"
            parent_exists = True
            try:
                run_git(p, ["rev-parse", "--verify", parent_ref], check=True)
            except Exception:
                parent_exists = False

            base_ref = parent_ref if parent_exists else None

            try:
                drift = scan_git_drift(
                    repo_path=p,
                    base_commit=base_ref,
                    target_commit=sha,
                    repo_name=name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to scan drift at commit %s for '%s': %s", sha[:8], name, exc)
                continue

            if not drift.has_changes:
                continue

            raw_alerts: list[ContractDriftAlert] = []

            # Modified files
            for change in drift.modified_files:
                new_text = run_git(p, ["show", f"{sha}:{change.path}"], check=False)
                old_text = (
                    run_git(p, ["show", f"{base_ref}:{change.path}"], check=False)
                    if base_ref
                    else None
                )
                raw_alerts.extend(
                    self.drift_engine.analyze_file_diff(name, change.path, old_text, new_text)
                )

            # Deleted files
            for change in drift.deleted_files:
                old_text = (
                    run_git(p, ["show", f"{base_ref}:{change.path}"], check=False)
                    if base_ref
                    else None
                )
                raw_alerts.extend(
                    self.drift_engine.analyze_file_diff(name, change.path, old_text, None)
                )

            # Added files
            for change in drift.added_files:
                new_text = run_git(p, ["show", f"{sha}:{change.path}"], check=False)
                raw_alerts.extend(
                    self.drift_engine.analyze_file_diff(name, change.path, None, new_text)
                )

            if not raw_alerts:
                continue

            correlated = self.drift_engine.resolve_cross_repo_impact(raw_alerts)
            commit_events = self.record_alerts(
                repo=name,
                commit_sha=sha,
                alerts=correlated,
                commit_date=commit_date,
                author=author,
                version_tag=tag_name,
            )
            all_events.extend(commit_events)

        return all_events

    def synthesize_changelog(
        self,
        repo: str | None = None,
        group_by: Literal["release", "date", "repo"] = "release",
        breaking_only: bool = False,
        limit: int = 200,
    ) -> ArchitecturalChangelog:
        """Synthesize structured architectural changelog from recorded evolution events."""
        timeline = self.get_timeline(
            repo=repo,
            breaking_only=breaking_only,
            limit=limit,
        )

        if not timeline.events:
            return ArchitecturalChangelog(
                repo=repo,
                releases=[],
                total_breaking=0,
                total_changes=0,
            )

        # Group events by chosen strategy
        grouped_events: dict[str, list[ContractEvolutionEvent]] = defaultdict(list)

        for evt in timeline.events:
            if group_by == "release":
                key = evt.version_tag or evt.commit_sha[:8]
            elif group_by == "date":
                key = evt.commit_date[:10] if len(evt.commit_date) >= 10 else "Unknown Date"
            else:  # repo
                key = evt.repo
            grouped_events[key].append(evt)

        releases: list[ChangelogRelease] = []

        for group_key, evts in grouped_events.items():
            breaking_events = [e for e in evts if e.severity.is_breaking]
            deprecations = [
                e
                for e in evts
                if e.change_kind == ChangeKind.DEPRECATED and not e.severity.is_breaking
            ]
            additions = [
                e for e in evts if e.change_kind == ChangeKind.ADDED and not e.severity.is_breaking
            ]
            modifications = [
                e
                for e in evts
                if e.change_kind == ChangeKind.MODIFIED and not e.severity.is_breaking
            ]

            sections: list[ChangelogSection] = []
            if breaking_events:
                sections.append(
                    ChangelogSection(
                        title="🚨 Breaking Changes",
                        change_kind=ChangeKind.MODIFIED,
                        events=breaking_events,
                    )
                )
            if deprecations:
                sections.append(
                    ChangelogSection(
                        title="⚠️ Deprecations",
                        change_kind=ChangeKind.DEPRECATED,
                        events=deprecations,
                    )
                )
            if additions:
                sections.append(
                    ChangelogSection(
                        title="✨ Additions & Enhancements",
                        change_kind=ChangeKind.ADDED,
                        events=additions,
                    )
                )
            if modifications:
                sections.append(
                    ChangelogSection(
                        title="🔄 Contract Modifications",
                        change_kind=ChangeKind.MODIFIED,
                        events=modifications,
                    )
                )

            # Collect affected downstream repos
            impacted: set[str] = set()
            for e in evts:
                impacted.update(e.impacted_repos)

            # Representative date
            rep_date = evts[0].commit_date[:10] if len(evts[0].commit_date) >= 10 else None

            release = ChangelogRelease(
                tag_or_period=group_key,
                date=rep_date,
                repo=repo if repo else (evts[0].repo if group_by == "repo" else None),
                breaking_count=len(breaking_events),
                total_changes=len(evts),
                sections=sections,
                impacted_repos=sorted(impacted),
            )
            releases.append(release)

        total_breaking = sum(r.breaking_count for r in releases)
        total_changes = sum(r.total_changes for r in releases)

        return ArchitecturalChangelog(
            repo=repo,
            releases=releases,
            total_breaking=total_breaking,
            total_changes=total_changes,
        )

    def render_markdown(self, changelog: ArchitecturalChangelog) -> str:
        """Render changelog into Markdown string."""
        return changelog.to_markdown()
