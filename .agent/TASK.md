# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [03.2]: Dual-Mode Architecture & Homelab Hub

- **Description:** Implement lightweight daemon server and client for remote portfolio querying. Provides streaming JSON/NDJSON endpoints, Bearer Token authentication (`CORTEX_API_KEY`), and seamless fallback between local in-process mode and remote hub mode.
- **Systems Involved:** `src/cortex/server.py`, `src/cortex/client.py`, `src/cortex/cli.py`, `tests/`
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] Lightweight HTTP daemon with `/search`, `/contracts`, `/technologies`, and `/health` endpoints.
- [ ] Support Bearer token authentication via `CORTEX_API_KEY`.
- [ ] Dual-mode client interface with transparent fallback between local and remote.
- [ ] CLI subcommand `cortex serve` to launch daemon.
- [ ] Comprehensive hermetic tests with mock HTTP client/server.
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
| [02.2] | Incremental Git Drift Ingestion | [`04957ec`] | 2026-10-17 |
| [02.3] | CLI Interface (`cortex search`, `cortex sync`, `cortex status`) | [`01ca41a`] | 2026-10-17 |
| [03.1] | MCP Server (`cortex_search`, `cortex_get_repo_contracts`, `cortex_list_technologies`) | [`5b5b71d`] | 2026-10-17 |

---

## Backlog (Upcoming, in priority order)

- [ ] **[90.1]** [Storage Compaction & Portfolio Benchmarks: LanceDB compaction, index cleanup, latency benchmarks under multi-repo portfolios] — `[perf]`

