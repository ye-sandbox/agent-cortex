# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [01.2]: Semantic Chunking & Specialized Parsers

- **Description:** Implement domain-specific parsers and chunking logic for Markdown sections (by headers), OpenAPI (by endpoint `METHOD /path`), and Docker Compose (by service `services.<name>`) producing deterministic `DocumentChunk` records.
- **Systems Involved:** `src/cortex/parsers`, `tests/`
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] Markdown parser chunking documents by markdown headers (`#`, `##`, `###`) with hierarchical breadcrumbs and category `doc`.
- [ ] OpenAPI parser chunking by endpoint operation (`METHOD /path`) with parameters, descriptions, and category `contract`.
- [ ] Docker Compose parser chunking by service (`services.<name>`) isolating ports, volumes, non-secret env vars, and category `infra`.
- [ ] Comprehensive unit tests verifying deterministic IDs, chunk boundaries, metadata, and breadcrumb hierarchy.
- [ ] Strict typing with `mypy --strict`, linters, and tests passing with 0 errors.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [00.0] | Initial scaffolding from template-agent greenfield | [`ee62579`] | 2026-10-17 |
| [00.1] | Setup Python Skeleton, Tooling, Linters, and Core ML Packaging | [`70f90c5`] | 2026-10-17 |
| [01.1] | Core Data Models & Config Loader | [`7d7faf0`] | 2026-10-17 |

---

## Backlog (Upcoming, in priority order)

- [ ] **[01.3]** [LanceDB Vector Storage & FastEmbed Engine: In-process LanceDB management in `~/.local/share/agent-cortex/data`, ONNX embedding generation, hybrid retrieval (IVF-PQ dense + Tantivy BM25 + RRF fusion)] — `[storage]`
- [ ] **[01.4]** [Cross-Encoder Precision Reranker & Profile Controller: 2-stage reranker (`bge-reranker-base` / `large`), profile-based activation, and bypass in `low` profile] — `[reranker]`
- [ ] **[02.1]** [Model Lifecycle & Onboarding CLI: `cortex bootstrap` (directory setup, initial config, default weights download) and `cortex models download` (explicit pre-caching with Rich progress bars)] — `[models]`
- [ ] **[02.2]** [Incremental Git Drift Ingestion: Track portfolio commits via `git diff --name-status`, handle renames/deletes, and selective upsert into LanceDB] — `[ingestion]`
- [ ] **[02.3]** [CLI Interface: `cortex search`, `cortex sync`, `cortex status` with Rich terminal formatting and `--json` NDJSON output for agent subshells] — `[cli]`
- [ ] **[03.1]** [MCP Server: stdio server exposing `cortex_search` (with `scope` filter), `cortex_get_repo_contracts`, and `cortex_list_technologies`] — `[mcp]`
- [ ] **[03.2]** [Dual-Mode Architecture & Homelab Hub: Lightweight FastAPI/Starlette daemon with streaming JSON/NDJSON and Bearer Token (`CORTEX_API_KEY`) authentication] — `[remote]`
- [ ] **[90.1]** [Storage Compaction & Portfolio Benchmarks: LanceDB compaction, index cleanup, latency benchmarks under multi-repo portfolios] — `[perf]`
