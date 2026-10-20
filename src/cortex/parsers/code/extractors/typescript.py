"""TypeScript and TSX AST-based code signature and dependency extractor."""

from __future__ import annotations

import logging
from typing import ClassVar

import tree_sitter_typescript
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


def _ts_comments(node: Node, lines: list[str]) -> str:
    """Extract preceding comments for TypeScript nodes."""
    return extract_preceding_comments(node.start_point.row, lines, ("//", "/*", "*"))


class TypeScriptASTExtractor(BaseASTExtractor):
    """Extracts code signatures and dependencies from TypeScript / TSX source AST."""

    _ts_parser: ClassVar[Parser | None] = None
    _tsx_parser: ClassVar[Parser | None] = None

    @classmethod
    def get_parser(cls, is_tsx: bool = False) -> Parser:
        """Lazily initialize TypeScript / TSX Tree-Sitter parser."""
        if is_tsx:
            if cls._tsx_parser is None:
                tsx_lang = Language(tree_sitter_typescript.language_tsx())
                cls._tsx_parser = Parser(tsx_lang)
            return cls._tsx_parser
        if cls._ts_parser is None:
            ts_lang = Language(tree_sitter_typescript.language_typescript())
            cls._ts_parser = Parser(ts_lang)
        return cls._ts_parser

    def extract(
        self,
        content: str,
        repo: str,
        file_path: str,
    ) -> tuple[list[CodeSignature], list[CodeDependency]]:
        """Extract signatures and dependencies from TypeScript / TSX code."""
        if not content.strip():
            return [], []

        is_tsx = file_path.endswith((".tsx", ".jsx"))
        parser = self.get_parser(is_tsx=is_tsx)
        source_bytes = content.encode("utf-8")
        try:
            tree = parser.parse(source_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tree-sitter failed parsing TS %s: %s", file_path, exc)
            return [], []

        lines = content.splitlines()
        signatures: list[CodeSignature] = []
        dependencies: list[CodeDependency] = []

        for node in tree.root_node.children:
            is_exported = False
            target_node = node

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
                        target_node = child
                        break

            if target_node.type == "import_statement":
                self._extract_import(target_node, repo, file_path, dependencies)
            elif target_node.type == "interface_declaration":
                self._extract_interface(
                    target_node, is_exported, repo, file_path, lines, signatures, dependencies
                )
            elif target_node.type == "type_alias_declaration":
                self._extract_type_alias(
                    target_node, is_exported, repo, file_path, lines, signatures
                )
            elif target_node.type == "enum_declaration":
                self._extract_enum(target_node, is_exported, repo, file_path, lines, signatures)
            elif target_node.type == "class_declaration":
                self._extract_class(
                    target_node, is_exported, repo, file_path, lines, signatures, dependencies
                )
            elif target_node.type == "function_declaration":
                self._extract_function(
                    target_node, is_exported, repo, file_path, lines, signatures, dependencies
                )
            elif target_node.type == "lexical_declaration":
                self._extract_lexical(
                    target_node, is_exported, repo, file_path, lines, signatures, dependencies
                )

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

        source_node = node.child_by_field_name("source")
        target_mod = safe_decode(source_node.text).strip("'\"`") if source_node else ""
        if not target_mod:
            return

        imported_symbols: list[str] = []
        for child in node.children:
            if child.type == "import_clause":
                for ic_child in child.children:
                    if ic_child.type == "identifier":
                        imported_symbols.append(safe_decode(ic_child.text))
                    elif ic_child.type == "named_imports":
                        for spec in ic_child.children:
                            if spec.type == "import_specifier":
                                n_node = spec.child_by_field_name("name")
                                if n_node:
                                    imported_symbols.append(safe_decode(n_node.text))
                    elif ic_child.type == "namespace_import":
                        n_node = ic_child.child_by_field_name("name")
                        if n_node:
                            imported_symbols.append(f"* as {safe_decode(n_node.text)}")

        if not imported_symbols:
            dep_id = CodeDependency.build_id(
                repo, file_path, DependencyEdgeType.IMPORT, target_mod, "", line_no
            )
            dependencies.append(
                CodeDependency(
                    id=dep_id,
                    source_repo=repo,
                    source_file=file_path,
                    edge_type=DependencyEdgeType.IMPORT,
                    target_module=target_mod,
                    line_number=line_no,
                    raw_statement=raw_stmt,
                )
            )
        else:
            for sym in imported_symbols:
                dep_id = CodeDependency.build_id(
                    repo, file_path, DependencyEdgeType.IMPORT, target_mod, sym, line_no
                )
                dependencies.append(
                    CodeDependency(
                        id=dep_id,
                        source_repo=repo,
                        source_file=file_path,
                        edge_type=DependencyEdgeType.IMPORT,
                        target_module=target_mod,
                        target_symbol=sym,
                        line_number=line_no,
                        raw_statement=raw_stmt,
                    )
                )

    def _extract_interface(
        self,
        node: Node,
        exported: bool,
        repo: str,
        file_path: str,
        lines: list[str],
        signatures: list[CodeSignature],
        dependencies: list[CodeDependency],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = safe_decode(name_node.text)
        line_no = node.start_point.row + 1

        # Extends clause
        for child in node.children:
            if child.type in ("extends_clause", "extends_type_clause"):
                for super_type in child.children:
                    if super_type.type in ("type_identifier", "identifier"):
                        sup_name = safe_decode(super_type.text)
                        if sup_name:
                            dep_id = CodeDependency.build_id(
                                repo, file_path, DependencyEdgeType.EXTENDS, "", sup_name, line_no
                            )
                            dependencies.append(
                                CodeDependency(
                                    id=dep_id,
                                    source_repo=repo,
                                    source_file=file_path,
                                    source_symbol=name,
                                    edge_type=DependencyEdgeType.EXTENDS,
                                    target_module="",
                                    target_symbol=sup_name,
                                    line_number=line_no,
                                    raw_statement=node_signature_line(node, lines),
                                )
                            )

        sig_id = CodeSignature.build_id(repo, file_path, "interface", name)
        signatures.append(
            CodeSignature(
                id=sig_id,
                repo=repo,
                file_path=file_path,
                language="typescript",
                kind="interface",
                identifier=name,
                signature=node_signature_line(node, lines),
                docstring=_ts_comments(node, lines),
                line_start=node.start_point.row + 1,
                line_end=node.end_point.row + 1,
                exported=exported,
                calls=[],
            )
        )

    def _extract_type_alias(
        self,
        node: Node,
        exported: bool,
        repo: str,
        file_path: str,
        lines: list[str],
        signatures: list[CodeSignature],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = safe_decode(name_node.text)
        sig_id = CodeSignature.build_id(repo, file_path, "type", name)
        signatures.append(
            CodeSignature(
                id=sig_id,
                repo=repo,
                file_path=file_path,
                language="typescript",
                kind="type",
                identifier=name,
                signature=node_signature_line(node, lines),
                docstring=_ts_comments(node, lines),
                line_start=node.start_point.row + 1,
                line_end=node.end_point.row + 1,
                exported=exported,
                calls=[],
            )
        )

    def _extract_enum(
        self,
        node: Node,
        exported: bool,
        repo: str,
        file_path: str,
        lines: list[str],
        signatures: list[CodeSignature],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = safe_decode(name_node.text)
        sig_id = CodeSignature.build_id(repo, file_path, "enum", name)
        signatures.append(
            CodeSignature(
                id=sig_id,
                repo=repo,
                file_path=file_path,
                language="typescript",
                kind="enum",
                identifier=name,
                signature=node_signature_line(node, lines),
                docstring=_ts_comments(node, lines),
                line_start=node.start_point.row + 1,
                line_end=node.end_point.row + 1,
                exported=exported,
                calls=[],
            )
        )

    def _extract_class(
        self,
        node: Node,
        exported: bool,
        repo: str,
        file_path: str,
        lines: list[str],
        signatures: list[CodeSignature],
        dependencies: list[CodeDependency],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        class_name = safe_decode(name_node.text)
        line_no = node.start_point.row + 1

        # Class heritage (extends / implements)
        for child in node.children:
            if child.type == "class_heritage":
                for h_child in child.children:
                    if h_child.type == "extends_clause":
                        for super_cls in h_child.children:
                            if super_cls.type in ("identifier", "type_identifier"):
                                sup_name = safe_decode(super_cls.text)
                                if sup_name:
                                    dep_id = CodeDependency.build_id(
                                        repo,
                                        file_path,
                                        DependencyEdgeType.EXTENDS,
                                        "",
                                        sup_name,
                                        line_no,
                                    )
                                    dependencies.append(
                                        CodeDependency(
                                            id=dep_id,
                                            source_repo=repo,
                                            source_file=file_path,
                                            source_symbol=class_name,
                                            edge_type=DependencyEdgeType.EXTENDS,
                                            target_module="",
                                            target_symbol=sup_name,
                                            line_number=line_no,
                                            raw_statement=node_signature_line(node, lines),
                                        )
                                    )
                    elif h_child.type == "implements_clause":
                        for iface in h_child.children:
                            if iface.type in ("identifier", "type_identifier"):
                                iface_name = safe_decode(iface.text)
                                if iface_name:
                                    dep_id = CodeDependency.build_id(
                                        repo,
                                        file_path,
                                        DependencyEdgeType.IMPLEMENTS,
                                        "",
                                        iface_name,
                                        line_no,
                                    )
                                    dependencies.append(
                                        CodeDependency(
                                            id=dep_id,
                                            source_repo=repo,
                                            source_file=file_path,
                                            source_symbol=class_name,
                                            edge_type=DependencyEdgeType.IMPLEMENTS,
                                            target_module="",
                                            target_symbol=iface_name,
                                            line_number=line_no,
                                            raw_statement=node_signature_line(node, lines),
                                        )
                                    )

        calls = self._collect_calls(node)
        sig_id = CodeSignature.build_id(repo, file_path, "class", class_name)
        signatures.append(
            CodeSignature(
                id=sig_id,
                repo=repo,
                file_path=file_path,
                language="typescript",
                kind="class",
                identifier=class_name,
                signature=node_signature_line(node, lines),
                docstring=_ts_comments(node, lines),
                line_start=node.start_point.row + 1,
                line_end=node.end_point.row + 1,
                exported=exported,
                calls=calls,
            )
        )

        # Methods
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "method_definition":
                    m_name_node = child.child_by_field_name("name")
                    if m_name_node:
                        m_name = safe_decode(m_name_node.text)
                        qual_name = f"{class_name}.{m_name}"
                        m_calls = self._collect_calls(child)
                        m_line_no = child.start_point.row + 1

                        for call_sym in m_calls:
                            dep_id = CodeDependency.build_id(
                                repo, file_path, DependencyEdgeType.CALL, "", call_sym, m_line_no
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
                                    line_number=m_line_no,
                                    raw_statement=f"{call_sym}(...)",
                                )
                            )

                        m_sig_id = CodeSignature.build_id(repo, file_path, "method", qual_name)
                        signatures.append(
                            CodeSignature(
                                id=m_sig_id,
                                repo=repo,
                                file_path=file_path,
                                language="typescript",
                                kind="method",
                                identifier=qual_name,
                                signature=node_signature_line(child, lines),
                                docstring=extract_preceding_comments(
                                    child.start_point.row, lines, ("//", "/*", "*")
                                ),
                                line_start=child.start_point.row + 1,
                                line_end=child.end_point.row + 1,
                                exported=not m_name.startswith("#") and not m_name.startswith("_"),
                                calls=m_calls,
                            )
                        )

    def _extract_function(
        self,
        node: Node,
        exported: bool,
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
                language="typescript",
                kind="function",
                identifier=func_name,
                signature=node_signature_line(node, lines),
                docstring=_ts_comments(node, lines),
                line_start=node.start_point.row + 1,
                line_end=node.end_point.row + 1,
                exported=exported,
                calls=calls,
            )
        )

    def _extract_lexical(
        self,
        node: Node,
        exported: bool,
        repo: str,
        file_path: str,
        lines: list[str],
        signatures: list[CodeSignature],
        dependencies: list[CodeDependency],
    ) -> None:
        for declarator in node.children:
            if declarator.type == "variable_declarator":
                name_node = declarator.child_by_field_name("name")
                value_node = declarator.child_by_field_name("value")
                is_fn_expr = value_node is not None and value_node.type in (
                    "arrow_function",
                    "function_expression",
                )
                if name_node and value_node and is_fn_expr:
                    fn_name = safe_decode(name_node.text)
                    calls = self._collect_calls(value_node)
                    line_no = declarator.start_point.row + 1

                    for call_sym in calls:
                        dep_id = CodeDependency.build_id(
                            repo, file_path, DependencyEdgeType.CALL, "", call_sym, line_no
                        )
                        dependencies.append(
                            CodeDependency(
                                id=dep_id,
                                source_repo=repo,
                                source_file=file_path,
                                source_symbol=fn_name,
                                edge_type=DependencyEdgeType.CALL,
                                target_module="",
                                target_symbol=call_sym,
                                line_number=line_no,
                                raw_statement=f"{call_sym}(...)",
                            )
                        )

                    sig_id = CodeSignature.build_id(repo, file_path, "function", fn_name)
                    signatures.append(
                        CodeSignature(
                            id=sig_id,
                            repo=repo,
                            file_path=file_path,
                            language="typescript",
                            kind="function",
                            identifier=fn_name,
                            signature=node_signature_line(declarator, lines),
                            docstring=extract_preceding_comments(
                                node.start_point.row, lines, ("//", "/*", "*")
                            ),
                            line_start=declarator.start_point.row + 1,
                            line_end=declarator.end_point.row + 1,
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
