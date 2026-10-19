---
author_type: human
author: Architecture & AI Systems Team
reviewed_by: yegear
date: 2026-10-17
status: accepted
type: architectural-decision-log
---

# Architectural Decisions Log (agent-cortex)

> 🏛️ **Progressive Disclosure:** Cumulative architectural decisions live here. Active runtime contracts stay in [`.agent/NOTES.md`](../../.agent/NOTES.md).

---

## Cumulative Decisions

### 2026-10-17 — ADR-001: Embedded LanceDB with FastEmbed, Hardware Profiles and 2-Stage Reranking

- **Context:** Autonomous agents and developers across `ye-sandbox` need sub-second semantic discovery of architectural patterns, contracts, and past solutions without the overhead of heavy vector database daemons (Qdrant, Milvus) running continuously. Hardware varies from low-power laptops to high-core homelab servers.
- **Decision:** Adopt **LanceDB** as an in-process embedded vector database combined with **FastEmbed** (ONNX Runtime in CPU) supporting 5 configurable profiles:
  - `high`: `BAAI/bge-large-en-v1.5` (1024 dim) + `BAAI/bge-reranker-large` (aliased to `bge-reranker-v2-m3-int8`, maximum precision).
  - `balanced` (Default): `BAAI/bge-small-en-v1.5` or `multilingual-e5-small` (384 dim, ~130MB) + `BAAI/bge-reranker-base` (~30-50ms latency).
  - `low`: `bge-small-en-v1.5` (384 dim) with Cross-Encoder disabled (pure Stage 1 Hybrid retrieval, <20ms latency).
  - `code`: `jinaai/jina-embeddings-v2-base-code` (768 dim, 8k context) + `jinaai/jina-reranker-v1-turbo-en` (specialized for source code and contracts).
  - `custom`: User-declared ONNX embedding and reranker models in `config.yaml`.
- **Pipeline:**
  1. *Stage 1 (Hybrid Retrieval):* Dense vector search (IVF-PQ) + Sparse full-text search (Tantivy BM25) fused with RRF (Reciprocal Rank Fusion).
  2. *Stage 2 (Reranking):* Cross-Encoder model (enabled in `high`, `balanced`, `code`, and `custom`) to eliminate false positives and provide precision ranking for top 5 candidates.
- **Consequences:** Zero background RAM overhead at rest; instant cold-start (<30ms); zero GPU/PyTorch requirements; adaptive resource usage per device profile.

---

### 2026-10-17 — ADR-002: Dual-Mode Architecture with HTTP/REST and Bearer Token

- **Context:** Developers work across multiple machines (workstation, laptop, homelab mini-PC). The system must allow running fully offline on local workstations while also supporting a centralized homelab hub for shared multi-device access.
- **Decision:** Design `agent-cortex` with a **Dual-Mode abstraction**:
  - *Mode 1 (Local-First):* CLI and MCP server read/write directly to local LanceDB Arrow files in `~/.local/share/agent-cortex/`.
  - *Mode 2 (Remote Hub):* CLI and MCP server connect via lightweight HTTP/REST (FastAPI/Starlette) streaming JSON/NDJSON to a central `agent-cortex` daemon on the homelab mini-PC.
  - *Authentication:* Pre-shared Bearer Token (`CORTEX_API_KEY`) via header `Authorization: Bearer <token>`.
- **Alternatives Considered:**
  - *gRPC:* Rejected due to compilation overhead (`protoc`), lack of human-debuggability, and heavy client dependencies.
  - *mTLS:* Rejected due to X.509 certificate renewal/rotation friction on local dev laptops; network-level security (Tailscale/Cloudflare Tunnels) with Bearer token is sufficient.
- **Consequences:** Uniform client behavior in both modes; zero client-side compilation; full alignment with `ye-sandbox` FastAPI standards.

---

### 2026-10-17 — ADR-003: Contract Chunking Granularity (OpenAPI & Docker Compose)

- **Context:** Large monolithic contract files (such as OpenAPI specs with 1,700+ lines or Docker Compose files with multiple interconnected services) cause semantic dilution and token bloat if indexed as single chunks.
- **Decision:**
  - *OpenAPI Specs (`openapi.json` / `openapi.yaml`):* Chunk by **individual operation / endpoint** (`METHOD /path`). Each chunk encapsulates operation summary, description, tags, query/path parameters, and primary success response schemas (200/201).
  - *Docker Compose (`compose.yaml` / `docker-compose.yml`):* Chunk by **individual service** (`services.<service_name>`). Each chunk encapsulates image/build targets, environment variable keys (excluding secret values), volume mount points, ports, healthchecks, and concise service dependencies.
- **Consequences:** Precise semantic hits for queries like "how to paginate deals endpoint" or "redis healthcheck configuration"; eliminates token waste in agent LLM contexts.

---

### 2026-10-17 — ADR-004: Model Lifecycle Management and Pre-Caching (`bootstrap` and `models download`)

