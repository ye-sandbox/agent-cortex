# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

### 📌 Task [00.1]: Setup Python Skeleton, UV Tooling, Linters, and Test Runner

- **Description:** Initialize `pyproject.toml` with `uv`, configure strict typing (`mypy`), linting/formatting (`ruff`), and testing framework (`pytest`). Establish standard directory layout (`src/cortex/`, `tests/`) and basic smoke test.
- **Systems Involved:** `tooling`, `ci`, `src/cortex`
- **Action Type:**
  - [ ] Read-only / Documentation
  - [x] Source code changes
- **Status:** READY FOR PLANNING
  *(Workflow: `READY FOR PLANNING` → `PLANNING` on presenting plan → approval → `RUNNING`)*

### Acceptance Criteria
- [ ] `pyproject.toml` configured with Python >= 3.12, `uv` packaging, and core dependencies.
- [ ] `ruff` and `mypy --strict` configured and passing with exit code 0.
- [ ] `pytest` configured and passing with a baseline smoke test in `tests/`.
- [ ] Clean directory structure in `src/cortex/` with entrypoints for CLI and MCP.

---

## Completed Tasks Log

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [00.0] | Initial scaffolding from template-agent greenfield | [`ee62579`] | 2026-10-17 |

---

## Backlog (Upcoming, in priority order)

- [ ] **[01.1]** [Core Data Models & Config Loader: Pydantic v2 schemas for DocumentChunk, Metadata, and YAML config] — `[core]`
- [ ] **[01.2]** [Semantic Chunking & Parsers: Markdown sections, OpenAPI endpoints, Docker Compose services] — `[parsers]`
- [ ] **[01.3]** [LanceDB Vector Storage & FastEmbed: Hybrid retrieval (IVF-PQ dense + Tantivy BM25)] — `[storage]`
- [ ] **[01.4]** [Cross-Encoder Reranker: 2-stage precision reranking via FastEmbed] — `[reranker]`
- [ ] **[02.1]** [Incremental Git Drift Ingestion: Track commits via git diff and perform selective upsert] — `[ingestion]`
- [ ] **[02.2]** [CLI Interface: `cortex search`, `cortex sync`, `cortex status` with rich terminal & JSON output] — `[cli]`
- [ ] **[03.1]** [MCP Server: stdio server exposing `cortex_search` and `cortex_get_repo_contracts`] — `[mcp]`
- [ ] **[03.2]** [Dual-Mode Architecture: Remote HTTP client and Homelab Hub integration] — `[remote]`
