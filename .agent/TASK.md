# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [01.1]: Core Data Models & Config Loader

- **Description:** Implement Pydantic v2 schemas for `DocumentChunk` (with metadata contracts: `scope`, `lifecycle`, `category`, `breadcrumb`, `tags`), hardware profiles (`high`, `balanced`, `low`, `custom`), and `config.yaml` loader (`sources.repositories`, `sources.auto_discover`).
- **Systems Involved:** `src/cortex/models`, `src/cortex/config`, `tests/`
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] Strictly-typed Pydantic v2 model for `DocumentChunk` matching contracts in `.agent/NOTES.md` (id schema, metadata, deterministic validation).
- [ ] Hardware profile models (`HardwareProfile`: `high`, `balanced`, `low`, `custom`) defining embedding model, dimensions, reranker, and thread settings.
- [ ] Cortex configuration loader (`CortexConfig`) supporting `~/.config/agent-cortex/config.yaml` or local workspace override with validation.
- [ ] Unit tests in `tests/test_models.py` and `tests/test_config.py` verifying serialization, validation errors, and profile resolution.
- [ ] `mypy --strict`, `ruff check`, and `pytest` pass with 0 errors.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [00.0] | Initial scaffolding from template-agent greenfield | [`ee62579`] | 2026-10-17 |
| [00.1] | Setup Python Skeleton, Tooling, Linters, and Core ML Packaging | [`70f90c5`] | 2026-10-17 |

---

## Backlog (Upcoming, in priority order)

- [ ] **[01.2]** [Semantic Chunking & Specialized Parsers: Markdown sections by headers, OpenAPI by endpoint (`METHOD /path`), and Docker Compose by service (`services.<name>`)] — `[parsers]`
- [ ] **[01.3]** [LanceDB Vector Storage & FastEmbed Engine: In-process LanceDB management in `~/.local/share/agent-cortex/data`, ONNX embedding generation, hybrid retrieval (IVF-PQ dense + Tantivy BM25 + RRF fusion)] — `[storage]`
- [ ] **[01.4]** [Cross-Encoder Precision Reranker & Profile Controller: 2-stage reranker (`bge-reranker-base` / `large`), profile-based activation, and bypass in `low` profile] — `[reranker]`
- [ ] **[02.1]** [Model Lifecycle & Onboarding CLI: `cortex bootstrap` (directory setup, initial config, default weights download) and `cortex models download` (explicit pre-caching with Rich progress bars)] — `[models]`
- [ ] **[02.2]** [Incremental Git Drift Ingestion: Track portfolio commits via `git diff --name-status`, handle renames/deletes, and selective upsert into LanceDB] — `[ingestion]`
- [ ] **[02.3]** [CLI Interface: `cortex search`, `cortex sync`, `cortex status` with Rich terminal formatting and `--json` NDJSON output for agent subshells] — `[cli]`
- [ ] **[03.1]** [MCP Server: stdio server exposing `cortex_search` (with `scope` filter), `cortex_get_repo_contracts`, and `cortex_list_technologies`] — `[mcp]`
- [ ] **[03.2]** [Dual-Mode Architecture & Homelab Hub: Lightweight FastAPI/Starlette daemon with streaming JSON/NDJSON and Bearer Token (`CORTEX_API_KEY`) authentication] — `[remote]`
- [ ] **[90.1]** [Storage Compaction & Portfolio Benchmarks: LanceDB compaction, index cleanup, latency benchmarks under multi-repo portfolios] — `[perf]`
