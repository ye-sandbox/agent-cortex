"""Base parser protocol and common utilities for cortex specialized parsers."""

from __future__ import annotations

import abc
import re

from cortex.models.chunk import ChunkLifecycle, ChunkScope, DocumentChunk


def slugify(text: str, fallback: str = "chunk") -> str:
    """Normalize text into a deterministic, URL/ID-safe slug."""
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "_", text.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_-")
    return cleaned.lower() if cleaned else fallback


def format_breadcrumb(repo: str, file_path: str, *parts: str) -> str:
    """Construct hierarchical structural breadcrumb.

    Example: 'sentinel > specs/openapi.json > GET /deals'
    """
    clean_parts = [repo.strip(), file_path.strip().lstrip("/")]
    for part in parts:
        stripped = part.strip()
        if stripped:
            clean_parts.append(stripped)
    return " > ".join(clean_parts)


class BaseParser(abc.ABC):
    """Abstract base class for domain-specific chunking parsers."""

    @abc.abstractmethod
    def parse(
        self,
        content: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle = ChunkLifecycle.ACTIVE,
        scope: ChunkScope = ChunkScope.INTERNAL,
    ) -> list[DocumentChunk]:
        """Parse source content into deterministic DocumentChunk records."""
        raise NotImplementedError
