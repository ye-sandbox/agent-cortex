"""TypeScript and TSX code AST contract parser extracting types, classes, and functions."""

from __future__ import annotations

import logging
from typing import ClassVar

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from cortex.models.chunk import ChunkCategory, ChunkLifecycle, ChunkScope, DocumentChunk
from cortex.parsers.base import BaseParser, format_breadcrumb
from cortex.parsers.code.common import build_contract_id, extract_preceding_comments, safe_decode

logger = logging.getLogger(__name__)


class TypeScriptContractParser(BaseParser):
    """Extracts architectural contracts (types, classes, functions) from TS/TSX."""

    _ts_parser: ClassVar[Parser | None] = None
    _tsx_parser: ClassVar[Parser | None] = None

    @classmethod
    def get_parser(cls, is_tsx: bool = False) -> Parser:
        """Lazily initialize and return either TS or TSX Tree-Sitter parser."""
        if is_tsx:
            if cls._tsx_parser is None:
                tsx_lang = Language(tree_sitter_typescript.language_tsx())
                cls._tsx_parser = Parser(tsx_lang)
            return cls._tsx_parser

        if cls._ts_parser is None:
            ts_lang = Language(tree_sitter_typescript.language_typescript())
            cls._ts_parser = Parser(ts_lang)
        return cls._ts_parser

    def parse(
        self,
        content: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle = ChunkLifecycle.ACTIVE,
        scope: ChunkScope = ChunkScope.INTERNAL,
    ) -> list[DocumentChunk]:
        """Parse TypeScript source content into contract DocumentChunk records."""
        if not content.strip():
            return []

        is_tsx = file_path.endswith((".tsx", ".jsx"))
        parser = self.get_parser(is_tsx=is_tsx)
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
            is_exported = False
            decl_node: Node = node

            if node.type == "export_statement":
                is_exported = True
                for child in node.children:
                    if child.type in (
                        "interface_declaration",
                        "type_alias_declaration",
                        "enum_declaration",
                        "class_declaration",
                        "function_declaration",
                        "lexical_declaration",
                    ):
                        decl_node = child
                        break

            chunk = self._process_declaration(
                node=decl_node,
                parent_node=node,
                is_exported=is_exported,
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

    def _process_declaration(
        self,
        node: Node,
        parent_node: Node,
        is_exported: bool,
        lines: list[str],
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Route declaration node to the appropriate contract chunk generator."""
        doc_row = parent_node.start_point.row if is_exported else node.start_point.row
        doc_comment = extract_preceding_comments(doc_row, lines, ("//", "/*", "*"))

        if node.type == "interface_declaration":
            return self._parse_interface_or_type(
                node=node,
                kind="interface",
                is_exported=is_exported,
                doc_comment=doc_comment,
                repo=repo,
                file_path=file_path,
                commit_sha=commit_sha,
                lifecycle=lifecycle,
                scope=scope,
                slug_counts=slug_counts,
            )

        if node.type == "type_alias_declaration":
            return self._parse_interface_or_type(
                node=node,
                kind="type",
                is_exported=is_exported,
                doc_comment=doc_comment,
                repo=repo,
                file_path=file_path,
                commit_sha=commit_sha,
                lifecycle=lifecycle,
                scope=scope,
                slug_counts=slug_counts,
            )

        if node.type == "enum_declaration":
            return self._parse_enum(
                node=node,
                is_exported=is_exported,
                doc_comment=doc_comment,
                repo=repo,
                file_path=file_path,
                commit_sha=commit_sha,
                lifecycle=lifecycle,
                scope=scope,
                slug_counts=slug_counts,
            )

        if node.type == "class_declaration":
            return self._parse_class(
                node=node,
                is_exported=is_exported,
                doc_comment=doc_comment,
                repo=repo,
                file_path=file_path,
                commit_sha=commit_sha,
                lifecycle=lifecycle,
                scope=scope,
                slug_counts=slug_counts,
            )

        if node.type == "function_declaration":
            return self._parse_function(
                node=node,
                is_exported=is_exported,
                doc_comment=doc_comment,
                repo=repo,
                file_path=file_path,
                commit_sha=commit_sha,
                lifecycle=lifecycle,
                scope=scope,
                slug_counts=slug_counts,
            )

        if node.type == "lexical_declaration":
            return self._parse_lexical_function(
                node=node,
                is_exported=is_exported,
                doc_comment=doc_comment,
                repo=repo,
                file_path=file_path,
                commit_sha=commit_sha,
                lifecycle=lifecycle,
                scope=scope,
                slug_counts=slug_counts,
            )

        return None

    def _parse_interface_or_type(
        self,
        node: Node,
        kind: str,
        is_exported: bool,
        doc_comment: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Parse interface or type alias declaration."""
        name_node = node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name:
            return None

        raw_contract = safe_decode(node.text)
        if is_exported and not raw_contract.startswith("export "):
            raw_contract = f"export {raw_contract}"

        content_lines: list[str] = []
        if doc_comment:
            content_lines.append(doc_comment)
        content_lines.append(raw_contract)

        chunk_id = build_contract_id(repo, file_path, kind, name, slug_counts)
        breadcrumb = format_breadcrumb(repo, file_path, f"{kind} {name}")
        tags = ["typescript", kind, name]

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
            content=f"```typescript\n{'\n'.join(content_lines)}\n```",
        )

    def _parse_enum(
        self,
        node: Node,
        is_exported: bool,
        doc_comment: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Parse enum declaration."""
        name_node = node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name:
            return None

        raw_enum = safe_decode(node.text)
        if is_exported and not raw_enum.startswith("export "):
            raw_enum = f"export {raw_enum}"

        content_lines: list[str] = []
        if doc_comment:
            content_lines.append(doc_comment)
        content_lines.append(raw_enum)

        chunk_id = build_contract_id(repo, file_path, "enum", name, slug_counts)
        breadcrumb = format_breadcrumb(repo, file_path, f"enum {name}")
        tags = ["typescript", "enum", name]

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
            content=f"```typescript\n{'\n'.join(content_lines)}\n```",
        )

    def _parse_class(
        self,
        node: Node,
        is_exported: bool,
        doc_comment: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Parse class declaration, extracting signatures of public methods and members."""
        name_node = node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name:
            return None

        # Heritage (extends / implements)
        heritage_parts: list[str] = []
        for child in node.children:
            if child.type in ("class_heritage", "heritage_clause"):
                h_text = safe_decode(child.text)
                if h_text:
                    heritage_parts.append(h_text)
        heritage_str = f" {' '.join(heritage_parts)}" if heritage_parts else ""

        # Extract public fields and methods
        body_node = node.child_by_field_name("body")
        members: list[str] = []
        tags = ["typescript", "class", name]

        if body_node:
            for member in body_node.children:
                if member.type == "public_field_definition":
                    f_text = safe_decode(member.text).rstrip(";")
                    if "private" not in f_text:
                        members.append(f"    {f_text};")
                elif member.type == "method_definition":
                    method_sig = self._format_ts_method(member)
                    if method_sig:
                        members.append(method_sig)

        lines: list[str] = []
        if doc_comment:
            lines.append(doc_comment)
        export_kw = "export " if is_exported else ""
        lines.append(f"{export_kw}class {name}{heritage_str} {{")
        if members:
            lines.extend(members)
        else:
            lines.append("    // ...")
        lines.append("}")

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
            content=f"```typescript\n{'\n'.join(lines)}\n```",
        )

    def _parse_function(
        self,
        node: Node,
        is_exported: bool,
        doc_comment: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Parse standalone function declaration."""
        name_node = node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name:
            return None

        params_node = node.child_by_field_name("parameters")
        params = safe_decode(params_node.text) if params_node else "()"
        ret_node = node.child_by_field_name("return_type")
        ret = safe_decode(ret_node.text) if ret_node else ""

        is_async = any(c.type == "async" for c in node.children)
        fn_kw = "async function" if is_async else "function"
        export_kw = "export " if is_exported else ""

        lines: list[str] = []
        if doc_comment:
            lines.append(doc_comment)
        lines.append(f"{export_kw}{fn_kw} {name}{params}{ret};")

        tags = ["typescript", "function", name]
        if is_async:
            tags.append("async")

        chunk_id = build_contract_id(repo, file_path, "func", name, slug_counts)
        breadcrumb = format_breadcrumb(repo, file_path, f"function {name}")

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
            content=f"```typescript\n{'\n'.join(lines)}\n```",
        )

    def _parse_lexical_function(
        self,
        node: Node,
        is_exported: bool,
        doc_comment: str,
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Parse exported arrow function or function expression in a const/let declaration."""
        for decl in node.children:
            if decl.type == "variable_declarator":
                name_node = decl.child_by_field_name("name")
                val_node = decl.child_by_field_name("value")
                if not name_node or not val_node:
                    continue
                if val_node.type != "arrow_function":
                    continue

                name = safe_decode(name_node.text)
                if not name:
                    continue

                params_node = val_node.child_by_field_name("parameters")
                params = safe_decode(params_node.text) if params_node else "()"
                ret_node = val_node.child_by_field_name("return_type")
                ret = safe_decode(ret_node.text) if ret_node else ""

                is_async = any(c.type == "async" for c in val_node.children)
                async_kw = "async " if is_async else ""
                export_kw = "export " if is_exported else ""

                lines: list[str] = []
                if doc_comment:
                    lines.append(doc_comment)
                lines.append(f"{export_kw}const {name} = {async_kw}{params}{ret} => ...;")

                tags = ["typescript", "function", name]
                if is_async:
                    tags.append("async")

                chunk_id = build_contract_id(repo, file_path, "func", name, slug_counts)
                breadcrumb = format_breadcrumb(repo, file_path, f"const {name}")

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
                    content=f"```typescript\n{'\n'.join(lines)}\n```",
                )
        return None

    def _format_ts_method(self, method_node: Node) -> str | None:
        """Extract and format a public method signature from a class."""
        name_node = method_node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name:
            return None

        # Filter out private methods
        member_text = safe_decode(method_node.text).splitlines()[0]
        if "private" in member_text or name.startswith("_"):
            return None

        params_node = method_node.child_by_field_name("parameters")
        params = safe_decode(params_node.text) if params_node else "()"
        ret_node = method_node.child_by_field_name("return_type")
        ret = safe_decode(ret_node.text) if ret_node else ""

        modifiers: list[str] = []
        if "public" in member_text:
            modifiers.append("public")
        if "static" in member_text:
            modifiers.append("static")
        if "async" in member_text:
            modifiers.append("async")

        prefix = f"{' '.join(modifiers)} " if modifiers else ""
        return f"    {prefix}{name}{params}{ret};"
