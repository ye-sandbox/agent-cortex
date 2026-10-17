# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [02.3]: CLI Interface (`cortex search`, `cortex sync`, `cortex status`)

- **Description:** Implement user- and agent-facing CLI commands using Typer and Rich: `cortex sync` (orchestrating incremental drift sync across configured and auto-discovered repos), `cortex search` (hybrid RRF + rerank retrieval with token-dense agent anchors and `--json` NDJSON streaming output), and `cortex status` (displaying active profile, model cache, indexed repository commits, and chunk statistics).
- **Systems Involved:** `src/cortex/cli.py`, `src/cortex/ingestion`, `src/cortex/retrieval`, `tests/`
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] `cortex sync` command supporting `--repo <name>`, `--all`, and `--force-full` flags with Rich progress display.
- [ ] `cortex search <query>` command supporting `--profile`, `--limit`, `--scope`, `--include-archived`, and `--json` NDJSON stream output.
- [ ] `cortex status` command showing active hardware profile, storage path, synced repositories, latest commit SHAs, and total indexed chunks.
- [ ] Machine-readable NDJSON contract tested for AI agent subshell invocation.
- [ ] Comprehensive CLI hermetic tests with Typer `CliRunner`.
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

---

## Backlog (Upcoming, in priority order)

- [ ] **[03.1]** [MCP Server: stdio server exposing `cortex_search` (with `scope` filter), `cortex_get_repo_contracts`, and `cortex_list_technologies`] — `[mcp]`
- [ ] **[03.2]** [Dual-Mode Architecture & Homelab Hub: Lightweight FastAPI/Starlette daemon with streaming JSON/NDJSON and Bearer Token (`CORTEX_API_KEY`) authentication] — `[remote]`
- [ ] **[90.1]** [Storage Compaction & Portfolio Benchmarks: LanceDB compaction, index cleanup, latency benchmarks under multi-repo portfolios] — `[perf]`
