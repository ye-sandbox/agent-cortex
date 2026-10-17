# NOTES.md — Active Contracts and Runtime Memory (agent-cortex)

> Stores active runtime contracts, core algorithms, and critical gotchas.
> Formal architectural decisions live in [`docs/adr/decisions.md`](../docs/adr/decisions.md).

---

## Active Contracts

### 1. Document Chunk Identification & Schema Contract

Every indexed chunk is uniquely identifiable and deterministic across re-indexing runs:

- **ID Schema:** `{repo}:{file_path}:{chunk_index_or_hash}` (e.g. `ia-maestri:.agent/ECOSYSTEM.md:c2`, `sentinel:specs/openapi.json:get_deals`)
- **Metadata Contract:**
  - `repo`: repository name (e.g. `sentinel-deals-backend`, `clipflow-backend`)
  - `file_path`: relative file path in target repo
  - `category`: one of `["doc", "contract", "infra", "invariant", "solution"]`
  - `lifecycle`: one of `["active", "archived", "deprecated"]`
  - `scope`: one of `["internal", "public", "confidential"]` (default: `"internal"`)
  - `breadcrumb`: heading/structural hierarchy (e.g. `sentinel > specs/openapi.json > GET /deals` or `clipflow > compose.yaml > services > worker`)
  - `commit_sha`: git commit hash when indexed
  - `tags`: extracted keywords / tech identifiers (e.g. `["websocket", "retry", "lancedb", "GET", "/deals"]`)

### 2. Contract Parsing Invariants

- **OpenAPI (`openapi.json` / `openapi.yaml`):**
  - Chunked by **individual operation (`METHOD /path`)**.
  - Content includes summary, description, tags, parameters (path/query/header), and primary 200/201 response schemas.
  - Category: `"contract"`.
- **Docker Compose (`compose.yaml` / `docker-compose.yml`):**
  - Chunked by **individual service (`services.<name>`)**.
  - Content includes image/build target, non-secret env vars, volume mounts, port mappings, healthcheck, and `depends_on`.
  - Category: `"infra"`.

### 3. Retrieval Profiles & Scoring Formula

The search pipeline combines dense vector embeddings with sparse BM25 scores via Reciprocal Rank Fusion (RRF):

$$RRF(d) = \sum_{m \in \{dense, sparse\}} \frac{w_m}{k + rank_m(d)}$$

- Default constants: $k = 60$, $w_{dense} = 0.65$, $w_{sparse} = 0.35$.
- **Lifecycle penalty:** If `lifecycle == "archived"`, candidate score is multiplied by `0.6` unless explicitly queried with `--include-archived`.
- **Scope filtering:** Queries default to allowed scopes (`internal` and `public`). Confidential chunks require explicit `--scope confidential` or privileged credentials.
- **Hardware Profiles Matrix:**
  - `high`: `BAAI/bge-m3` (1024 dim) + `BAAI/bge-reranker-large` (top 30 -> top K)
  - `balanced` (Default): `BAAI/bge-small-en-v1.5` or `multilingual-e5-small` (384 dim) + `BAAI/bge-reranker-base` (top 20 -> top K)
  - `low`: `bge-small-en-v1.5` (384 dim), Reranker disabled (pure Stage 1 RRF, < 20ms)
  - `custom`: Declared in `config.yaml`

### 4. Dynamic Configuration & Multi-Tenant Resolution

Runtime configuration can be persisted and managed dynamically without daemon restarts:
- **Storage Table:** Embedded LanceDB table `runtime_configs` located in `storage.data_dir`.
- **Resolution Order:** Base static fallback (`config.yaml`) $\leftarrow$ default DB record (`tenant_id == "default"`) $\leftarrow$ tenant-specific DB overrides (`tenant_id == "<id>"`).
- **Tenant Identification:** Remote hub daemon resolves tenant via `X-Tenant-ID` header, query parameter `?tenant_id=...`, POST body `"tenant_id": "..."`, or tenant-specific Bearer token mapped from `remote.api_key`. Defaults to `"default"` tenant if unspecified.
- **Dynamic Caching:** Retrieval pipelines are cached per configuration profile and weights to ensure zero redundant FastEmbed model initializations.

---

## Gotchas & Pitfalls

- **FastEmbed ONNX CPU Threads:** On multi-core CPUs, limit ONNX thread contention when invoked from within agent subshells (`OMP_NUM_THREADS=4`).
- **File URI Portability:** Always normalize file paths into standard `file://` URLs that work across both Linux native and WSL2/Windows environments.
- **Git Diff Renames:** Detect `R` (Rename) in `git diff --name-status` to avoid orphan records; delete the old path and upsert the new path.
- **Git Worktrees & Submodules:** Bypass secondary worktrees via `git rev-parse --git-common-dir` and ignore submodules during parent repository indexing to prevent duplicate vectors.
- **Archived Tasks vs. Archived Repos:** `ARCHIVE.md` files store valuable historic releases and active foundations; they MUST NOT trigger repo-level exclusion. Only explicit repository deprecation (`.cortexignore` or GitHub `isArchived`) flags an entire repo as archived.
- **Token Efficiency Invariant:** MCP and CLI search outputs presented to LLMs use compact markdown anchors (`[repo] path > breadcrumb`) and omit verbose metadata (commit SHA, UUIDs) to preserve context tokens.
- **Model Download Pre-flight:** Always prompt or rely on `cortex bootstrap` / `cortex models download` to cache weights; avoid unannounced multi-gigabyte downloads during CLI searches.

---

## Deliberate Technical Debt

| Debt | Rationale | Revisit When |
|---|---|---|
| None active | All Phase 1-3 baseline debts resolved | Post-Release [99.1] |
