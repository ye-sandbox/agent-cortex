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
- **Code AST Architectural Contracts (`.py`, `.ts`, `.tsx`, `.mts`, `.cts`, `.go`):**
  - **Python (`.py`):** Chunked by exported classes (with inheritance, docstrings, fields, and public methods) and top-level functions (signatures, docstrings, decorators). Skips private members (`_private`) unless in dunder whitelist. Category: `"contract"`.
  - **TypeScript (`.ts`, `.tsx`, `.mts`, `.cts`):** Chunked by `interface`, `type` alias, `enum`, exported `class` (with heritage, fields, and public methods), and exported functions / arrow functions. Category: `"contract"`.
  - **Go (`.go`):** Chunked by exported types (`interface`, `struct`, aliases), exported functions (`func Name(...)`), and exported receiver methods (`func (r *Recv) Method(...)`). Skips unexported identifiers (lowercase) and `*_test.go` files. Category: `"contract"`.

### 3. Retrieval Profiles & Scoring Formula

The search pipeline combines dense vector embeddings with sparse BM25 scores via Reciprocal Rank Fusion (RRF):

$$RRF(d) = \sum_{m \in \{dense, sparse\}} \frac{w_m}{k + rank_m(d)}$$

- Default constants: $k = 60$, $w_{dense} = 0.65$, $w_{sparse} = 0.35$.
- **Lifecycle penalty:** If `lifecycle == "archived"`, candidate score is multiplied by `0.6` unless explicitly queried with `--include-archived`.
- **Scope filtering:** Queries default to allowed scopes (`internal` and `public`). Confidential chunks require explicit `--scope confidential` or privileged credentials.
- **Hardware Profiles Matrix:**
  - `high`: `BAAI/bge-large-en-v1.5` (1024 dim) + `BAAI/bge-reranker-large` (aliased to `BAAI/bge-reranker-v2-m3-int8`, top 30 -> top K)
  - `balanced` (Default): `BAAI/bge-small-en-v1.5` or `multilingual-e5-small` (384 dim) + `BAAI/bge-reranker-base` (top 20 -> top K)
  - `low`: `bge-small-en-v1.5` (384 dim), Reranker disabled (pure Stage 1 RRF, < 20ms)
  - `code`: `jinaai/jina-embeddings-v2-base-code` (768 dim, 8k context) + `jinaai/jina-reranker-v1-turbo-en` (top 25 -> top K, 4 threads)
  - `custom`: Declared in `config.yaml`

### 4. Dynamic Configuration & Multi-Tenant Resolution

Runtime configuration can be persisted and managed dynamically without daemon restarts:
- **Storage Table:** Embedded LanceDB table `runtime_configs` located in `storage.data_dir`.
- **Resolution Order:** Base static fallback (`config.yaml`) $\leftarrow$ default DB record (`tenant_id == "default"`) $\leftarrow$ tenant-specific DB overrides (`tenant_id == "<id>"`).
- **Tenant Identification:** Remote hub daemon resolves tenant via `X-Tenant-ID` header, query parameter `?tenant_id=...`, POST body `"tenant_id": "..."`, or tenant-specific Bearer token mapped from `remote.api_key`. Defaults to `"default"` tenant if unspecified.
- **Dynamic Caching:** Retrieval pipelines are cached per configuration profile and weights to ensure zero redundant FastEmbed model initializations.

### 5. System & Retrieval Invariants

- **File URI Portability:** Always normalize file paths into standard `file://` URLs compatible with Linux native and WSL2/Windows.
- **Archived Tasks vs. Repositories:** `ARCHIVE.md` files store active historic knowledge; they MUST NOT trigger repo-level exclusion. Only explicit repository deprecation flags a repo as archived.
- **Token Efficiency:** MCP and CLI outputs presented to LLMs use compact markdown anchors (`[repo] path > breadcrumb`) and omit verbose metadata (commit SHA, raw UUIDs) to conserve context tokens.

---

## Gotchas & Pitfalls

Runtime platform bugs, library gotchas, and approved workarounds are captured as atomic cards in [`.agent/knowledge/`](knowledge/) to prevent default context bloat. Search cards via `grep` or `find_by_name` using `tags` and `symptoms` when troubleshooting:
- [`k-001`](knowledge/k-001-fastembed-onnx-thread-contention.md): FastEmbed ONNX thread contention (`OMP_NUM_THREADS=4`).
- [`k-002`](knowledge/k-002-git-diff-rename-orphan-vectors.md): Git diff `R` rename handling to prevent orphan vectors.
- [`k-003`](knowledge/k-003-git-worktree-submodule-duplicate-index.md): Secondary git worktree and submodule deduplication.
- [`k-004`](knowledge/k-004-model-weights-preflight-download.md): Pre-flight cache validation for ONNX model weights.

---

## Deliberate Technical Debt

| Debt | Rationale | Revisit When |
|---|---|---|
| None active | All Phase 1-3 baseline debts resolved | Post-Release [99.1] |
