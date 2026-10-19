"""Incremental ingestion engine orchestrating Git drift, parsers, and LanceDB storage."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from cortex.config.loader import CortexConfig, RepositorySourceConfig, load_config
from cortex.embeddings.engine import EmbeddingEngine
from cortex.ingestion.git import get_head_commit, is_git_repository, scan_git_drift
from cortex.ingestion.manifest import ManifestManager, RepoSyncState
from cortex.ingestion.models import FileChangeType, SyncResult
from cortex.models.chunk import ChunkScope, DocumentChunk
from cortex.models.drift import ContractDriftAlert
from cortex.models.graph import CodeDependency, CodeSignature
from cortex.parsers.code.extractor import extract_code_ast
from cortex.parsers.registry import get_parser_for_file, parse_document
from cortex.storage.manager import StorageManager

if TYPE_CHECKING:
    from cortex.retrieval.drift import ContractDriftEngine

logger = logging.getLogger(__name__)


class IngestionEngine:
    """Orchestrates git drift inspection, parsing, embedding, and incremental LanceDB upserts."""

    def __init__(
        self,
        storage_manager: StorageManager,
        embedding_engine: EmbeddingEngine,
        manifest_manager: ManifestManager | None = None,
        drift_engine: ContractDriftEngine | None = None,
        batch_size: int = 32,
    ) -> None:
        """Initialize ingestion engine with storage, embedding, manifest, and drift engines."""
        self.storage = storage_manager
        self.embedding = embedding_engine
        self.manifest = manifest_manager or ManifestManager(self.storage.data_dir / "manifest.json")
        if drift_engine is None:
            from cortex.retrieval.drift import ContractDriftEngine

            drift_engine = ContractDriftEngine(
                storage_manager=self.storage,
                manifest_manager=self.manifest,
            )
        self.drift_engine = drift_engine
        self.batch_size = batch_size

    @classmethod
    def from_config(cls, config: CortexConfig | None = None) -> IngestionEngine:
        """Construct IngestionEngine from resolved CortexConfig or system defaults."""
        cfg = config or load_config()
        storage = StorageManager(data_dir=cfg.storage.data_dir)
        profile = cfg.get_active_profile()
        embedding = EmbeddingEngine(profile=profile)
        manifest_path = storage.data_dir / "manifest.json"
        manifest = ManifestManager(manifest_path=manifest_path)
        return cls(
            storage_manager=storage,
            embedding_engine=embedding,
            manifest_manager=manifest,
        )

    def sync_repository(
        self,
        repo_path: Path | str,
        repo_name: str | None = None,
        default_scope: ChunkScope = ChunkScope.INTERNAL,
        force_full: bool = False,
        table_name: str = "chunks",
        defer_fts: bool = False,
    ) -> SyncResult:
        """Perform incremental or full drift sync of a git repository into LanceDB."""
        start_time = time.perf_counter()
        path = Path(repo_path).expanduser().resolve()
        name = repo_name.strip() if repo_name and repo_name.strip() else path.name

        if not is_git_repository(path):
            msg = f"Cannot sync '{path}': not a valid git repository."
            logger.error(msg)
            return SyncResult(
                repo=name,
                base_commit=None,
                target_commit="unknown",
                duration_seconds=time.perf_counter() - start_time,
                errors=[msg],
            )

        target_commit = get_head_commit(path)
        repo_state = self.manifest.get_repo_state(name)
        base_commit = None if force_full or repo_state is None else repo_state.last_synced_commit

        try:
            drift = scan_git_drift(
                repo_path=path,
                base_commit=base_commit,
                target_commit=target_commit,
                repo_name=name,
            )
        except Exception as exc:
            err_msg = f"Failed to scan git drift for repository '{name}': {exc}"
            logger.exception(err_msg)
            return SyncResult(
                repo=name,
                base_commit=base_commit,
                target_commit=target_commit,
                duration_seconds=time.perf_counter() - start_time,
                errors=[err_msg],
            )

        # Early return if no changes occurred
        if not drift.has_changes and base_commit is not None:
            logger.info("Repository '%s' has zero drift against commit %s", name, base_commit[:8])
            return SyncResult(
                repo=name,
                base_commit=base_commit,
                target_commit=target_commit,
                duration_seconds=time.perf_counter() - start_time,
            )

        errors: list[str] = []
        deleted_count = 0
        added_count = 0
        updated_count = 0
        processed_files = 0

        # Analyze architectural contract drift prior to storage updates
        drift_alerts: list[ContractDriftAlert] = []
        try:
            drift_report = self.drift_engine.analyze_repo_drift(
                repo_path=path,
                repo_name=name,
                base_commit=base_commit,
                target_commit=target_commit,
            )
            drift_alerts = drift_report.alerts
            for alert in drift_alerts:
                if alert.severity.is_breaking:
                    logger.warning("Breaking contract drift in '%s': %s", name, alert.summary)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to inspect contract drift for '%s': %s", name, exc)

        if force_full:
            self.storage.delete_signatures_by_repo(name)
            self.storage.delete_dependencies_by_repo(name)

        # 1. Prune deletions from storage
        for change in drift.deleted_files:
            try:
                self.storage.delete_by_file(repo=name, file_path=change.path, table_name=table_name)
                self.storage.delete_signatures_by_file(repo=name, file_path=change.path)
                self.storage.delete_dependencies_by_file(repo=name, file_path=change.path)
                deleted_count += 1
                processed_files += 1
            except Exception as exc:
                errors.append(f"Failed to delete chunks for '{change.path}': {exc}")

        # 2. Prune old paths of renamed files
        for change in drift.renamed_files:
            if change.old_path:
                try:
                    self.storage.delete_by_file(
                        repo=name,
                        file_path=change.old_path,
                        table_name=table_name,
                    )
                    self.storage.delete_signatures_by_file(repo=name, file_path=change.old_path)
                    self.storage.delete_dependencies_by_file(repo=name, file_path=change.old_path)
                    deleted_count += 1
                except Exception as exc:
                    errors.append(f"Failed to prune old renamed path '{change.old_path}': {exc}")

        # 3. Prune modified files prior to re-indexing (prevents ghost/orphan chunks)
        for change in drift.modified_files:
            try:
                self.storage.delete_by_file(repo=name, file_path=change.path, table_name=table_name)
                self.storage.delete_signatures_by_file(repo=name, file_path=change.path)
                self.storage.delete_dependencies_by_file(repo=name, file_path=change.path)
            except Exception as exc:
                errors.append(f"Failed to prune modified file '{change.path}': {exc}")

        # 4. Parse eligible added, modified, and renamed files
        files_to_parse = [
            *drift.added_files,
            *drift.modified_files,
            *drift.renamed_files,
        ]

        chunks_to_upsert: list[DocumentChunk] = []
        signatures_to_upsert: list[CodeSignature] = []
        dependencies_to_upsert: list[CodeDependency] = []

        for change in files_to_parse:
            file_path_obj = path / change.path
            if not file_path_obj.is_file():
                continue

            try:
                content = file_path_obj.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                msg = f"Failed to read file '{change.path}' in repo '{name}': {exc}"
                logger.warning(msg)
                errors.append(msg)
                continue

            # AST signature and dependency extraction for code files
            if change.path.endswith(
                (".py", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".go")
            ):
                try:
                    extracted_sigs, extracted_deps = extract_code_ast(
                        content=content,
                        repo=name,
                        file_path=change.path,
                    )
                    if extracted_sigs:
                        signatures_to_upsert.extend(extracted_sigs)
                    if extracted_deps:
                        dependencies_to_upsert.extend(extracted_deps)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Code AST extraction failed for '%s': %s", change.path, exc)

            parser = get_parser_for_file(change.path)
            if parser is None:
                continue

            try:
                parsed_chunks = parse_document(
                    content=content,
                    repo=name,
                    file_path=change.path,
                    commit_sha=target_commit,
                    scope=default_scope,
                    parser=parser,
                )
                if parsed_chunks:
                    chunks_to_upsert.extend(parsed_chunks)
                    if change.change_type == FileChangeType.MODIFIED:
                        updated_count += len(parsed_chunks)
                    else:
                        added_count += len(parsed_chunks)
                processed_files += 1
            except Exception as exc:
                msg = f"Failed to parse file '{change.path}' in repo '{name}': {exc}"
                logger.warning(msg)
                errors.append(msg)

        # 5. Batch embed and upsert into LanceDB
        if chunks_to_upsert:
            try:
                for i in range(0, len(chunks_to_upsert), self.batch_size):
                    batch = chunks_to_upsert[i : i + self.batch_size]
                    embedded_batch = self.embedding.embed_chunks(batch)
                    dim = len(embedded_batch[0].vector or []) if embedded_batch else 384
                    self.storage.upsert_chunks(
                        embedded_batch,
                        table_name=table_name,
                        dim=dim,
                        create_fts=False,
                        recreate_on_dim_mismatch=(force_full and i == 0),
                    )
            except Exception as exc:
                msg = f"Failed to embed and upsert chunks for repo '{name}': {exc}"
                logger.exception(msg)
                errors.append(msg)

        # Upsert code signatures and dependencies
        if signatures_to_upsert:
            try:
                self.storage.upsert_signatures(signatures_to_upsert)
            except Exception as exc:
                msg = f"Failed to upsert code signatures for repo '{name}': {exc}"
                logger.exception(msg)
                errors.append(msg)

        if dependencies_to_upsert:
            try:
                self.storage.upsert_dependencies(dependencies_to_upsert)
            except Exception as exc:
                msg = f"Failed to upsert code dependencies for repo '{name}': {exc}"
                logger.exception(msg)
                errors.append(msg)

        # Defer FTS and vector index rebuild until sync cycle completion
        total_changed = added_count + updated_count + deleted_count
        if not defer_fts and total_changed > 0:
            self.storage.create_fts_index(table_name=table_name)
            self.storage.create_vector_index(table_name=table_name)

        # 6. Update state manifest
        safe_name = name.replace("'", "''")
        current_chunk_count = self.storage.count_chunks(
            table_name=table_name,
            where=f"repo = '{safe_name}'",
        )

        new_state = RepoSyncState(
            repo_name=name,
            repo_path=str(path),
            last_synced_commit=target_commit,
            chunk_count=current_chunk_count,
            file_count=processed_files,
        )
        self.manifest.update_repo_state(name, new_state)

        duration = time.perf_counter() - start_time
        return SyncResult(
            repo=name,
            base_commit=base_commit,
            target_commit=target_commit,
            added_chunks=added_count,
            updated_chunks=updated_count,
            deleted_chunks=deleted_count,
            processed_files=processed_files,
            duration_seconds=duration,
            errors=errors,
            drift_alerts=drift_alerts,
        )

    def sync_all(
        self,
        sources: Sequence[RepositorySourceConfig],
        force_full: bool = False,
        table_name: str = "chunks",
        defer_fts: bool = True,
    ) -> list[SyncResult]:
        """Sync all configured repository sources incrementally.

        Defers FTS index creation until all sources finish when defer_fts is True.
        """
        results: list[SyncResult] = []
        any_changes = False
        for src in sources:
            if not src.enabled:
                logger.info("Skipping disabled repository '%s'", src.get_repo_name())
                continue
            res = self.sync_repository(
                repo_path=src.path,
                repo_name=src.get_repo_name(),
                default_scope=src.default_scope,
                force_full=force_full,
                table_name=table_name,
                defer_fts=defer_fts,
            )
            results.append(res)
            if res.added_chunks > 0 or res.updated_chunks > 0 or res.deleted_chunks > 0:
                any_changes = True

        if defer_fts and any_changes:
            self.storage.create_fts_index(table_name=table_name)
            self.storage.create_vector_index(table_name=table_name)

        return results
