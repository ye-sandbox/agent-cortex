# TASK.md — Current Task and Roadmap (agent-cortex)

> WHAT to do now. Detailed history lives in `git log`. User requests during conversation
> take precedence — report discrepancies before acting.

---

## Active Task

- **Task ID:** `[90.1]`
- **Title:** Technical Debt Remediation & Dual-Mode/Contract Alignment
- **Status:** `RUNNING`
- **Driver:** Align README/CLI (`cortex sync` positional path & `config.yaml` schema), wire `cortex-mcp` through `CortexClient` for Dual-Mode support, deduplicate contract/tech aggregation into `StorageManager` / `cortex.models`, harden multi-tenant token auth (`hmac.compare_digest` + tenant isolation), and guard vector dimension mismatches on table open.

---

## Completed Tasks Log

*(Previous cycle tasks [00.0] through [99.1] archived in [`ARCHIVE.md`](ARCHIVE.md).)*

| Task | Title | Commit(s) | Date |
|---|---|---|---|
| [01.1] | Hardware Profiles Matrix & FastEmbed Model Alignment | `fa2f27e` | 2026-10-17 |
| [01.2] | Retrieval & Reranking evaluation benchmark suite | `08277a3` | 2026-10-17 |

---

## Backlog (Upcoming, in priority order)

- [ ] Automated continuous background sync service (daemonized watcher)
- [ ] Code AST chunking for Python, TypeScript, and Go contracts
