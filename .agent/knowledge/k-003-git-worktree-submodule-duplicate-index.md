---
id: "k-003"
title: "Bypass Secondary Git Worktrees and Submodules in Portfolio Indexing"
date: 2026-10-17
tags:
  - "git"
  - "discovery"
  - "worktree"
  - "submodules"
severity: "medium"
affected_components:
  - "src/cortex/ingestion/discovery.py"
symptoms:
  - "Identical repositories indexed multiple times under parallel worktree directories"
  - "Submodule trees causing recursive duplicate chunks and vector bloat"
---

# [k-003] Bypass Secondary Git Worktrees and Submodules in Portfolio Indexing

## Problem / Symptom

When developers or agent workspaces maintain git worktrees (e.g. `git worktree add`) or recursive submodules inside portfolio directories, portfolio repository auto-discovery traverses each worktree folder as if it were a distinct repository. This causes duplicate chunks, skewed RRF search scores, and unnecessary re-indexing cycles.

```text
Found repository: /home/user/github/repo (head: abc1234)
Found repository: /home/user/github/repo/.worktrees/feature-x (head: abc1234)
```

---

## Approved Solution

During repository discovery in [src/cortex/ingestion/discovery.py](file:///home/yegear/github/ye-sandbox/agent-cortex/src/cortex/ingestion/discovery.py):
1. Execute `git rev-parse --git-common-dir` to identify the canonical root git directory.
2. If the common directory resolves to an already discovered or parent git root, bypass the directory as a secondary worktree.
3. Check `.git` type: if `.git` is a file containing `gitdir:`, inspect if it belongs to a worktree or submodule, and filter accordingly unless explicitly configured in `portfolio.repos`.

**Root Cause:** Git worktrees share the same commit objects and common git dir (`.git/worktrees/...`), but present separate working trees on the filesystem.

---

## What NEVER to Do

- ❌ **Anti-Pattern:** Indexing every folder containing a `.git` item indiscriminately without verifying common dir ownership.
  - *Why:* Results in 2x-5x redundant vector storage and outdated chunks when worktrees diverge.
- ❌ **Anti-Pattern:** Hard-coding `.git/worktrees` string matching without using `git rev-parse`.
  - *Why:* Breaks when worktrees are located outside the main repository root.

---

## Verification

```bash
uv run pytest tests/test_discovery.py
```
