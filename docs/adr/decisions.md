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

### 2026-10-17 — ADR-001: Embedded LanceDB with FastEmbed and 2-Stage Reranking

- **Context:** Autonomous agents and developers across `ye-sandbox` need sub-second semantic discovery of architectural patterns, contracts, and past solutions without the overhead of heavy vector database daemons (Qdrant, Milvus) running continuously.
- **Decision:** Adopt **LanceDB** as an in-process embedded vector database combined with **FastEmbed** (ONNX Runtime in CPU) and a 2-stage retrieval pipeline:
  1. *Stage 1 (Hybrid Retrieval):* Dense vector search (IVF-PQ) + Sparse full-text search (Tantivy BM25) fused with RRF (Reciprocal Rank Fusion).
  2. *Stage 2 (Reranking):* Cross-Encoder model (`BAAI/bge-reranker-large` / `base`) to eliminate false positives and provide precision ranking for top 5 candidates.
- **Alternatives Considered:**
  - *Qdrant / Milvus (Daemon):* Rejected due to persistent memory overhead (150–300MB RAM), port management, and external service dependency.
  - *SQLite FTS5 alone:* Excellent for keyword matching, but incapable of conceptual semantic matching ("how to reconnect dropped sockets").
  - *Bi-Encoder alone (no reranker):* High recall but mediocre precision when ordering top-3 results for AI planner consumption.
- **Consequences:** Zero background RAM overhead at rest; instant cold-start (<30ms); zero GPU requirements; superior search accuracy for code and architectural text.

---

### 2026-10-17 — ADR-002: Dual-Mode Architecture (Local-First Embedded & Homelab Hub)

- **Context:** Developers work across multiple machines (workstation, laptop, homelab mini-PC). The system must allow running fully offline on local workstations while also supporting a centralized homelab hub for shared multi-device access.
- **Decision:** Design `agent-cortex` with a **Dual-Mode abstraction**:
  - *Mode 1 (Local-First):* CLI and MCP server read/write directly to local LanceDB Arrow files in `~/.local/share/agent-cortex/`.
  - *Mode 2 (Remote Hub):* CLI and MCP server connect via HTTP/gRPC to a central `agent-cortex` daemon hosted on the homelab mini-PC.
- **Consequences:** The same CLI command (`cortex search`) and MCP tools work seamlessly in both modes via a simple configuration switch in `config.yaml`.
