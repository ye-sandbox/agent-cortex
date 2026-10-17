# agent-cortex

[![CI](https://github.com/ye-sandbox/agent-cortex/actions/workflows/ci.yml/badge.svg)](https://github.com/ye-sandbox/agent-cortex/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Architecture: In--Process LanceDB](https://img.shields.io/badge/Storage-LanceDB%20Embedded-green.svg)](https://lancedb.github.io/lancedb/)

🌐 **English | [Português](README.pt-br.md)**

**Cross-repository semantic memory and portfolio knowledge engine for autonomous AI agents and software engineers.**

`agent-cortex` turns multi-repository portfolios into an active, queryable long-term memory (LTM). It enables instant natural language discovery of past architectural solutions, reusable interfaces, and system contracts across dozens of repositories without persistent daemon overhead.

---

## ⚡ Why agent-cortex?

In growing software ecosystems with autonomous agents (Antigravity, Cursor, Claude Code, Dev Trinity), development often suffers from **organizational amnesia**:
- Planners reinvent existing patterns because they lack cross-repo visibility.
- Engineers waste cognitive energy searching through dozens of local folders to recall where an architectural challenge was previously solved.
- Contract drift and inconsistent conventions proliferate across microservices.

`agent-cortex` solves this by continuously indexing curated documentation, contracts, and infrastructure manifests, exposing sub-50ms hybrid retrieval through a terminal CLI and an MCP Server.

---

## 🏛️ Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PORTFOLIO SOURCE REPOSITORIES                   │
│   ia-maestri   │   agent-guard   │   taskctl   │  satellites / services │
│   (docs/specs) │   (invariants)  │  (contracts)│    (compose/apis)     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Git Diff Tracking (Incremental)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        AGENT-CORTEX INGESTION ENGINE                   │
│  - Semantic chunking (Markdown headers, OpenAPI routes, Compose svcs)  │
│  - Metadata extraction (repo, breadcrumbs, tags, lifecycle status)     │
│  - Local CPU FastEmbed (BGE-M3 / ONNX Runtime, zero PyTorch/GPU)       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      HYBRID RETRIEVAL & RERANKING                      │
│  Stage 1: LanceDB Embedded (Dense IVF-PQ + Tantivy BM25 + RRF Fusion)   │
│  Stage 2: Cross-Encoder Reranker (BGE-Reranker for precision top-K)    │
│  Storage: Apache Arrow / Parquet in local filesystem (Zero RAM idle)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
┌───────────────────────┐                       ┌───────────────────────┐
│     TERMINAL CLI      │                       │   MCP SERVER (stdio)  │
│  cortex search ...    │                       │  Planners, Antigravity│
│  Output: ANSI / JSON  │                       │  and Autonomous Agents│
└───────────────────────┘                       └───────────────────────┘
```

### Key Architectural Invariants:
1. **In-Process & Zero Daemon:** Built on embedded LanceDB and FastEmbed ONNX. Consumes zero RAM when idle and cold-starts in < 30ms.
2. **Two-Stage Precision Retrieval:** Combines Dense Vector + BM25 Lexical search via Reciprocal Rank Fusion (RRF), followed by a Cross-Encoder Reranker to eliminate false positives.
3. **Public Engine / Private Data Isolation:** The engine is open-source and public; all generated embeddings and portfolio code chunks are stored outside the Git tree in user-local directories (`~/.local/share/agent-cortex/`).
4. **Dual-Mode Operation:** Operates locally on individual workstations or connects remotely to a central homelab hub.

---

## 🚀 Quickstart

### Prerequisites
- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) (recommended) or `pip`

### Installation
```bash
git clone https://github.com/ye-sandbox/agent-cortex.git
cd agent-cortex
uv sync
```

### Indexing Repositories
```bash
# Scan and index a local portfolio directory
uv run cortex sync ~/github/ye-sandbox/

# Or index a single repository
uv run cortex sync ~/github/ye-sandbox/poc-mod-maestri
```

### Searching the Portfolio
```bash
# Natural language semantic search
uv run cortex search "reconexão automática websocket backoff"

# Filter by category or repository
uv run cortex search "victorialogs integration" --category infra --limit 3

# Machine-readable JSON output for agent subshells
uv run cortex search "SSE streaming retry" --json
```

---

## 🤖 Model Context Protocol (MCP) Integration

`agent-cortex` ships with a stdio MCP server for direct integration into agent workflows:

Add to your agent's MCP configuration (`antigravity.json`, `claude_desktop_config.json`, or Cursor):
```json
{
  "mcpServers": {
    "cortex": {
      "command": "uv",
      "args": ["--directory", "/path/to/agent-cortex", "run", "cortex-mcp"]
    }
  }
}
```

### Available MCP Tools:
- **`cortex_search(query, category?, repo?, limit?)`**: Executes hybrid search and returns snippets with `file://` links.
- **`cortex_get_repo_contracts(repo)`**: Retrieves declared APIs, sockets, and interfaces for a specific repository.
- **`cortex_list_technologies(tech_name)`**: Identifies all repositories using a specified framework or tool.

---

## ⚙️ Configuration (`config.yaml`)

```yaml
storage:
  mode: "local"                             # "local" | "remote"
  path: "~/.local/share/agent-cortex/data"

models:
  profile: "high-precision"                 # "fast" | "balanced" | "high-precision"
  embedding:
    model: "BAAI/bge-m3"
  reranker:
    enabled: true
    model: "BAAI/bge-reranker-large"
    top_k_retrieve: 30
    top_k_return: 5

indexing:
  include_archived: true
  archived_score_multiplier: 0.6
```

---

## 📄 License

MIT © [ye-sandbox](https://github.com/ye-sandbox)
