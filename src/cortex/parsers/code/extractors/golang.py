"""Go AST-based code signature and dependency extractor."""

from __future__ import annotations

import logging
from typing import ClassVar

import tree_sitter_go
from tree_sitter import Language, Node, Parser

from cortex.models.graph import (
    CodeDependency,
    CodeSignature,
    DependencyEdgeType,
)
from cortex.parsers.code.common import (
    extract_preceding_comments,
    safe_decode,
)
from cortex.parsers.code.extractors.base import BaseASTExtractor, node_signature_line

logger = logging.getLogger(__name__)


class GolangASTExtractor(BaseASTExtractor):
    """Extracts code signatures and dependencies from Go source AST."""

    _parser: ClassVar[Parser | None] = None

    @classmethod
    def get_parser(cls) -> Parser:
        """Lazily initialize Go Tree-Sitter parser."""
        if cls._parser is None:
            go_lang = Language(tree_sitter_go.language())
            cls._parser = Parser(go_lang)
        return cls._parser

    def extract(
        self,
        content: str,
        repo: str,
        file_path: str,
    ) -> tuple[list[CodeSignature], list[CodeDependency]]:
        """Extract signatures and dependencies from Go code."""
        if not content.strip() or file_path.endswith("_test.go"):
            return [], []

        parser = self.get_parser()
        source_bytes = content.encode("utf-8")
        try:
            tree = parser.parse(source_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tree-sitter failed parsing Go %s: %s", file_path, exc)
            return [], []

        lines = content.splitlines()
        signatures: list[CodeSignature] = []
        dependencies: list[CodeDependency] = []

        for node in tree.root_node.children:
            if node.type == "import_declaration":
                self._extract_import(node, repo, file_path, dependencies)
            elif node.type == "type_declaration":
                self._extract_type_declaration(node, repo, file_path, lines, signatures)
            elif node.type == "function_declaration":
                self._extract_function(node, repo, file_path, lines, signatures, dependencies)
            elif node.type == "method_declaration":
                self._extract_method(node, repo, file_path, lines, signatures, dependencies)

        return signatures, dependencies

    def _extract_import(
        self,
        node: Node,
        repo: str,
        file_path: str,
        dependencies: list[CodeDependency],
    ) -> None:
        raw_stmt = safe_decode(node.text)
        line_no = node.start_point.row + 1

        for child in node.children:
            if child.type == "import_spec":
                path_node = child.child_by_field_name("path")
                name_node = child.child_by_field_name("name")
                pkg_path = safe_decode(path_node.text).strip('"') if path_node else ""
                alias = safe_decode(name_node.text) if name_node else ""
                if pkg_path:
                    dep_id = CodeDependency.build_id(
                        repo, file_path, DependencyEdgeType.IMPORT, pkg_path, alias, line_no
                    )
                    dependencies.append(
                        CodeDependency(
                            id=dep_id,
                            source_repo=repo,
                            source_file=file_path,
                            edge_type=DependencyEdgeType.IMPORT,
                            target_module=pkg_path,
                            target_symbol=alias,
                            line_number=line_no,
                            raw_statement=raw_stmt,
                        )
                    )
            elif child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec":
                        path_node = spec.child_by_field_name("path")
                        name_node = spec.child_by_field_name("name")
                        pkg_path = safe_decode(path_node.text).strip('"') if path_node else ""
                        alias = safe_decode(name_node.text) if name_node else ""
                        spec_line = spec.start_point.row + 1
                        if pkg_path:
                            dep_id = CodeDependency.build_id(
                                repo,
                                file_path,
                                DependencyEdgeType.IMPORT,
                                pkg_path,
                                alias,
                                spec_line,
                            )
                            dependencies.append(
                                CodeDependency(
                                    id=dep_id,
                                    source_repo=repo,
                                    source_file=file_path,
                                    edge_type=DependencyEdgeType.IMPORT,
                                    target_module=pkg_path,
                                    target_symbol=alias,
                                    line_number=spec_line,
                                    raw_statement=safe_decode(spec.text),
                                )
                            )

    def _extract_type_declaration(
        self,
        node: Node,
        repo: str,
        file_path: str,
        lines: list[str],
        signatures: list[CodeSignature],
    ) -> None:
        for child in node.children:
            if child.type == "type_spec":
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")
                if not name_node or not type_node:
                    continue
                type_name = safe_decode(name_node.text)
                exported = bool(type_name and type_name[0].isupper())

                kind = "type"
                if type_node.type == "struct_type":
                    kind = "struct"
                elif type_node.type == "interface_type":
                    kind = "interface"

                sig_id = CodeSignature.build_id(repo, file_path, kind, type_name)
                signatures.append(
                    CodeSignature(
                        id=sig_id,
                        repo=repo,
                        file_path=file_path,
                        language="go",
                        kind=kind,
                        identifier=type_name,
                        signature=node_signature_line(child, lines),
                        docstring=extract_preceding_comments(
                            node.start_point.row, lines, ("//", "/*")
                        ),
                        line_start=child.start_point.row + 1,
                        line_end=child.end_point.row + 1,
                        exported=exported,
                        calls=[],
                    )
                )

    def _extract_function(
        self,
        node: Node,
        repo: str,
        file_path: str,
        lines: list[str],
        signatures: list[CodeSignature],
        dependencies: list[CodeDependency],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        func_name = safe_decode(name_node.text)
        exported = bool(func_name and func_name[0].isupper())
        calls = self._collect_calls(node)
        line_no = node.start_point.row + 1

        for call_sym in calls:
            dep_id = CodeDependency.build_id(
                repo, file_path, DependencyEdgeType.CALL, "", call_sym, line_no
            )
            dependencies.append(
                CodeDependency(
                    id=dep_id,
                    source_repo=repo,
                    source_file=file_path,
                    source_symbol=func_name,
                    edge_type=DependencyEdgeType.CALL,
                    target_module="",
                    target_symbol=call_sym,
                    line_number=line_no,
                    raw_statement=f"{call_sym}(...)",
                )
            )

        sig_id = CodeSignature.build_id(repo, file_path, "function", func_name)
        signatures.append(
            CodeSignature(
                id=sig_id,
                repo=repo,
                file_path=file_path,
                language="go",
                kind="function",
                identifier=func_name,
                signature=node_signature_line(node, lines),
                docstring=extract_preceding_comments(node.start_point.row, lines, ("//", "/*")),
                line_start=node.start_point.row + 1,
                line_end=node.end_point.row + 1,
                exported=exported,
                calls=calls,
            )
        )

    def _extract_method(
        self,
        node: Node,
        repo: str,
        file_path: str,
        lines: list[str],
        signatures: list[CodeSignature],
        dependencies: list[CodeDependency],
    ) -> None:
        name_node = node.child_by_field_name("name")
        rec_node = node.child_by_field_name("receiver")
        if not name_node or not rec_node:
            return

        method_name = safe_decode(name_node.text)
        rec_text = safe_decode(rec_node.text).strip("()").strip("*").strip()
        # Extract receiver type name from receiver param list
        parts = rec_text.split()
        rec_type = parts[-1].strip("*") if parts else "Receiver"

        qual_name = f"{rec_type}.{method_name}"
        exported = bool(method_name and method_name[0].isupper())
        calls = self._collect_calls(node)
        line_no = node.start_point.row + 1

        for call_sym in calls:
            dep_id = CodeDependency.build_id(
                repo, file_path, DependencyEdgeType.CALL, "", call_sym, line_no
            )
            dependencies.append(
                CodeDependency(
                    id=dep_id,
                    source_repo=repo,
                    source_file=file_path,
                    source_symbol=qual_name,
                    edge_type=DependencyEdgeType.CALL,
                    target_module="",
                    target_symbol=call_sym,
                    line_number=line_no,
                    raw_statement=f"{call_sym}(...)",
                )
            )

        sig_id = CodeSignature.build_id(repo, file_path, "method", qual_name)
        signatures.append(
            CodeSignature(
                id=sig_id,
                repo=repo,
                file_path=file_path,
                language="go",
                kind="method",
                identifier=qual_name,
                signature=node_signature_line(node, lines),
                docstring=extract_preceding_comments(node.start_point.row, lines, ("//", "/*")),
                line_start=node.start_point.row + 1,
                line_end=node.end_point.row + 1,
                exported=exported,
                calls=calls,
            )
        )

    def _collect_calls(self, node: Node) -> list[str]:
        calls: list[str] = []
        stack = [node]
        while stack:
            curr = stack.pop()
            if curr.type == "call_expression":
                fn_node = curr.child_by_field_name("function")
                if fn_node:
                    fn_name = safe_decode(fn_node.text)
                    if fn_name and fn_name not in calls:
                        calls.append(fn_name)
            for child in reversed(curr.children):
                stack.append(child)
        return calls
