# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

- **Task ID:** `[99.1]`
- **Title:** Version tagging, release notes, and documentation synchronization for v0.3.0
- **Status:** `PLANNING`
- **Driver:** Finalize Phase 2 and Phase 3 capabilities (AST chunking, contract drift, portfolio topology dashboard, transitive blast radius simulation, change intent simulation and automated contract patch generation) for release.
- **Verification Plan:**
  - Strict Typing: `uv run mypy --strict src/` exits with code 0.
  - Automated Tests: `uv run pytest` exits with code 0.
  - Linters: `uv run ruff check .` and `uv run ruff format --check .` exit with code 0.
  - Git Cleanliness: `git diff --check` exits with code 0.

---

## Completed Tasks Log

*(Previous cycle tasks [00.0] through [99.1] archived in [`ARCHIVE.md`](ARCHIVE.md).)*

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [01.1] | Hardware Profiles Matrix & FastEmbed Model Alignment | `fa2f27e` | 2026-10-17 |
| [01.2] | Retrieval & Reranking evaluation benchmark suite | `08277a3` | 2026-10-17 |
| [02.1] | Automated continuous background sync service (daemonized watcher) | `f55f578` | 2026-10-19 |
| [02.2] | Code AST chunking for Python, TypeScript, and Go contracts | `655f8d3` | 2026-10-19 |
| [02.3] | AST-based code signature extractor integration for cross-language dependency graphs | `50cc4b6` | 2026-10-19 |
| [02.4] | Cross-repository architectural contract drift alerting (breaking changes in interfaces & APIs) | `faf1e1d` | 2026-10-19 |
| [02.5] | Multi-repo portfolio topology visualization and dependency matrix reporting | `35183c1` | 2026-10-19 |
| [02.6] | Portfolio architectural contract evolution timeline and changelog synthesis | `237c1b7` | 2026-10-20 |
| [03.1] | Cross-repository transitive blast-radius simulation and impact tracing for AI agent planning | `c734170` | 2026-10-19 |
| [03.2] | Interactive Cytoscape / Web spatial canvas dependency dashboard (`cortex topology dashboard`) | `562fad5` | 2026-10-20 |
| [03.3] | Multi-repo portfolio change intent simulation and automated contract patch generation | `b3c1d22` | 2026-10-20 |
| [90.1] | Config Schema Alignment, README Sync & CLI Positional Sync Target | `9f71111` | 2026-10-17 |
| [90.2] | MCP Server Dual-Mode Client Routing (`CortexClient` / `hub_url`) | `9f71111`, `8e2357e` | 2026-10-17 |
| [90.3] | Domain Model & Contract/Tech Aggregation Deduplication | `9f71111` | 2026-10-17 |
| [90.4] | Vector Dimension Guard & Automatic Vector Indexing on Sync | `9f71111`, `8e2357e` | 2026-10-17 |
| [90.5] | Multi-Tenant HTTP Daemon Hardening (Constant-Time Auth & Isolation) | `9f71111`, `8e2357e` | 2026-10-17 |
| [90.6] | Upstream Template Synchronization & Knowledge Base Architecture | `f7e1a79` | 2026-10-17 |
| [90.7] | CLI & HTTP Server Modularization and Presentation Decoupling | `05413bc` | 2026-10-19 |

---

## Backlog (Upcoming, in priority order)

- [ ] (Backlog items prioritized per roadmap)



