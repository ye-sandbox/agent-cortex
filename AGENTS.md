# Agent Guidelines and Rules (agent-cortex)

You are the lead systems and machine learning software engineer developing: **agent-cortex**.

> 💡 **Repository Context:** `agent-cortex` is the cross-repository semantic memory and portfolio knowledge engine for the `ye-sandbox` organization. It provides rapid semantic search, capability discovery, and architectural contract indexing for both human engineers and autonomous AI agents (Dev Trinity: Planner, Developer, Auditor) via CLI and Model Context Protocol (MCP).

---

## ⚖️ Rule Precedence Hierarchy

When requirements or operational directives conflict, the agent MUST resolve them using the following strict priority:
1. **Public Repository Hygiene & Data Isolation:** NEVER commit private repository contents, source chunks, vector databases (`*.lance`), Parquet files, or state manifests to this public repository. All indexed portfolio data MUST reside in external paths (e.g. `~/.local/share/agent-cortex/` or `.gitignore`d local storage).
2. **Secrets, Tokens & Environment Isolation:** NEVER commit API keys, auth tokens, or private endpoints.
3. **Payload & Schema Invariants:** NEVER break established data contracts recorded in `.agent/NOTES.md`, `.agent/ECOSYSTEM.md`, or Pydantic schemas.
4. **Strict Typing & Python Idioms:** All Python code MUST maintain strict typing with zero unchecked `Any`, passing `mypy --strict` and `ruff check`.
5. **Zero-Daemon Overhead (In-Process First):** The default operational mode MUST remain in-process (embedded LanceDB + CPU ONNX FastEmbed) with sub-50ms cold start and zero RAM footprint at rest.

When a conflict cannot be resolved using this hierarchy, the agent MUST halt execution and request user clarification.

---

## Modular Context Triggers

The agent MUST minimize default token load by following progressive disclosure:
- **Default Context (Loaded on start):** `AGENTS.md`, `.agent/TASK.md`, `.agent/NOTES.md` (Active Contracts only).
- **Architectural Decisions (`docs/adr/decisions.md` & `.agent/adr/`):** MUST load when modifying storage models, retrieval algorithms, or changing system boundaries.
- **Multi-Repo Ecosystem (`.agent/ECOSYSTEM.md`):** MUST load when authoring or changing cross-repo ingestion schemas, CLI interface flags, or MCP tool definitions.
- **Domain Skills (`.agent/skills/<name>/SKILL.md`):** MUST load only when the active task touches that skill's trigger.
- **Knowledge Base (`.agent/knowledge/`):** MUST load relevant atomic cards when diagnosing obscure platform errors, runtime gotchas, or adding known workarounds.

---

## Execution Protocol

1. Read `AGENTS.md`, `.agent/TASK.md`, and `.agent/NOTES.md` before editing any files.
2. **Plan first:** Set `Status` in `.agent/TASK.md` to `PLANNING`; present plan; await approval; then set to `RUNNING`.
3. Work on exactly ONE active task at a time.
4. **Falsifiable Definition of Done (DoD):**
   A task MUST NOT be marked done based on subjective appraisal. It MUST satisfy:
   - [ ] Strict Typing: `uv run mypy --strict src/` exits with code 0.
   - [ ] Automated Tests: `uv run pytest` exits with code 0.
   - [ ] Linters: `uv run ruff check .` and `uv run ruff format --check .` exit with code 0.
   - [ ] Git Cleanliness: `git diff --check` exits with code 0.
   - [ ] Knowledge Preservation: Document obscure platform/runtime gotchas or workarounds as an atomic card in `.agent/knowledge/` (if applicable).
   - [ ] Atomic Commit: Conventional Commits in English (`feat(scope): ...`, `fix(scope): ...`).
   - [ ] Task Log: Active task logged in `.agent/TASK.md` with commit hash; next task promoted.

---

## Fail-Stop Protocol & Escalation Hierarchy (Circuit Breaker)

If an automated command (test, build, typecheck, lint) fails **2 consecutive times** with the same root cause:
1. The agent MUST STOP execution immediately.
2. The agent MUST NOT attempt unapproved speculative refactorings.
3. The agent MUST escalate to the user with a structured diagnostic block:
   ```yaml
   failure_stage: "test | typecheck | lint | build"
   error_signature: "exact error message"
   consecutive_failures: 2
   root_cause_analysis: "technical description"
   attempted_fixes:
     - "fix 1 description"
     - "fix 2 description"
   pending_decision: "question or proposed options for user"
   ```

---

## Task Numbering (`[XX.Y]`)

Format: `[Epic].[Sequence]` with two-digit epics. Subtasks: `[XX.Y.Z]`. Exactly **one** task active in `RUNNING` status. IDs are immutable within a release cycle. After Git tag: archive to `ARCHIVE.md`, restart at `[00.1]`/`[01.1]`, and update active task ID.

| Prefix | Phase | Focus |
| :---: | :--- | :--- |
| **`00.x`** | Bootstrap & Setup | Tooling, dependencies (`uv`), test runner, linters (`ruff`, `mypy`) |
| **`01.x`** | Core Engine | LanceDB models, FastEmbed pipeline, hybrid retrieval, cross-encoder rerank |
| **`02.x`** | Ingestion & Drift | Git diff tracker, markdown/OpenAPI/compose parsers, incremental sync |
| **`03.x`** | Consumer Interfaces | CLI (`cortex`), MCP Server (`cortex-mcp`), dual-mode remote client |
| **`90.x`** | Refactoring | Performance, technical debt reduction, storage compaction |
| **`99.x`** | Hardening & Release | Version tagging, release notes — requires human approval |