- **Context:** Downloading multi-hundred-megabyte or gigabyte ONNX model weights during active query or sync execution creates unpredictable latency spikes and fails in air-gapped/offline workflows.
- **Decision:**
  - Implement `cortex bootstrap` to initialize directories, generate baseline configuration, and download default profile weights.
  - Implement `cortex models download [--profile <name> | --model <id>]` to explicitly download and cache ONNX weights ahead of time with Rich progress bars.
- **Consequences:** Deterministic execution during `cortex search` and `cortex sync`; full offline predictability once models are pre-cached.

---

### 2026-10-17 — ADR-005: Python 3.14+ Baseline and Direct Core ML Packaging

- **Context:** The host development environment and homelab nodes standardize on CPython 3.14 (`/usr/bin/python3.14`). Core ML dependencies (`lancedb 0.40.0`, `fastembed 0.9.0`, `onnxruntime 1.31.0`, `pyarrow 26.0.0`) have verified wheel resolution on Python 3.14. Separating ML libraries into optional extras (`[ml]`) created unnecessary onboarding friction for a local-first semantic engine.
- **Decision:**
  - Set baseline Python version to `requires-python = ">=3.14"`.
  - Configure `ruff` and `mypy --strict` targeting Python 3.14.
  - Move `lancedb` and `fastembed` directly into primary `[project.dependencies]`.
- **Consequences:** Out-of-the-box functionality with simple `uv sync` on Python 3.14+; full access to modern Python 3.14 interpreter speedups, syntax improvements, and strict type safety.

---

### 2026-10-17 — ADR-006: Ecosystem Hygiene, Git Topologies, and Token-Dense Formatting

- **Context:** Large-scale ingestion across dozens of portfolio repositories introduces edge cases: duplicate indexation from git worktrees and submodules; false repository exclusions caused by task archive files (`ARCHIVE.md`); token exhaustion when feeding verbose search snippets to AI agents; and language variances across projects.
- **Decision:**
  - *Language Invariant:* Default embedding model for `balanced` profile is strictly English-first (`BAAI/bge-small-en-v1.5`), in line with organization-wide technical standards. Document alternative multilingual models (`multilingual-e5-small`) in configuration for external non-English projects.
  - *Contract & Architecture Focus:* Restrict MVP ingestion to architectural artifacts (Markdown, OpenAPI endpoints, Docker Compose services, system invariants). Omit raw AST code chunking to avoid semantic dilution and index bloat.
  - *Git Topology Deduplication:* Canonicalize git roots using `git rev-parse --git-common-dir` to automatically bypass secondary git worktrees. Ignore nested `.git` submodules during parent repository scans.
  - *Repository Lifecycle Isolation:* Clearly separate task history from repository status. The presence of `ARCHIVE.md` (historical release tasks) MUST NOT mark a repository as archived. Only explicit `.cortexignore` or GitHub `isArchived` flags an entire repository.
  - *Token-Dense Snippets for Agents:* Format search results for LLMs using compact Markdown anchors (`[repo] path > breadcrumb`) + clean snippet, keeping verbose metadata in JSON payload attributes rather than polluting agent prompt context.
  - *Single Bearer Token:* Remote homelab daemon authenticates via simple `Authorization: Bearer <CORTEX_API_KEY>`.
- **Consequences:** Zero phantom duplicate vectors; high signal-to-noise ratio in agent LLM contexts; simple and predictable repository discovery.

---

### 2026-10-19 — ADR-007: Continuous Background Sync Watcher and HTTP Drift Synchronization

- **Context:** Autonomous development Trinity agents (Planner, Dev, Auditor) and developers frequently push architectural changes, OpenAPI specs, and compose definitions across repositories. Manually triggering `cortex sync` creates drift latency and risk of stale memory.
- **Decision:**
  - Implement **`RepoWatcher` (`src/cortex/ingestion/watcher.py`)**: A zero-dependency periodic drift scanner utilizing `asyncio` and `IngestionEngine`.
  - *Drift Detection:* Directly checks git HEAD commit SHAs (`get_head_commit`) against `manifest.json` state, achieving sub-2ms verification per repository without filesystem inotify descriptor exhaustion.
  - *Debounce & Lifecycle:* Configurable interval (default 30s) and debounce delay (default 2s) with signal handling (`SIGINT`/`SIGTERM`) and Starlette lifespan integration for zero-leak graceful teardown.
  - *Dual-Mode Control:* Expose `cortex watch` and `cortex sync --watch`, daemon server background monitoring (`cortex serve --watch`), remote HTTP trigger (`POST /sync`), and `CortexClient.sync()`.
- **Consequences:** Zero RAM footprint when idle; continuous real-time semantic memory consistency across portfolio satellites; seamless background monitoring on homelab nodes and local machines.

---

### 2026-10-19 — ADR-008: Cross-Repository Architectural Contract Drift Alerting and Impact Correlation

