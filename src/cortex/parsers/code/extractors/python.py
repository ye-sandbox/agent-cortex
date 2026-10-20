"""Python AST-based code signature and dependency extractor."""

from __future__ import annotations

import logging
from typing import ClassVar

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from cortex.models.graph import (
    CodeDependency,
    CodeSignature,
    DependencyEdgeType,
)
from cortex.parsers.code.common import (
    clean_docstring,
    extract_preceding_comments,
    safe_decode,
)
from cortex.parsers.code.extractors.base import BaseASTExtractor, node_signature_line

logger = logging.getLogger(__name__)

_PY_DUNDER_WHITELIST = frozenset(
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


class PythonASTExtractor(BaseASTExtractor):
    """Extracts code signatures and dependencies from Python source AST."""

    _parser: ClassVar[Parser | None] = None

    @classmethod
    def get_parser(cls) -> Parser:
        """Lazily initialize Python Tree-Sitter parser."""
        if cls._parser is None:
            py_lang = Language(tree_sitter_python.language())
            cls._parser = Parser(py_lang)
        return cls._parser

    def extract(
        self,
        content: str,
        repo: str,
        file_path: str,
    ) -> tuple[list[CodeSignature], list[CodeDependency]]:
        """Extract signatures and dependencies from Python code."""
        if not content.strip():
            return [], []

        parser = self.get_parser()
        source_bytes = content.encode("utf-8")
        try:
            tree = parser.parse(source_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tree-sitter failed parsing Python %s: %s", file_path, exc)
            return [], []

        lines = content.splitlines()
        signatures: list[CodeSignature] = []
        dependencies: list[CodeDependency] = []

        for node in tree.root_node.children:
            target_node = node
            if node.type == "decorated_definition":
                for child in node.children:
                    if child.type in ("class_definition", "function_definition"):
                        target_node = child
                        break

            if target_node.type == "import_statement":
                self._extract_import(target_node, repo, file_path, dependencies)
            elif target_node.type == "import_from_statement":
                self._extract_import_from(target_node, repo, file_path, dependencies)
            elif target_node.type == "class_definition":
                self._extract_class(target_node, repo, file_path, lines, signatures, dependencies)
            elif target_node.type == "function_definition":
                self._extract_function(
                    target_node, repo, file_path, lines, signatures, dependencies
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

        for child in node.children:
            if child.type == "dotted_name":
                mod_name = safe_decode(child.text)
                if mod_name:
                    dep_id = CodeDependency.build_id(
                        repo, file_path, DependencyEdgeType.IMPORT, mod_name, "", line_no
                    )
                    dependencies.append(
                        CodeDependency(
                            id=dep_id,
                            source_repo=repo,
                            source_file=file_path,
                            edge_type=DependencyEdgeType.IMPORT,
                            target_module=mod_name,
                            line_number=line_no,
                            raw_statement=raw_stmt,
                        )
                    )
            elif child.type == "aliased_import":
                name_node = child.child_by_field_name("name")
                alias_node = child.child_by_field_name("alias")
                mod_name = safe_decode(name_node.text) if name_node else ""
                alias_name = safe_decode(alias_node.text) if alias_node else ""
                if mod_name:
                    dep_id = CodeDependency.build_id(
                        repo, file_path, DependencyEdgeType.IMPORT, mod_name, alias_name, line_no
                    )
                    dependencies.append(
                        CodeDependency(
                            id=dep_id,
                            source_repo=repo,
                            source_file=file_path,
                            edge_type=DependencyEdgeType.IMPORT,
                            target_module=mod_name,
                            target_symbol=alias_name,
                            line_number=line_no,
                            raw_statement=raw_stmt,
                        )
                    )

    def _extract_import_from(
        self,
        node: Node,
        repo: str,
        file_path: str,
        dependencies: list[CodeDependency],
    ) -> None:
        raw_stmt = safe_decode(node.text)
        line_no = node.start_point.row + 1
        module_name = ""
        imported_names: list[tuple[str, str]] = []

        mod_node = node.child_by_field_name("module_name")
        if mod_node:
            module_name = safe_decode(mod_node.text)
        else:
            # Relative import without module name e.g. from . import foo
            for child in node.children:
                if child.type == "relative_import":
                    module_name = safe_decode(child.text)
                    break

        for child in node.children:
            if child.type == "dotted_name" and child != mod_node:
                sym = safe_decode(child.text)
                if sym:
                    imported_names.append((sym, ""))
            elif child.type == "aliased_import":
                n_node = child.child_by_field_name("name")
                a_node = child.child_by_field_name("alias")
                sym = safe_decode(n_node.text) if n_node else ""
                alias = safe_decode(a_node.text) if a_node else ""
                if sym:
                    imported_names.append((sym, alias))

        for sym, _alias in imported_names:
            dep_id = CodeDependency.build_id(
                repo, file_path, DependencyEdgeType.IMPORT, module_name, sym, line_no
            )
            dependencies.append(
                CodeDependency(
                    id=dep_id,
                    source_repo=repo,
                    source_file=file_path,
                    edge_type=DependencyEdgeType.IMPORT,
                    target_module=module_name,
                    target_symbol=sym,
                    line_number=line_no,
                    raw_statement=raw_stmt,
                )
            )

    def _extract_class(
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
        class_name = safe_decode(name_node.text)
        exported = not class_name.startswith("_")

        # Superclasses heritage
        superclasses: list[str] = []
        sup_node = node.child_by_field_name("superclasses")
        line_no = node.start_point.row + 1
        if sup_node:
            for child in sup_node.children:
                if child.type in ("identifier", "attribute"):
                    sup_name = safe_decode(child.text)
                    if sup_name:
                        superclasses.append(sup_name)
                        dep_id = CodeDependency.build_id(
                            repo, file_path, DependencyEdgeType.EXTENDS, "", sup_name, line_no
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
                                raw_statement=safe_decode(node.text).splitlines()[0],
                            )
                        )

        docstring = self._extract_docstring(node, lines)
        header_sig = node_signature_line(node, lines)

        # Extract calls inside class body
        calls = self._collect_calls(node)

        sig_id = CodeSignature.build_id(repo, file_path, "class", class_name)
        signatures.append(
            CodeSignature(
                id=sig_id,
                repo=repo,
                file_path=file_path,
                language="python",
                kind="class",
                identifier=class_name,
                signature=header_sig,
                docstring=docstring,
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
                target = child
                if child.type == "decorated_definition":
                    for d_child in child.children:
                        if d_child.type == "function_definition":
                            target = d_child
                            break
                if target.type == "function_definition":
                    self._extract_method(
                        target, class_name, repo, file_path, lines, signatures, dependencies
                    )

    def _extract_method(
        self,
        node: Node,
        class_name: str,
        repo: str,
        file_path: str,
        lines: list[str],
        signatures: list[CodeSignature],
        dependencies: list[CodeDependency],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        method_name = safe_decode(name_node.text)
        exported = not method_name.startswith("_") or method_name in _PY_DUNDER_WHITELIST

        qual_name = f"{class_name}.{method_name}"
        docstring = self._extract_docstring(node, lines)
        header_sig = node_signature_line(node, lines)
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
                language="python",
                kind="method",
                identifier=qual_name,
                signature=header_sig,
                docstring=docstring,
                line_start=node.start_point.row + 1,
                line_end=node.end_point.row + 1,
                exported=exported,
                calls=calls,
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
        exported = not func_name.startswith("_")

        docstring = self._extract_docstring(node, lines)
        header_sig = node_signature_line(node, lines)
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
                language="python",
                kind="function",
                identifier=func_name,
                signature=header_sig,
                docstring=docstring,
                line_start=node.start_point.row + 1,
                line_end=node.end_point.row + 1,
                exported=exported,
                calls=calls,
            )
        )

    def _extract_docstring(self, node: Node, lines: list[str]) -> str:
        body = node.child_by_field_name("body")
        if body and body.children:
            first_stmt = body.children[0]
            if first_stmt.type == "expression_statement" and first_stmt.children:
                expr = first_stmt.children[0]
                if expr.type == "string":
                    return clean_docstring(safe_decode(expr.text))
        return extract_preceding_comments(node.start_point.row, lines, ("#",))

    def _collect_calls(self, node: Node) -> list[str]:
        calls: list[str] = []
        stack = [node]
        while stack:
            curr = stack.pop()
            if curr.type == "call":
                fn_node = curr.child_by_field_name("function")
                if fn_node:
                    fn_name = safe_decode(fn_node.text)
                    if fn_name and fn_name not in calls:
                        calls.append(fn_name)
            for child in reversed(curr.children):
                stack.append(child)
        return calls