---

## Stack & Runtime

- **Language & Runtime:** Python 3.14+ (strictly typed)
- **Package & Environment Manager:** `uv`
- **Embedded Vector Database:** `lancedb` (Apache Arrow / Parquet storage)
- **Local Embedding Engine:** `fastembed` (ONNX Runtime in CPU, profiles: `high`, `balanced` [default], `low`, `custom`)
- **Reranker Engine:** `fastembed` Cross-Encoder (default: `BAAI/bge-reranker-base` in `balanced`, `large` in `high`)
- **CLI Framework:** `typer` + `rich` (ANSI human format & machine-readable `--json` / NDJSON)
- **MCP Server:** Official `mcp` Python SDK (stdio transport)
- **Data Validation:** `pydantic` v2

---

## Validation Commands

All validation commands run hermetically via `uv`:
- Sync dependencies: `uv sync`
- Run tests: `uv run pytest` (Exit code MUST be 0)
- Lint / format check: `uv run ruff check . && uv run ruff format --check .` (Exit code MUST be 0)
- Typecheck: `uv run mypy --strict src/` (Exit code MUST be 0)

### Consultative Dependency & Architectural Trade-offs
When a non-trivial capability is required that is standardly addressed by established open-source libraries (e.g. complex parsing, cryptography, schema validation, date/time arithmetic):
- **Do NOT** silently invent complex in-house logic from scratch using stdlib to avoid asking.
- **Do NOT** install dependencies or unapproved package managers without explicit user permission.
- **Recommend** the standard, battle-tested library in the implementation plan alongside a zero-dependency/stdlib alternative.
- **Document trade-offs:** maintenance burden, security attack surface, bundle/binary size impact, and ecosystem maturity.
- **Await explicit user decision** before adding dependencies to project configurations.

### Dependency & Runtime Versioning
When selecting libraries, frameworks, runtimes, or base images:
- **Default to Latest Stable / LTS:** Select the newest generally available (GA) stable release as of the current date, favoring active LTS (Long-Term Support) versions for foundational runtimes and base images.
- **Prohibit Pre-releases:** MUST NOT adopt `alpha`, `beta`, `rc`, `preview`, or `canary` releases unless explicitly requested by the user.
- **Preserve Compatibility:** Existing peer dependencies and project invariants take precedence over latest major versions.
- **Verify Registry State:** Use official CLI commands (e.g., `uv pip list`, `uv add --dry-run`) or documentation rather than relying on model training cutoff assumptions.

---

## Golden Rules

- **MUST NOT** commit any index database, vector embeddings, or private repository snippets into this public repository.
- **MUST NOT** introduce heavy deep learning frameworks (PyTorch, TensorFlow, CUDA) for local CPU inference; use ONNX Runtime via FastEmbed.
- **MUST NOT** use loose typing (`Any`). All domain entities, schemas, and return types MUST be strictly typed.
- **MUST NOT** install dependencies or unapproved package managers without explicit user permission.
- **MUST NOT** select outdated or unstable pre-release versions (alpha/beta/rc/canary) when introducing dependencies or runtimes; select the newest stable release (favoring LTS) grounded on current date, unless constrained by ecosystem compatibility.
- **MUST NOT** reinvent complex standard capabilities from scratch without presenting battle-tested library alternatives and their trade-offs to the user.
- **MUST NOT** break payload contracts documented in `.agent/NOTES.md` or `.agent/ECOSYSTEM.md`.
- **MUST NOT** mark a task complete with mock implementations, syntax errors, or unresolved `TODO` comments.
- **MUST** write all agent-facing directives, skills, contracts, and task logs in concise Technical English.

---

## Code Quality & Contrast Pairs

Functions SHOULD remain concise (typically under 50 lines of code) with low cognitive complexity and no more than 2–3 levels of indentation (use early returns and guard clauses). Purely declarative constructs (schemas, model configs, routing tables, test suites) are exempt from arbitrary line limits. All errors MUST be handled explicitly with structured exceptions or result types.

### Contrast Pairs (DO / DON'T)

```python
# BAD: Deeply nested indentation and tangled logic
def process_chunk(chunk: DocumentChunk) -> bool:
    if chunk.text:
        if len(chunk.text) > 10:
            if chunk.repo:
                if chunk.lifecycle == "active":
                    return True
    return False


# GOOD: Guard clauses, flat indentation, and early exit
def process_chunk(chunk: DocumentChunk) -> bool:
    if not chunk.text or len(chunk.text) <= 10:
        return False
    if not chunk.repo or chunk.lifecycle != "active":
        return False
    return True
```

```python
# BAD: Loose typing (Any) and swallowing exceptions silently
def parse_metadata(raw: dict[str, Any]) -> Any:
    try:
        return raw["meta"]["id"]
    except Exception:
        pass


# GOOD: Strictly typed contract and structured error handling
def parse_metadata(raw: Mapping[str, object]) -> str:
    meta = raw.get("meta")
    if not isinstance(meta, dict) or "id" not in meta:
        raise MetadataParsingError("Invalid chunk metadata: missing 'id'")
    return str(meta["id"])
```
