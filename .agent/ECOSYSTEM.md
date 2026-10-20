# Multi-Repository Ecosystem Topology & Contracts (ECOSYSTEM.md)

> 🎯 **Purpose:** Canonical source of truth for topology, sibling services, shared contracts, and cross-repo boundaries in the **agent-cortex** engineering ecosystem.
>
> ⚠️ **Mandatory Rules for the Agent:**
> 1. You MUST NOT break active contracts consumed by sibling repositories or AI agent planners without backward-compatible deprecation.
> 2. You MUST NOT commit any proprietary or private repository code, vector chunks, or embedding data to this public repository.
> 3. You MUST mock external service interactions and file access in local automated tests.

---

## 1. Repository Topology Matrix

| Repository | Role / Responsibility | Relationship | Location / Repository URL | Owner / Team |
| :--- | :--- | :---: | :--- | :--- |
| **`agent-cortex`** *(Current)* | Cross-repo semantic memory and portfolio knowledge engine. | `Self` (Public) | `https://github.com/ye-sandbox/agent-cortex` | Platform / AI Systems |
| **`template-agent`** | Upstream canonical template for Agent-Driven Development. | `Upstream (Template)` | `https://github.com/ye-sandbox/template-agent` | Platform Team |
| **`poc-mod-maestri`** *(ia-maestri)* | Desktop agent orchestration, ASAR patching, taskctl hub. | `Downstream (Consumer)` | `https://github.com/ye-sandbox/poc-mod-maestri` | Systems / Core |
| **`agent-guard`** | Subshell interception, security guardrails, telemetry. | `Downstream (Consumer)` | `https://github.com/ye-sandbox/agent-guard` | Security / Dev Trinity |
| **`taskctl`** | Multi-agent task lifecycle CLI (Planner / Dev / Auditor). | `Downstream (Consumer)` | Hosted in `poc-mod-maestri` | Platform Team |
| **`<target-repo>`** *(Satellites)* | Arbitrary repositories indexed into agent-cortex memory. | `Source Data (Ingested)` | Local disk / GitHub org | Application Teams |

---

## 2. Shared Contracts & Source of Truth

- **MCP Server Contract (`cortex-mcp` via stdio):**
  - Consumed by: Antigravity, Maestri Desktop, Cursor, Claude Code, and autonomous Planner agents.
  - Tools exposed:
    - `cortex_search(query: str, category?: str, repo?: str, scope?: str, limit?: int)`: Hybrid semantic search returning code & doc snippets with `file://` references.
    - `cortex_get_repo_contracts(repo: str)`: Returns high-level API routes (OpenAPI endpoints), Docker Compose services, and schemas for a repository.
    - `cortex_list_technologies(tech_name: str)`: Finds which repositories utilize a given technology (e.g. `VictoriaLogs`, `FastAPI`, `LanceDB`, `Redis`).
    - `cortex_get_dependencies(repo: str, file_path?: str, symbol?: str, cross_repo_only?: bool, limit?: int)`: Traces outgoing code and module dependencies.
    - `cortex_get_dependents(symbol: str, module?: str, limit?: int)`: Traces incoming callers and cross-repo dependents.
    - `cortex_get_code_signatures(query: str, repo?: str, kind?: str, language?: str, limit?: int)`: AST code contracts and signatures.
    - `cortex_get_contract_drift(repo?: str, breaking_only?: bool, cross_repo_only?: bool)`: Audits architectural contract drift and breaking changes across repositories.
- **CLI Contract (`cortex`):**
  - Commands: `cortex bootstrap`, `cortex models`, `cortex search`, `cortex sync`, `cortex watch`, `cortex status`, `cortex deps`, `cortex drift`, `cortex topology dashboard`.
  - `cortex topology dashboard` writes an offline HTML snapshot of the existing topology graph; default destination is external to the checkout at `~/.local/share/agent-cortex/exports/topology-dashboard.html`.
  - Flag Invariant: `--json` MUST output strictly valid NDJSON/JSON for programmatic ingestion by agent subshells.
- **Dual-Mode Transport Contract:**
  - Local mode: Embedded LanceDB + in-process FastEmbed ONNX.
  - Remote mode: FastAPI / Starlette streaming JSON/NDJSON secured with `Authorization: Bearer <CORTEX_API_KEY>`.
- **Data Storage Boundary (Privacy Invariant):**
  - Production vector storage path defaults to `~/.local/share/agent-cortex/data/` or `$AGENT_CORTEX_DATA_DIR`.
  - It MUST NEVER be placed within the tracked git directory of this public repository.

---

## 3. Cross-Repo Interfaces Catalog

### A. Consumed by this Repository (Upstream Dependencies)

| Source Service | Protocol / Transport | Target Interface | Contract / Schema | Fallback / Blast Radius |
| :--- | :---: | :--- | :--- | :--- |
| Local Git Repositories | CLI / Subprocess | `git diff --name-status` / `git log` | Git tree & commit SHA | Skip repo if git corrupted or inaccessible |
| Local Markdown & Configs | File I/O | `README.md`, `openapi.yaml`, etc. | UTF-8 Text / YAML / JSON | Skip unparseable files with warning |

### B. Exposed by this Repository (Downstream Consumers)

| Interface / Asset | Consumer(s) | Payload / Schema | Breaking Change Risk | Deprecation Policy |
| :--- | :--- | :--- | :---: | :--- |
| `cortex-mcp` (stdio) | Planner agents / AI IDEs | MCP Tool Protocol (JSON-RPC) | **HIGH** | Additive-first, optional params |
| `cortex search --json` | Agent scripts / `taskctl` | JSON schema with `id`, `repo`, `file`, `score`, `snippet` | **HIGH** | Backward-compatible schema |

---

## 4. Blast Radius & Contract Evolution Rules

1. **Additive-First Evolution:**
   - NEVER drop or rename fields from `DocumentChunk` or MCP tool response schemas.
   - New filters or metadata fields MUST be optional with safe defaults.
2. **Context Isolation:**
   - `agent-cortex` is an indexer/search engine; it MUST NOT mutate source code in target repositories during indexing.
3. **Hermetic Testing:**
   - Unit tests MUST run against temporary mock repositories in `tests/fixtures` without touching user home directories or live git repositories.
