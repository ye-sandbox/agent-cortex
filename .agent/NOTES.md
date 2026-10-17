# NOTES.md — Active Contracts and Runtime Memory

> Stores the active runtime contracts (WHAT interacts with WHAT), live communication topology, and critical gotchas.
> Historical architectural decisions live in [`docs/adr/decisions.md`](../docs/adr/decisions.md).
> Formal individual ADRs live in [`.agent/adr/`](adr/).

---

## How to Use this File

1. **Read before planning.** Active contracts and gotchas here take precedence over unstated defaults.
2. **Keep this file lean:** Only store ACTIVE contracts, live topology, open technical debt, and critical gotchas.
3. **Architectural decisions:** Record in [`docs/adr/decisions.md`](../docs/adr/decisions.md). Do NOT accumulate historical decisions here to prevent context bloat.

---

## Active Contracts

### 1. Multi-Agent Topology & Ensemble Contract (Dev Trinity Sentinel)

For multi-agent orchestration via Maestri or Antigravity, the canonical topology is defined by the **Dev Trinity Sentinel Ensemble** (`dev-trinity-sentinel.maestripartitura`):

| Node / Role | Channel / Protocol | Consumer | Contract / Responsibilities |
|---|---|---|---|
| **Project Architect (Planner)** | Maestri IPC / Socket | Developer Terminal | Decomposes initiatives into `.agent/TASK.md`, promotes tasks with `taskctl next`, dispatches execution. |
| **Software Developer** | PTY / Subshell (`aether-guard wrap`) | Scope Auditor | Surgical code implementation confined strictly to `Systems Involved`. Invokes `taskctl audit`. |
| **Task & Scope Auditor** | Read-Only CLI / Socket | Planner & Developer | Independent audit against `.agent/TASK.md` criteria and DoD. Semantic exit codes: 0 (`[APPROVED]`), 1 (`[CHANGES REQUIRED]`), 2 (`[REJECTED]`). |
| **Aether Sentinel** | Live Terminal & Rope (`#30D158`) | Developer Subshell | Real-time command interception, risk scoring (Safe/Audit/Block), NDJSON telemetry sink to VictoriaLogs. |

### 2. Runtime Data & Payload Contracts

Full schemas live in code (`[src/models/]` or `[core/schemas/]`). This table maps high-level contracts:

| Channel / Route / Queue | Producer | Consumer | Payload Schema / Protocol | Notes |
|---|---|---|---|---|
| `[e.g.: GET /api/v1/items]` | `[Service API]` | `[Web Frontend]` | `[ItemSummaryResponse]` | `[Active pagination schema]` |
| `[e.g.: queue:events:raw]` | `[Ingestion Worker]` | `[Event Parser]` | `[RawEventPayload]` | `[Redis stream / Kafka topic]` |

Contract changes require updating schemas on both sides within the same task.

---

## Gotchas & Pitfalls

- **[Lib/Service]:** [unexpected behavior and mitigation]

---

## Deliberate Technical Debt

| Debt | Rationale | Revisit When |
|---|---|---|
| | | |
