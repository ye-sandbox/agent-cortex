# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-10-20

### Added
- **Code AST Chunking & Extraction**: Native AST-based contract parsers for Python, TypeScript, and Go extracting exported interfaces, classes, functions, and structs with parameter and return type signatures.
- **Cross-Language Dependency Graph**: Persistent `code_dependencies` table in LanceDB tracking cross-repository and intra-repository AST calls, symbol imports, and architectural bridges.
- **Contract Drift Alerting**: Cross-repository breaking change detection engine classifying removals, signature changes, and deprecations into `CRITICAL`, `HIGH`, `MEDIUM`, and `INFO` severity tiers.
- **Portfolio Topology & Coupling Metrics**: Portfolio dependency matrix and graph engine calculating Afferent Coupling ($C_a$), Efferent Coupling ($C_e$), Instability Index ($I$), cycle detection, and exports to Mermaid, Graphviz DOT, and Cytoscape JSON.
- **Interactive Offline Topology Dashboard**: Standalone HTML/Cytoscape dashboard (`cortex topology dashboard`) with zero external network dependencies, cycle highlighting, and node/edge inspection.
- **Transitive Blast-Radius Simulation**: Multi-hop BFS dependency impact tracer computing composite risk scores (0-100) and actionable AI planning advisories for upstream contract migrations.
- **Contract Evolution Timeline & Changelog Synthesis**: Historical Git commit scanner and timeline engine synthesizing structured, release-oriented contract changelogs with downstream caller impact highlights.
- **Portfolio Change Intent & Automated Patch Generation**: Intent simulation engine generating ready-to-apply `git apply` unified diffs across downstream consumer repositories for symbol renames and endpoint adjustments.
- **Automated Background Watcher Service**: Daemonized filesystem watcher with debouncing and systemd integration (`cortex watcher`) for hands-free incremental synchronization.
- **Hardware Profile Matrix & Benchmark Suite**: Extended embedding profiles (`code` with `jina-embeddings-v2-base-code`, `high`, `balanced`, `low`) and automated retrieval evaluation benchmark harness.

### Changed
- **Modular CLI Architecture**: Decoupled monolithic CLI into modular command groups (`cortex search`, `cortex sync`, `cortex drift`, `cortex topology`, `cortex impact`, `cortex intent`, `cortex timeline`, `cortex changelog`, `cortex watcher`, `cortex storage`).
- **Domain-Partitioned MCP Tool Registries**: Modularized MCP server into domain-specific tool modules (`retrieval`, `drift`, `topology`, `impact`, `evolution`, `intent`, `graph`) with uniform error propagation and JSON formatting.
- **Decomposed Dual-Mode CortexClient**: Refactored monolithic HTTP/embedded client into clean domain mixins with identical signatures across local and remote daemon modes.
- **Multi-Tenant Server Hardening**: Dynamic DB-backed runtime configuration table (`runtime_configs`), constant-time token verification, and isolated multi-tenant config resolution.
- **Strict AST Parser Separation**: Split language-specific extraction logic into dedicated, isolated parser modules (`python.py`, `typescript.py`, `golang.py`).

## [0.1.0] - 2026-10-17

### Added
- **Core Engine & Data Models**: Strict Pydantic v2 domain schemas (`DocumentChunk`, `HardwareProfile`, `CortexConfig`), deterministic chunk IDs, and extensible configuration loaders.
- **Specialized Semantic Parsers**: Chunkers for Markdown documents, OpenAPI operation contracts (`METHOD /path`), and Docker Compose services with structural breadcrumbs and metadata extraction.
- **LanceDB Vector Storage & Embeddings**: In-process Apache Arrow/Parquet storage engine with CPU FastEmbed ONNX embeddings (`bge-small-en-v1.5`, `bge-m3`, `multilingual-e5-small`).
- **Hybrid Retrieval & Reranker**: Hybrid dense vector + BM25 sparse search fused via Reciprocal Rank Fusion (RRF), coupled with Stage 2 Cross-Encoder reranking (`BAAI/bge-reranker-base` / `large`) and hardware profile controller (`high`, `balanced`, `low`, `custom`).
- **Incremental Git Drift Engine**: Drift tracker detecting working tree and commit changes, file renames, and deletions for minimal incremental re-indexing.
- **Model Lifecycle & Management**: CLI commands (`cortex bootstrap`, `cortex models download`) for offline weight pre-caching.
- **Consumer CLI**: Human ANSI (`rich`) and machine-readable (`--json`) output modes for `cortex search`, `cortex sync`, and `cortex status`.
- **Model Context Protocol (MCP) Server**: Stdio MCP server exposing tools (`cortex_search`, `cortex_get_repo_contracts`, `cortex_list_technologies`) for LLM agent integration.
- **Dual-Mode Architecture & Remote Hub**: Lightweight HTTP/SSE daemon server powered by Starlette/Uvicorn, paired with `CortexClient` featuring fast-fail connection diagnostics and multi-tenant DB-backed configuration resolution.
- **Storage Compaction & Optimizations**: Native LanceDB fragment compaction, version vacuuming, deferred FTS index rebuilding during sync, and orphan vector pruning (`cortex storage clean-orphans --keep`).
