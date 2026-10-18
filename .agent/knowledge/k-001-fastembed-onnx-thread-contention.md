---
id: "k-001"
title: "Limit FastEmbed ONNX Thread Contention in Multi-Core Subshells"
date: 2026-10-17
tags:
  - "fastembed"
  - "onnxruntime"
  - "concurrency"
  - "performance"
severity: "medium"
affected_components:
  - "src/cortex/embeddings/engine.py"
  - "src/cortex/retrieval/reranker.py"
symptoms:
  - "High CPU saturation across all logical cores during embedding"
  - "Subshell latency spikes or terminal freezes when running search concurrently"
---

# [k-001] Limit FastEmbed ONNX Thread Contention in Multi-Core Subshells

## Problem / Symptom

When running local FastEmbed and ONNX Runtime embedding or cross-encoder inference on high-core-count developer machines, ONNX Runtime defaults to spawning thread pools matching the host's total logical cores. Inside agent subshells (e.g. Maestri, Antigravity, or terminal multiplexers), this causes aggressive thread contention, cache thrashing, and high CPU spikes, stalling parallel agent tasks.

```text
OMP: Warning #96: Cannot enforce thread affinity on all threads.
Resource temporarily unavailable (thread pool creation failed)
```

---

## Approved Solution

Enforce bounded CPU thread parallelism by restricting OpenMP and ONNX thread concurrency to a maximum of 4 threads:

```bash
export OMP_NUM_THREADS=4
export ONNXRUNTIME_NUM_THREADS=4
```

In code, configure `fastembed.TextEmbedding` and `fastembed.rerank.cross_encoder.TextCrossEncoder` with `threads=4` when instantiating the models in [src/cortex/embeddings/engine.py](file:///home/yegear/github/ye-sandbox/agent-cortex/src/cortex/embeddings/engine.py) and [src/cortex/retrieval/reranker.py](file:///home/yegear/github/ye-sandbox/agent-cortex/src/cortex/retrieval/reranker.py).

**Root Cause:** FastEmbed defaults to unconstrained OpenMP thread allocation which starves adjacent agent processes in concurrent terminal environments.

---

## What NEVER to Do

- ❌ **Anti-Pattern:** Setting `OMP_NUM_THREADS=1` unconditionally.
  - *Why:* Degrades embedding and reranking throughput significantly on batches > 16.
- ❌ **Anti-Pattern:** Relying on unconstrained defaults on 16+ core machines.
  - *Why:* Spawns excessive OS threads, causing latency jitter and starving the terminal environment.

---

## Verification

```bash
uv run python -c "from cortex.embeddings.engine import EmbeddingEngine; engine = EmbeddingEngine(); print(engine.embed(['test']))"
```
