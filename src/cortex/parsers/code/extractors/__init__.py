"""Modular AST-based code signature and dependency extractors."""

from __future__ import annotations

from cortex.models.graph import CodeDependency, CodeSignature
from cortex.parsers.code.extractors.base import BaseASTExtractor, node_signature_line
from cortex.parsers.code.extractors.golang import GolangASTExtractor
from cortex.parsers.code.extractors.python import PythonASTExtractor
from cortex.parsers.code.extractors.typescript import TypeScriptASTExtractor


def extract_code_ast(
    content: str,
    repo: str,
    file_path: str,
) -> tuple[list[CodeSignature], list[CodeDependency]]:
    """Extract code signatures and dependency edges based on file extension."""
    if file_path.endswith(".py"):
        return PythonASTExtractor().extract(content, repo, file_path)
    if file_path.endswith((".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")):
        return TypeScriptASTExtractor().extract(content, repo, file_path)
    if file_path.endswith(".go"):
        return GolangASTExtractor().extract(content, repo, file_path)
    return [], []


__all__ = [
    "BaseASTExtractor",
    "GolangASTExtractor",
    "PythonASTExtractor",
    "TypeScriptASTExtractor",
    "extract_code_ast",
    "node_signature_line",
]
