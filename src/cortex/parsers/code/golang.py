"""Go code AST contract parser extracting exported types, interfaces, funcs, and methods."""

from __future__ import annotations

import logging
import re
from typing import ClassVar

import tree_sitter_go
from tree_sitter import Language, Node, Parser

from cortex.models.chunk import ChunkCategory, ChunkLifecycle, ChunkScope, DocumentChunk
from cortex.parsers.base import BaseParser, format_breadcrumb
from cortex.parsers.code.common import build_contract_id, extract_preceding_comments, safe_decode

logger = logging.getLogger(__name__)


class GoContractParser(BaseParser):
    """Extracts architectural contracts (types, structs, funcs) from Go code."""

    _parser: ClassVar[Parser | None] = None

    @classmethod
    def get_parser(cls) -> Parser:
        """Lazily initialize and return the Tree-Sitter Go parser."""
        if cls._parser is None:
            go_lang = Language(tree_sitter_go.language())
            cls._parser = Parser(go_lang)
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
        """Parse Go source content into contract DocumentChunk records."""
        # Skip unit/integration test files from contract indexing
        if file_path.endswith("_test.go") or not content.strip():
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
            if node.type == "type_declaration":
                type_chunks = self._parse_type_declaration(
                    node=node,
                    lines=lines,
                    repo=repo,
                    file_path=file_path,
                    commit_sha=commit_sha,
                    lifecycle=lifecycle,
                    scope=scope,
                    slug_counts=slug_counts,
                )
                chunks.extend(type_chunks)

            elif node.type == "function_declaration":
                func_chunk = self._parse_function(
                    node=node,
                    lines=lines,
                    repo=repo,
                    file_path=file_path,
                    commit_sha=commit_sha,
                    lifecycle=lifecycle,
                    scope=scope,
                    slug_counts=slug_counts,
                )
                if func_chunk:
                    chunks.append(func_chunk)

            elif node.type == "method_declaration":
                method_chunk = self._parse_method(
                    node=node,
                    lines=lines,
                    repo=repo,
                    file_path=file_path,
                    commit_sha=commit_sha,
                    lifecycle=lifecycle,
                    scope=scope,
                    slug_counts=slug_counts,
                )
                if method_chunk:
                    chunks.append(method_chunk)

        return chunks

    def _parse_type_declaration(
        self,
        node: Node,
        lines: list[str],
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> list[DocumentChunk]:
        """Parse type declaration block which may contain multiple type specs."""
        doc_comment = extract_preceding_comments(node.start_point.row, lines, ("//",))
        chunks: list[DocumentChunk] = []

        for spec in node.children:
            if spec.type != "type_spec":
                continue

            name_node = spec.child_by_field_name("name")
            name = safe_decode(name_node.text) if name_node else ""
            if not name or not name[0].isupper():
                # In Go, uncapitalized types are package-private
                continue

            type_node = spec.child_by_field_name("type")
            type_kind = type_node.type if type_node else "type"
            if "interface" in type_kind:
                kind_label = "interface"
            elif "struct" in type_kind:
                kind_label = "struct"
            else:
                kind_label = "type"

            raw_spec = safe_decode(spec.text)
            content_lines: list[str] = []
            if doc_comment:
                content_lines.append(doc_comment)
            content_lines.append(f"type {raw_spec}")

            tags = ["go", kind_label, name]
            chunk_id = build_contract_id(repo, file_path, kind_label, name, slug_counts)
            breadcrumb = format_breadcrumb(repo, file_path, f"type {name}")

            chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    repo=repo,
                    file_path=file_path,
                    category=ChunkCategory.CONTRACT,
                    lifecycle=lifecycle,
                    scope=scope,
                    breadcrumb=breadcrumb,
                    commit_sha=commit_sha,
                    tags=tags,
                    content=f"```go\n{'\n'.join(content_lines)}\n```",
                )
            )

        return chunks

    def _parse_function(
        self,
        node: Node,
        lines: list[str],
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Parse standalone exported function declaration."""
        name_node = node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name or not name[0].isupper():
            # In Go, uncapitalized functions are package-private
            return None

        doc_comment = extract_preceding_comments(node.start_point.row, lines, ("//",))
        params_node = node.child_by_field_name("parameters")
        params = safe_decode(params_node.text) if params_node else "()"

        res_node = node.child_by_field_name("result")
        res = f" {safe_decode(res_node.text)}" if res_node else ""

        content_lines: list[str] = []
        if doc_comment:
            content_lines.append(doc_comment)
        content_lines.append(f"func {name}{params}{res}")

        tags = ["go", "func", name]
        chunk_id = build_contract_id(repo, file_path, "func", name, slug_counts)
        breadcrumb = format_breadcrumb(repo, file_path, f"func {name}")

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
            content=f"```go\n{'\n'.join(content_lines)}\n```",
        )

    def _parse_method(
        self,
        node: Node,
        lines: list[str],
        repo: str,
        file_path: str,
        commit_sha: str,
        lifecycle: ChunkLifecycle,
        scope: ChunkScope,
        slug_counts: dict[str, int],
    ) -> DocumentChunk | None:
        """Parse exported receiver method declaration."""
        name_node = node.child_by_field_name("name")
        name = safe_decode(name_node.text) if name_node else ""
        if not name or not name[0].isupper():
            # Uncapitalized methods are package-private
            return None

        recv_node = node.child_by_field_name("receiver")
        recv_raw = safe_decode(recv_node.text) if recv_node else "()"

        doc_comment = extract_preceding_comments(node.start_point.row, lines, ("//",))
        params_node = node.child_by_field_name("parameters")
        params = safe_decode(params_node.text) if params_node else "()"

        res_node = node.child_by_field_name("result")
        res = f" {safe_decode(res_node.text)}" if res_node else ""

        # Extract receiver type name for tags (e.g. from `(c *Config)` -> `Config`)
        clean_recv = re.sub(r"[()*&]", "", recv_raw).strip()
        recv_type = clean_recv.split()[-1] if clean_recv else ""

        content_lines: list[str] = []
        if doc_comment:
            content_lines.append(doc_comment)
        content_lines.append(f"func {recv_raw} {name}{params}{res}")

        tags = ["go", "method", name]
        if recv_type:
            tags.append(recv_type)

        tag_recv = recv_type if recv_type else "recv"
        chunk_id = build_contract_id(repo, file_path, "method", f"{tag_recv}_{name}", slug_counts)
        breadcrumb = format_breadcrumb(repo, file_path, f"func {recv_raw} {name}")

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
            content=f"```go\n{'\n'.join(content_lines)}\n```",
        )
