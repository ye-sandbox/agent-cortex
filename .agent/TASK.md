# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [02.2]: Incremental Git Drift Ingestion

- **Description:** Implement portfolio Git drift tracking via `git diff --name-status` and commit history inspection. Parse added/modified files using registered parsers (`markdown`, `openapi`, `compose`), detect renames (`R`) and deletions (`D`) to prune orphan chunks, and perform selective upserts into LanceDB table with updated chunk metadata and vectors.
- **Systems Involved:** `src/cortex/ingestion`, `src/cortex/storage`, `tests/`
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] Git diff scanner identifying added (`A`), modified (`M`), deleted (`D`), and renamed (`R`) files against last synced commit SHA or HEAD.
- [ ] Incremental upsert engine updating only changed files without full re-indexing.
- [ ] Orphan deletion deleting chunks corresponding to deleted files or previous paths of renamed files.
- [ ] State manifest persistence recording latest synced commit per repository.
- [ ] Comprehensive hermetic test suite with mock git repositories covering all diff scenarios.
- [ ] Strict typing with `mypy --strict`, linters, and all tests passing.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [00.0] | Initial scaffolding from template-agent greenfield | [`ee62579`] | 2026-10-17 |
| [00.1] | Setup Python Skeleton, Tooling, Linters, and Core ML Packaging | [`70f90c5`] | 2026-10-17 |
| [01.1] | Core Data Models & Config Loader | [`7d7faf0`] | 2026-10-17 |
| [01.2] | Semantic Chunking & Specialized Parsers | [`a994e69`] | 2026-10-17 |
| [01.3] | LanceDB Vector Storage & FastEmbed Engine | [`5b532fb`] | 2026-10-17 |
| [01.4] | Cross-Encoder Precision Reranker & Profile Controller | [`20923f4`] | 2026-10-17 |
| [02.1] | Model Lifecycle & Onboarding CLI (`bootstrap` and `models download`) | [`24f3bcc`] | 2026-10-17 |

---

## Backlog (Upcoming, in priority order)

- [ ] **[02.3]** [CLI Interface: `cortex search`, `cortex sync`, `cortex status` with Rich terminal formatting and `--json` NDJSON output for agent subshells] — `[cli]`
- [ ] **[03.1]** [MCP Server: stdio server exposing `cortex_search` (with `scope` filter), `cortex_get_repo_contracts`, and `cortex_list_technologies`] — `[mcp]`
- [ ] **[03.2]** [Dual-Mode Architecture & Homelab Hub: Lightweight FastAPI/Starlette daemon with streaming JSON/NDJSON and Bearer Token (`CORTEX_API_KEY`) authentication] — `[remote]`
- [ ] **[90.1]** [Storage Compaction & Portfolio Benchmarks: LanceDB compaction, index cleanup, latency benchmarks under multi-repo portfolios] — `[perf]`
