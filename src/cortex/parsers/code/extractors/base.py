"""Base interface and common utilities for code AST extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod

from tree_sitter import Node

from cortex.models.graph import CodeDependency, CodeSignature
from cortex.parsers.code.common import safe_decode


def node_signature_line(node: Node, lines: list[str]) -> str:
    """Extract declaration header up to body block opening or colon."""
    start_row = node.start_point.row
    if start_row < len(lines):
        line = lines[start_row].strip()
        return line
    return safe_decode(node.text).split("\n", 1)[0].strip()


# Backwards-compatible alias
_node_signature_line = node_signature_line


class BaseASTExtractor(ABC):
    """Abstract base class for language-specific AST extractors."""

    @abstractmethod
    def extract(
        self,
        content: str,
        repo: str,
        file_path: str,
    ) -> tuple[list[CodeSignature], list[CodeDependency]]:
        """Extract signatures and dependencies from code AST."""
