# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [03.1]: MCP Server (`cortex_search`, `cortex_get_repo_contracts`, `cortex_list_technologies`)

- **Description:** Implement Model Context Protocol (MCP) stdio server using the official MCP Python SDK (`mcp`), exposing core tool contracts for autonomous AI agents: `cortex_search` (with query, limit, scope, category, repo, and rerank parameters), `cortex_get_repo_contracts` (retrieving OpenAPI, compose, and architectural invariant chunks for a repository), and `cortex_list_technologies` (discovering tech tags across indexed repositories).
- **Systems Involved:** `src/cortex/mcp_server.py`, `src/cortex/cli.py`, `tests/`
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] Official MCP Python SDK server implementation with stdio transport.
- [ ] Tool `cortex_search`: semantic hybrid retrieval with compact agent anchors and metadata.
- [ ] Tool `cortex_get_repo_contracts`: targeted inspection of OpenAPI and Docker Compose definitions for a given repo.
- [ ] Tool `cortex_list_technologies`: aggregate tags/tech stack across portfolio repositories.
- [ ] CLI subcommand `cortex mcp` to launch stdio server.
- [ ] Comprehensive hermetic tests for MCP protocol tools.
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

---

## Backlog (Upcoming, in priority order)

- [ ] **[03.2]** [Dual-Mode Architecture & Homelab Hub: Lightweight FastAPI/Starlette daemon with streaming JSON/NDJSON and Bearer Token (`CORTEX_API_KEY`) authentication] — `[remote]`
- [ ] **[90.1]** [Storage Compaction & Portfolio Benchmarks: LanceDB compaction, index cleanup, latency benchmarks under multi-repo portfolios] — `[perf]`
