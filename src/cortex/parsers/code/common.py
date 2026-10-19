"""Common utilities for code AST contract parsers."""

from __future__ import annotations

import re

from cortex.models.chunk import DocumentChunk
from cortex.parsers.base import slugify


def safe_decode(raw: bytes | None) -> str:
    """Safely decode raw bytes from a tree-sitter node."""
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace").strip()


def extract_preceding_comments(
    start_row: int,
    lines: list[str],
    comment_chars: tuple[str, ...],
) -> str:
    """Extract contiguous comment block immediately preceding a node start row."""
    extracted: list[str] = []
    idx = start_row - 1
    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            # An empty line breaks the attached doc block
            break
        if any(line.startswith(c) for c in comment_chars):
            extracted.append(line)
            idx -= 1
        else:
            break

    if not extracted:
        return ""
    extracted.reverse()
    return "\n".join(extracted)


def clean_docstring(raw: str) -> str:
    """Normalize multi-line docstring text, removing quote delimiters and excess indent."""
    text = raw.strip()
    for quote in ('"""', "'''", "/*", "*/", "//", "#"):
        if text.startswith(quote):
            text = text[len(quote) :]
        if text.endswith(quote):
            text = text[: -len(quote)]
    return re.sub(r"\n\s*\*\s?", "\n", text).strip()


def build_contract_id(
    repo: str,
    file_path: str,
    kind: str,
    name: str,
    slug_counts: dict[str, int],
) -> str:
    """Build a deterministic, collision-free chunk ID for a code contract."""
    base_slug = slugify(f"{kind}_{name}")
    count = slug_counts.get(base_slug, 0)
    slug_counts[base_slug] = count + 1
    suffix = base_slug if count == 0 else f"{base_slug}_{count}"
    return DocumentChunk.build_id(repo, file_path, suffix)
