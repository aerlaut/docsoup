"""JavaScript symbol extractor — parses .js files using Tree-sitter."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import tree_sitter_javascript as ts_js
from tree_sitter import Language, Node, Parser

from docsoup.models import Dependency, Symbol
from docsoup.parsing.base import SymbolExtractor

logger = logging.getLogger(__name__)

# Lazily initialised module-level parser.
_parser: Parser | None = None


def _get_parser() -> Parser:
    global _parser
    if _parser is None:
        lang = Language(ts_js.language())
        _parser = Parser(lang)
    return _parser


# Map tree-sitter node types to Symbol.kind values.
_KIND_MAP: dict[str, str] = {
    "function_declaration": "function",
    "function_expression": "function",
    "arrow_function": "function",
    "class_declaration": "class",
    "lexical_declaration": "variable",
    "variable_declaration": "variable",
}

_METHOD_KINDS = {"method_definition"}


class JavaScriptExtractor(SymbolExtractor):
    """
    Extracts exported symbols from JavaScript ``.js`` files.

    Handles both ESM (``export`` statements) and CommonJS
    (``module.exports`` / ``exports.x`` assignments).

    Entry-point resolution order:
    1. ``main`` field in package.json
    2. ``index.js`` in the package root
    """

    # ------------------------------------------------------------------
    # SymbolExtractor interface
    # ------------------------------------------------------------------

    def can_extract(self, dependency: Dependency) -> bool:
        return dependency.ecosystem == "node" and self._find_js_entry(dependency) is not None

    def extract(self, dependency: Dependency) -> list[Symbol]:
        entry = self._find_js_entry(dependency)
        if entry is None:
            return []

        try:
            source = entry.read_bytes()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", entry, exc)
            return []

        parser = _get_parser()
        tree = parser.parse(source)
        rel_path = str(entry.relative_to(dependency.path))

        symbols: list[Symbol] = []
        self._walk_program(tree.root_node, source, dependency, rel_path, symbols)
        return symbols

    # ------------------------------------------------------------------
    # Tree walking
    # ------------------------------------------------------------------

    def _walk_program(
        self,
        root: Node,
        source: bytes,
        dep: Dependency,
        rel_path: str,
        symbols: list[Symbol],
    ) -> None:
        """Collect declarations from a top-level AST index file."""
        # First pass: build a lookup of named declarations for CJS resolution.
        decl_index = _build_declaration_index(root, source)

        children = root.children
        for i, node in enumerate(children):
            preceding_comment = _extract_preceding_comment(children, i, source)

            if node.type == "export_statement":
                self._handle_esm_export(node, source, dep, rel_path, symbols, preceding_comment)

            elif node.type == "expression_statement":
                self._handle_cjs_expression(
                    node, source, dep, rel_path, symbols, decl_index
                )

    # ------------------------------------------------------------------
    # ESM export handling
    # ------------------------------------------------------------------

    def _handle_esm_export(
        self,
        export_node: Node,
        source: bytes,
        dep: Dependency,
        rel_path: str,
        symbols: list[Symbol],
        docstring: str | None,
    ) -> None:
        is_default = any(c.type == "default" for c in export_node.children)

        # Find the actual declaration child (skip 'export' / 'default' keywords).
        decl = _first_named_non_keyword(export_node, skip={"export", "default"})
        if decl is None:
            return

        kind = _KIND_MAP.get(decl.type)
        if kind is None:
            logger.debug("Unhandled JS declaration type %r — skipping", decl.type)
            return

        # For default exports the public binding name is always "default",
        # regardless of any internal function/class name.
        name = "default" if is_default else _extract_name(decl, source)
        if not name:
            return

        sig = _extract_signature(decl, source)
        line = export_node.start_point[0] + 1

        sym = Symbol(
            name=name,
            fqn=f"{dep.name}:{name}",
            library=dep.name,
            library_version=dep.version,
            kind=kind,
            signature=sig,
            source=sig,
            file_path=rel_path,
            line_number=line,
            docstring=docstring,
        )
        symbols.append(sym)

        # Recursively extract class methods.
        if kind == "class":
            body = _child_of_type(decl, "class_body")
            if body:
                self._extract_members(body, source, dep, rel_path, symbols, parent_name=name)

    def _extract_members(
        self,
        body: Node,
        source: bytes,
        dep: Dependency,
        rel_path: str,
        symbols: list[Symbol],
        parent_name: str,
    ) -> None:
        children = body.children
        for i, node in enumerate(children):
            if node.type not in _METHOD_KINDS:
                continue

            member_name = _extract_name(node, source)
            if not member_name:
                continue

            preceding_comment = _extract_preceding_comment(children, i, source)
            sig = _node_text(node, source)

            symbols.append(Symbol(
                name=member_name,
                fqn=f"{dep.name}:{parent_name}.{member_name}",
                library=dep.name,
                library_version=dep.version,
                kind="function",
                signature=f"{parent_name}.{sig}",
                source=f"{parent_name}.{sig}",
                file_path=rel_path,
                line_number=node.start_point[0] + 1,
                docstring=preceding_comment,
            ))

    # ------------------------------------------------------------------
    # CommonJS export handling
    # ------------------------------------------------------------------

    def _handle_cjs_expression(
        self,
        stmt_node: Node,
        source: bytes,
        dep: Dependency,
        rel_path: str,
        symbols: list[Symbol],
        decl_index: dict[str, _DeclInfo],
    ) -> None:
        """Handle expression_statement nodes that are CJS export assignments."""
        assign = _child_of_type(stmt_node, "assignment_expression")
        if assign is None:
            return

        lhs = assign.children[0]  # left side of '='
        rhs = assign.children[2]  # right side of '='

        if lhs.type != "member_expression":
            return

        lhs_text = _node_text(lhs, source)

        # ----------------------------------------------------------------
        # module.exports = { greet, Router, VERSION }
        # ----------------------------------------------------------------
        if lhs_text == "module.exports" and rhs.type == "object":
            for prop in rhs.children:
                if prop.type == "shorthand_property_identifier":
                    prop_name = _node_text(prop, source)
                    self._emit_cjs_symbol(
                        prop_name, prop, source, dep, rel_path, symbols, decl_index
                    )
                elif prop.type == "pair":
                    # { key: value } — less common, extract the value name
                    key_node = prop.children[0]
                    prop_name = _node_text(key_node, source).strip('"\'')
                    self._emit_cjs_symbol(
                        prop_name, prop, source, dep, rel_path, symbols, decl_index
                    )
            return

        # ----------------------------------------------------------------
        # module.exports.foo = ...  or  exports.foo = ...
        # ----------------------------------------------------------------
        obj_node = _child_of_type(lhs, "identifier", "member_expression")
        prop_node = _child_of_type(lhs, "property_identifier")
        if prop_node is None:
            return

        obj_text = _node_text(obj_node, source) if obj_node else ""
        if obj_text not in ("module.exports", "exports"):
            return

        prop_name = _node_text(prop_node, source)
        self._emit_cjs_symbol(
            prop_name, stmt_node, source, dep, rel_path, symbols, decl_index,
            rhs_override=rhs,
        )

    def _emit_cjs_symbol(
        self,
        name: str,
        ref_node: Node,
        source: bytes,
        dep: Dependency,
        rel_path: str,
        symbols: list[Symbol],
        decl_index: dict[str, _DeclInfo],
        rhs_override: Node | None = None,
    ) -> None:
        """Resolve *name* through the declaration index and emit a Symbol."""
        info = decl_index.get(name)
        if info:
            kind = info.kind
            sig = info.signature
            docstring = info.docstring
            line = info.line
        else:
            # Fallback: infer kind from the rhs node type.
            rhs = rhs_override
            kind = _KIND_MAP.get(rhs.type, "variable") if rhs else "variable"
            sig = _extract_signature(rhs, source) if rhs else name
            docstring = None
            line = ref_node.start_point[0] + 1

        symbols.append(Symbol(
            name=name,
            fqn=f"{dep.name}:{name}",
            library=dep.name,
            library_version=dep.version,
            kind=kind,
            signature=sig,
            source=sig,
            file_path=rel_path,
            line_number=line,
            docstring=docstring,
        ))

    # ------------------------------------------------------------------
    # Entry-point resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _find_js_entry(dep: Dependency) -> Path | None:
        """Find the primary .js entry point for the dependency."""
        pkg_json = dep.path / "package.json"
        if pkg_json.exists():
            try:
                meta = json.loads(pkg_json.read_text(encoding="utf-8"))
                main = meta.get("main")
                if main:
                    candidate = dep.path / main
                    if candidate.exists():
                        return candidate
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback to index.js
        fallback = dep.path / "index.js"
        if fallback.exists():
            return fallback

        return None


# ------------------------------------------------------------------
# Declaration index for CJS resolution
# ------------------------------------------------------------------

class _DeclInfo:
    __slots__ = ("kind", "signature", "docstring", "line")

    def __init__(self, kind: str, signature: str, docstring: str | None, line: int) -> None:
        self.kind = kind
        self.signature = signature
        self.docstring = docstring
        self.line = line


def _build_declaration_index(root: Node, source: bytes) -> dict[str, _DeclInfo]:
    """
    Scan top-level declarations and build a name → _DeclInfo map.

    Used so CJS ``module.exports = { greet }`` can look up the kind and
    JSDoc of the original ``function greet()`` declaration.
    """
    index: dict[str, _DeclInfo] = {}
    children = root.children
    for i, node in enumerate(children):
        kind = _KIND_MAP.get(node.type)
        if kind is None:
            continue
        name = _extract_name(node, source)
        if not name:
            continue
        docstring = _extract_preceding_comment(children, i, source)
        index[name] = _DeclInfo(
            kind=kind,
            signature=_extract_signature(node, source),
            docstring=docstring,
            line=node.start_point[0] + 1,
        )
    return index


# ------------------------------------------------------------------
# Pure utility functions
# ------------------------------------------------------------------

def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _child_of_type(node: Node, *types: str) -> Node | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _first_named_non_keyword(node: Node, skip: set[str]) -> Node | None:
    for child in node.children:
        if child.is_named and child.type not in skip:
            return child
    return None


def _extract_name(node: Node, source: bytes) -> str | None:
    """Return the identifier name of a declaration node."""
    for child in node.children:
        if child.type in ("identifier", "property_identifier"):
            return _node_text(child, source)
    # lexical_declaration: const/let/var <variable_declarator> → identifier
    declarator = _child_of_type(node, "variable_declarator")
    if declarator is not None:
        return _extract_name(declarator, source)
    return None


def _extract_signature(node: Node, source: bytes) -> str:
    """
    Return a concise signature for a declaration node.

    For functions: everything up to and including the closing ')' of the
    parameter list (the body block is omitted).
    For classes: 'class ClassName'.
    For variables: the full declaration text (capped at 120 chars).
    """
    if node.type in ("function_declaration", "function_expression", "arrow_function"):
        params = _child_of_type(node, "formal_parameters")
        if params:
            end = params.end_byte
            text = source[node.start_byte:end].decode("utf-8", errors="replace")
            return text.strip()

    if node.type == "class_declaration":
        # Return just 'class Name'
        name_node = _child_of_type(node, "identifier")
        if name_node:
            end = name_node.end_byte
            return source[node.start_byte:end].decode("utf-8", errors="replace").strip()

    full = _node_text(node, source)
    return full[:120].strip()


def _extract_preceding_comment(siblings: list[Node], idx: int, source: bytes) -> str | None:
    """Return the text of a JSDoc/line comment immediately before siblings[idx]."""
    if idx == 0:
        return None
    prev = siblings[idx - 1]
    if prev.type == "comment":
        text = _node_text(prev, source).strip()
        if text.startswith("/**"):
            text = text[3:].rstrip("*/").strip()
            lines = [ln.lstrip().lstrip("* ") for ln in text.splitlines()]
            return "\n".join(ln for ln in lines if ln).strip() or None
        if text.startswith("//"):
            return text[2:].strip() or None
    return None
