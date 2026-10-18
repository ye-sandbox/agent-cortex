---
id: "k-004"
title: "Pre-flight Cache Validation for FastEmbed and Cross-Encoder ONNX Weights"
date: 2026-10-17
tags:
  - "fastembed"
  - "cli"
  - "bootstrap"
  - "models"
severity: "low"
affected_components:
  - "src/cortex/cli.py"
  - "src/cortex/embeddings/engine.py"
  - "src/cortex/retrieval/reranker.py"
symptoms:
  - "First search command hangs for several minutes while downloading multi-gigabyte models silently"
  - "Agent timeout errors during initial CLI or MCP queries"
---

# [k-004] Pre-flight Cache Validation for FastEmbed and Cross-Encoder ONNX Weights

## Problem / Symptom

On cold systems without pre-cached HuggingFace / FastEmbed models, executing `cortex search "query"` triggers an unannounced download of several hundred megabytes of ONNX weights (e.g. `BAAI/bge-small-en-v1.5`, `BAAI/bge-reranker-base`). In headless agent subshells or interactive sessions with aggressive timeout thresholds, this causes timeouts or perceived hangs with no progress telemetry.

```text
Downloading (...)_model.onnx: 100%|██████████| 134M/134M [00:15<00:00, 8.91MB/s]
Agent execution timed out after 30000ms.
```

---

## Approved Solution

Provide dedicated explicit lifecycle commands in the CLI to decouple model provisioning from query execution:
1. `cortex bootstrap`: Verifies local directory permissions, creates default configuration, and pre-downloads default balanced profile models.
2. `cortex models download [--profile <profile>]`: Pre-warms cache for specific hardware tiers (`high`, `balanced`, `low`, `code`).
3. During query execution, if models are missing from cache, warn the user and recommend running `cortex bootstrap` or `cortex models download`.

**Root Cause:** FastEmbed triggers automatic on-demand downloads upon first model instantiation if local cache misses.

---

## What NEVER to Do

- ❌ **Anti-Pattern:** Committing binary ONNX model weights (`*.onnx`) into git repositories.
  - *Why:* Violates repository hygiene and causes repository bloat.
- ❌ **Anti-Pattern:** Silently downloading large model weights during latency-sensitive CLI or MCP queries without user pre-flight checks.
  - *Why:* Triggers client timeouts and corrupts JSON/NDJSON streams if progress bars leak into stdout.

---

## Verification

```bash
uv run cortex models status
```
