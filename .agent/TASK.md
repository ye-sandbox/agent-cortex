# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [99.1]: Release Tagging & GitHub Release

- **Description:** Implement semver release tagging, CHANGELOG generation, and distribution packaging for agent-cortex.
- **Systems Involved:** `pyproject.toml`, `CHANGELOG.md`, `README.md`, GitHub release workflows
- **Action Type:**
  - [x] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] Version validation and bumping mechanism across pyproject.toml and __init__.py.
- [ ] Comprehensive CHANGELOG.md documenting epics 00.x through 90.x.
- [ ] GitHub release notes and packaging verification.
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
| [03.2] | Dual-Mode Architecture & Homelab Hub | [`7901eeb`] | 2026-10-17 |
| [90.1] | Storage Compaction & Portfolio Benchmarks | [`da1413d`] | 2026-10-17 |

---

## Backlog (Upcoming, in priority order)

*All planned release epics complete. Backlog cleared.*


