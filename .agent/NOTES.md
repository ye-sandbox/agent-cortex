# NOTES.md — Active Contracts and Runtime Memory (agent-cortex)

> Stores active runtime contracts, core algorithms, and critical gotchas.
> Formal architectural decisions live in [`docs/adr/decisions.md`](../docs/adr/decisions.md).

---

## Active Contracts

### 1. Document Chunk Identification & Schema Contract

Every indexed chunk is uniquely identifiable and deterministic across re-indexing runs:

- **ID Schema:** `{repo}:{file_path}:{chunk_index_or_hash}` (e.g. `ia-maestri:.agent/ECOSYSTEM.md:c2`)
- **Metadata Contract:**
  - `repo`: repository name (e.g. `poc-mod-maestri`)
  - `file_path`: relative file path in target repo
  - `category`: one of `["doc", "contract", "infra", "invariant", "solution"]`
  - `lifecycle`: one of `["active", "archived", "deprecated"]`
  - `breadcrumb`: heading hierarchy (e.g. `ia-maestri > ECOSYSTEM.md > 3. Interfaces`)
  - `commit_sha`: git commit hash when indexed
  - `tags`: extracted keywords / tech identifiers (e.g. `["websocket", "retry", "lancedb"]`)

### 2. Hybrid Retrieval & Scoring Formula

The search pipeline combines dense vector embeddings with sparse BM25 scores via Reciprocal Rank Fusion (RRF):

$$RRF(d) = \sum_{m \in \{dense, sparse\}} \frac{w_m}{k + rank_m(d)}$$

- Default constants: $k = 60$, $w_{dense} = 0.65$, $w_{sparse} = 0.35$.
- **Lifecycle penalty:** If `lifecycle == "archived"`, the candidate score is multiplied by `0.6` unless explicitly queried with `--include-archived`.
- **Reranker Step:** Top 30 candidates from RRF are passed through a Cross-Encoder (`BAAI/bge-reranker-large` or `base`) to produce the final top $K$ results.

---

## Gotchas & Pitfalls

- **FastEmbed ONNX CPU Threads:** On multi-core CPUs, limit ONNX thread contention when invoked from within agent subshells (`OMP_NUM_THREADS=4`).
- **File URI Portability:** Always normalize file paths into standard `file://` URLs that work across both Linux native and WSL2/Windows environments.
- **Git Diff Renames:** Detect `R` (Rename) in `git diff --name-status` to avoid orphan records; delete the old path and upsert the new path.

---

## Deliberate Technical Debt

| Debt | Rationale | Revisit When |
|---|---|---|
| In-memory configuration defaults | Avoid complex DB config tables during MVP | After Phase 3 (Dual-Mode Remote) |
