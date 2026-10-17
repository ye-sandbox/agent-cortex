# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
