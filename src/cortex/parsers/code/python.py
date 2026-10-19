"""Python code AST contract parser extracting classes, methods, and functions."""

from __future__ import annotations

import logging
from typing import ClassVar

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from cortex.models.chunk import ChunkCategory, ChunkLifecycle, ChunkScope, DocumentChunk
from cortex.parsers.base import BaseParser, format_breadcrumb
from cortex.parsers.code.common import build_contract_id, extract_preceding_comments, safe_decode

logger = logging.getLogger(__name__)

_DUNDER_WHITELIST = frozenset(
    {
        "__init__",
        "__call__",
        "__enter__",
        "__exit__",
        "__getitem__",
        "__setitem__",
        "__iter__",
        "__aiter__",
        "__anext__",
        "__len__",
        "__repr__",
        "__str__",
    }
)


class PythonContractParser(BaseParser):
    """Extracts architectural contracts (classes, public methods, functions) from Python code."""

    _parser: ClassVar[Parser | None] = None

    @classmethod
    def get_parser(cls) -> Parser:
        """Lazily initialize and cache the Tree-Sitter Python parser."""
        if cls._parser is None:
            py_lang = Language(tree_sitter_python.language())
            cls._parser = Parser(py_lang)
        return cls._parser

    def parse(
        self,
        content: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle = ChunkLifecycle.ACTIVE,
        scope: ChunkScope = ChunkScope.INTERNAL,
    ) -> list[DocumentChunk]:
        """Parse Python source content into contract DocumentChunk records."""
        if not content.strip():
            return []

        parser = self.get_parser()
        source_bytes = content.encode("utf-8")
        try:
            tree = parser.parse(source_bytes)
        except Exception as exc:
            logger.warning("Tree-sitter failed parsing %s: %s", file_path, exc)
            return []

        lines = content.splitlines()
        chunks: list[DocumentChunk] = []
        slug_counts: dict[str, int] = {}

        for node in tree.root_node.children:
            decorators: list[str] = []
            target_node: Node = node

            if node.type == "decorated_definition":
                for child in node.children:
                    if child.type == "decorator":
                        dec_text = safe_decode(child.text)
                        if dec_text:
                            decorators.append(dec_text)
                    elif child.type in ("class_definition", "function_definition"):
                        target_node = child

            if target_node.type == "class_definition":
                chunk = self._parse_class(
                    cls_node=target_node,
                    decorators=decorators,
                    lines=lines,
                    repo=repo,
                    file_path=file_path,
                    commit_sha=commit_sha,
                    lifecycle=lifecycle,
                    scope=scope,
                    slug_counts=slug_counts,
                )
                if chunk:
                    chunks.append(chunk)

            elif target_node.type == "function_definition":
                chunk = self._parse_function(
                    fn_node=target_node,
                    decorators=decorators,
                    lines=lines,
                    repo=repo,
                    file_path=file_path,
                    commit_sha=commit_sha,
                    lifecycle=lifecycle,
                    scope=scope,
                    slug_counts=slug_counts,
                )
                if chunk:
                    chunks.append(chunk)

        return chunks

    def _parse_class(
        self,
        cls_node: Node,
        decorators: list[str],
        lines: list[str],
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Parse class definition node into a DocumentChunk."""
        name_node = cls_node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name or (name.startswith("_") and not name.startswith("__")):
            return None

        # Base classes / superclasses
        supers_node = cls_node.child_by_field_name("superclasses")
        supers_text = safe_decode(supers_node.text) if supers_node else ""

        # Preceding doc comment or docstring inside body
        body_node = cls_node.child_by_field_name("body")
        docstring = self._extract_docstring(body_node) if body_node else ""
        if not docstring:
            docstring = extract_preceding_comments(cls_node.start_point.row, lines, ("#",))

        # Fields and methods
        body_lines: list[str] = []
        method_names: list[str] = []
        if body_node:
            for child in body_node.children:
                if child.type == "expression_statement":
                    stmt_text = safe_decode(child.text)
                    # Filter out the initial docstring from fields list
                    if not (stmt_text.startswith(('"""', "'''")) and docstring in stmt_text) and (
                        "=" in stmt_text or ":" in stmt_text
                    ):
                        body_lines.append(f"    {stmt_text}")
                elif child.type in ("function_definition", "decorated_definition"):
                    method_chunk_str, m_name = self._format_method_signature(child)
                    if method_chunk_str and m_name:
                        body_lines.append(method_chunk_str)
                        method_names.append(m_name)

        # Assemble contract markdown content
        header_parts: list[str] = []
        for dec in decorators:
            header_parts.append(dec)
        header_parts.append(f"class {name}{supers_text}:")
        if docstring:
            header_parts.append(f'    """{docstring}"""')
        if body_lines:
            header_parts.extend(body_lines)
        else:
            header_parts.append("    ...")

        contract_code = "\n".join(header_parts)
        tags = ["python", "class", name]
        for dec in decorators:
            tags.append(dec.lstrip("@").split("(")[0])
        if supers_text:
            cleaned_supers = supers_text.strip("()").split(",")
            for s in cleaned_supers:
                clean_s = s.strip()
                if clean_s:
                    tags.append(clean_s)

        chunk_id = build_contract_id(repo, file_path, "class", name, slug_counts)
        breadcrumb = format_breadcrumb(repo, file_path, f"class {name}")

        return DocumentChunk(
            id=chunk_id,
            repo=repo,
            file_path=file_path,
            category=ChunkCategory.CONTRACT,
            lifecycle=lifecycle,
            scope=scope,
            breadcrumb=breadcrumb,
            commit_sha=commit_sha,
            tags=tags,
            content=f"```python\n{contract_code}\n```",
        )

    def _parse_function(
        self,
        fn_node: Node,
        decorators: list[str],
        lines: list[str],
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Parse top-level function definition node into a DocumentChunk."""
        name_node = fn_node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name or (name.startswith("_") and not name.startswith("__")):
            return None

        params_node = fn_node.child_by_field_name("parameters")
        params_text = safe_decode(params_node.text) if params_node else "()"

        ret_node = fn_node.child_by_field_name("return_type")
        ret_text = f" -> {safe_decode(ret_node.text)}" if ret_node else ""

        is_async = any(c.type == "async" for c in fn_node.children)
        fn_keyword = "async def" if is_async else "def"

        body_node = fn_node.child_by_field_name("body")
        docstring = self._extract_docstring(body_node) if body_node else ""
        if not docstring:
            docstring = extract_preceding_comments(fn_node.start_point.row, lines, ("#",))

        sig_lines: list[str] = []
        for dec in decorators:
            sig_lines.append(dec)
        sig_lines.append(f"{fn_keyword} {name}{params_text}{ret_text}:")
        if docstring:
            sig_lines.append(f'    """{docstring}"""')
        sig_lines.append("    ...")

        contract_code = "\n".join(sig_lines)
        tags = ["python", "function", name]
        if is_async:
            tags.append("async")
        for dec in decorators:
            tags.append(dec.lstrip("@").split("(")[0])

        chunk_id = build_contract_id(repo, file_path, "func", name, slug_counts)
        breadcrumb = format_breadcrumb(repo, file_path, f"{fn_keyword} {name}")

        return DocumentChunk(
            id=chunk_id,
            repo=repo,
            file_path=file_path,
            category=ChunkCategory.CONTRACT,
            lifecycle=lifecycle,
            scope=scope,
            breadcrumb=breadcrumb,
            commit_sha=commit_sha,
            tags=tags,
            content=f"```python\n{contract_code}\n```",
        )

    def _format_method_signature(self, node: Node) -> tuple[str, str]:
        """Format method signature with docstring for inclusion in class contract."""
        decorators: list[str] = []
        fn_node = node
        if node.type == "decorated_definition":
            for child in node.children:
                if child.type == "decorator":
                    dec = safe_decode(child.text)
                    if dec:
                        decorators.append(dec)
                elif child.type == "function_definition":
                    fn_node = child

        name_node = fn_node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name:
            return "", ""

        # Filter private methods unless in dunder whitelist
        if name.startswith("_") and name not in _DUNDER_WHITELIST:
            return "", ""

        params_node = fn_node.child_by_field_name("parameters")
        params_text = safe_decode(params_node.text) if params_node else "()"
        ret_node = fn_node.child_by_field_name("return_type")
        ret_text = f" -> {safe_decode(ret_node.text)}" if ret_node else ""

        is_async = any(c.type == "async" for c in fn_node.children)
        fn_keyword = "async def" if is_async else "def"

        body_node = fn_node.child_by_field_name("body")
        docstring = self._extract_docstring(body_node) if body_node else ""

        lines: list[str] = []
        for dec in decorators:
            lines.append(f"    {dec}")
        lines.append(f"    {fn_keyword} {name}{params_text}{ret_text}:")
        if docstring:
            lines.append(f'        """{docstring}"""')
        lines.append("        ...")

        return "\n".join(lines), name

    def _extract_docstring(self, body_node: Node) -> str:
        """Extract docstring from a function or class body."""
        for child in body_node.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        raw = safe_decode(sub.text)
                        for q in ('"""', "'''"):
                            if raw.startswith(q) and raw.endswith(q) and len(raw) >= 6:
                                return raw[3:-3].strip()
                        return raw.strip("\"' ")
                break
        return ""