- **Context:** Sibling microservices and satellite tools in `ye-sandbox` continuously evolve. Breaking changes (removed API endpoints, altered request/response schemas, deleted Docker Compose services/ports, or removed/mutated exported AST code signatures) can silently break downstream consumers across repository boundaries before runtime deployment.
- **Decision:**
  - Implement **`ContractDriftEngine` (`src/cortex/retrieval/drift.py`)**: An AST- and schema-aware diff engine comparing contract revisions across Git revisions and indexed LanceDB records.
  - *Contract Diffs:*
    - **OpenAPI:** Diffs operations (`METHOD /path`), detecting deleted operations (`HIGH`), newly added required parameters (`HIGH`), removed parameters (`MEDIUM`), and deprecated routes (`MEDIUM`).
    - **Docker Compose:** Diffs service manifests (`services.<name>`), detecting deleted services (`HIGH`), removed port mappings (`HIGH`), and deleted env vars (`MEDIUM`).
    - **Code AST Signatures:** Diffs exported `CodeSignature` contracts (`.py`, `.ts`, `.go`), detecting removed exports (`HIGH`) and signature mutations (e.g. parameter count/type changes without defaults) (`HIGH`).
  - *Cross-Repository Dependency Correlation:* When a breaking change is detected in repository A, the engine queries `DependencyGraphEngine` and `code_dependencies` to discover any downstream portfolio repositories that import or call the altered symbol/route. If external callers exist, severity escalates to **`CRITICAL`** with detailed caller anchors (`repo:file:line`).
  - *Consumer Interfaces:*
    - CLI: `cortex drift audit [REPO]` with `--breaking-only`, `--cross-repo-only`, `--fail-on-breaking` (returns exit code 1 for CI/CD git hooks), and `--json`.
    - Ingestion: `IngestionEngine.sync_repository()` automatically emits breaking drift alerts and records `drift_alerts` in `SyncResult`.
    - MCP: Tool `cortex_get_contract_drift` for autonomous Planner and Auditor agents.
    - HTTP Daemon & Client: `GET /drift/alerts` and `CortexClient.get_contract_drift()`.
- **Consequences:** Proactive detection of cross-repository breaking changes prior to deployment; zero external runtime dependencies; full support for CI/CD quality gates and agentic workflows.

---

### 2026-10-19 — ADR-009: Portfolio Dependency Topology, Architectural Coupling Metrics, and Multi-Format Graph Export

- **Context:** As `ye-sandbox` portfolio repositories grow in count and complexity, understanding the cross-repository dependency topology, identifying foundational core services versus consumer leaves, pinpointing architectural bottlenecks, and catching circular dependencies is essential for both human system architects and autonomous Dev Trinity agents.
- **Decision:**
  - Implement **`PortfolioTopologyEngine` (`src/cortex/retrieval/topology.py`)**: An in-process topological synthesis engine leveraging `code_dependencies`, `code_signatures`, and `chunks`.
  - *Architectural Coupling Metrics:*
    - **Afferent Coupling ($C_a$):** Number of external portfolio repositories that depend on a repository (incoming).
    - **Efferent Coupling ($C_e$):** Number of external portfolio repositories that a repository depends on (outgoing).
    - **Instability Index ($I$):** $I = \frac{C_e}{C_a + C_e} \in [0.0, 1.0]$. Repositories with $I \le 0.3$ represent stable, foundational architectural hubs; $I \ge 0.7$ represent consumer applications/leaves.
    - **Circular Dependency Detection:** DFS cycle detection canonically deduplicating elementary directed cycles across repositories.
  - *Multi-Format Exporters:*
    - **Mermaid:** Native Markdown-compatible `flowchart LR/TD` with node metrics and highlighted cycles.
    - **Graphviz DOT:** Standard `digraph PortfolioTopology { ... }` with attribute styling.
    - **Cytoscape JSON:** Standard Cytoscape.js format `{"elements": {"nodes": [...], "edges": [...]}}` for spatial canvas rendering.
    - **NxN Rich Terminal Matrix:** ASCII/Unicode colored matrix table and summary cards for human engineers.
  - *Consumer Interfaces:*
    - CLI: `cortex topology matrix` (`--min-weight`, `--highlight-cycles`, `--json`), `cortex topology graph` (`--format`, `--direction`, `--output`), `cortex topology cycles` (`--fail-on-cycles`).
    - HTTP Server & Dual-Mode Client: `GET /topology/graph`, `GET /topology/matrix`, `GET /topology/cycles`, and `CortexClient` methods.
    - MCP Server: Tools `cortex_get_portfolio_topology` and `cortex_get_dependency_matrix`.
- **Consequences:** Instant, zero-overhead visualization of organization-wide microservice and tool topologies; automated prevention of circular dependencies in CI/CD pipelines; full compatibility with Markdown previews, Graphviz tools, and web canvas interfaces.
