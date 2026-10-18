---
id: "k-002"
title: "Handle Git Rename Status to Prevent Orphan Vector Chunks"
date: 2026-10-17
tags:
  - "git"
  - "ingestion"
  - "drift"
  - "lancedb"
severity: "medium"
affected_components:
  - "src/cortex/ingestion/git.py"
  - "src/cortex/ingestion/engine.py"
symptoms:
  - "Search results return stale file paths that no longer exist"
  - "Duplicate chunk records after moving or renaming source documents"
---

# [k-002] Handle Git Rename Status to Prevent Orphan Vector Chunks

## Problem / Symptom

When files are renamed or moved in tracked git repositories, `git diff --name-status` outputs `R` or `R100` status with two paths (`old_path` and `new_path`). If an ingestion engine treats renames simply as additions of `new_path`, the previous vectors referencing `old_path` remain in LanceDB as ghost records, polluting search results with dead links.

```text
R100    docs/old_spec.md    docs/new_spec.md
```

---

## Approved Solution

Parse the tab-delimited rename format in `GitDriftTracker`. When status starts with `R`:
1. Extract `old_path` and `new_path`.
2. Schedule `old_path` for hard deletion in the vector table (`delete_by_path(repo, old_path)`).
3. Schedule `new_path` for parsing and vector upsert.

In [src/cortex/ingestion/git.py](file:///home/yegear/github/ye-sandbox/agent-cortex/src/cortex/ingestion/git.py):
```python
if status_code.startswith("R"):
    # Git diff outputs: R<score>\t<old_path>\t<new_path>
    old_file, new_file = parts[1], parts[2]
    deleted_files.append(old_file)
    modified_files.append(new_file)
```

**Root Cause:** Git rename is a composite operation (delete old + add new) requiring atomic deletion of the prior chunk key space in the database.

---

## What NEVER to Do

- ❌ **Anti-Pattern:** Blindly indexing `new_path` without dropping `old_path`.
  - *Why:* Creates duplicate chunks and permanent orphan vectors pointing to non-existent files.
- ❌ **Anti-Pattern:** Wiping the entire repository table on any rename event.
  - *Why:* Destroys incremental sync performance and requires full re-embedding of millions of tokens.

---

## Verification

```bash
uv run pytest tests/test_ingestion.py -k "test_git_diff_rename"
```
