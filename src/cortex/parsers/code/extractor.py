"""AST-based Code Signature and Dependency Extractor (backwards-compatible facade)."""

from __future__ import annotations

from cortex.parsers.code.extractors import (
    BaseASTExtractor,
    GolangASTExtractor,
    PythonASTExtractor,
    TypeScriptASTExtractor,
    extract_code_ast,
)
from cortex.parsers.code.extractors.base import _node_signature_line
from cortex.parsers.code.extractors.python import _PY_DUNDER_WHITELIST
from cortex.parsers.code.extractors.typescript import _ts_comments

__all__ = [
    "BaseASTExtractor",
    "GolangASTExtractor",
    "PythonASTExtractor",
    "TypeScriptASTExtractor",
    "_PY_DUNDER_WHITELIST",
    "_node_signature_line",
    "_ts_comments",
    "extract_code_ast",
]
