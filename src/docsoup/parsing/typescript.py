"""TypeScript symbol extractor — parses .d.ts files using Tree-sitter."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import tree_sitter_typescript as ts_ts
from tree_sitter import Language, Node, Parser

from docsoup.models import Dependency, Symbol
from docsoup.parsing.base import SymbolExtractor

logger = logging.getLogger(__name__)

# Lazily initialised module-level parser (tree-sitter parsers are not thread-safe
# but are fine for sequential use).
_parser: Parser | None = None


def _get_parser() -> Parser:
    global _parser
    if _parser is None:
        lang = Language(ts_ts.language_typescript())
        _parser = Parser(lang)
    return _parser


# Map from tree-sitter node types to our Symbol.kind values.
_KIND_MAP: dict[str, str] = {
    "function_signature": "function",
    "function_declaration": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    "lexical_declaration": "variable",
    "variable_declaration": "variable",
}

_METHOD_KINDS = {"method_signature", "method_definition", "public_field_definition"}


class TypeScriptExtractor(SymbolExtractor):
    """
    Extracts exported symbols from TypeScript ``.d.ts`` declaration files.

    Handles: functions, classes (+ their methods), interfaces, type aliases,
    enums, exported constants/variables, ambient module blocks, and barrel
    re-exports (``export { X } from './file'``, ``export * from './file'``).

    Entry-point resolution order (mirrors TypeScript compiler):
    1. ``types`` field in package.json
    2. ``typings`` field in package.json
    3. ``exports["."]["types"]`` conditional export in package.json
    4. ``index.d.ts`` in the package root
    """

    # ------------------------------------------------------------------
    # SymbolExtractor interface
    # ------------------------------------------------------------------

    def can_extract(self, dependency: Dependency) -> bool:
        return dependency.ecosystem == "node" and self._find_dts_entry(dependency) is not None

    def extract(self, dependency: Dependency) -> list[Symbol]:
        entry = self._find_dts_entry(dependency)
        if entry is None:
            return []

        symbols: list[Symbol] = []
        # Walk the entry file and any referenced declaration files (barrel exports).
        visited: set[Path] = set()
        self._extract_file(entry, dependency, symbols, visited)
        return symbols

    # ------------------------------------------------------------------
    # File walking
    # ------------------------------------------------------------------

    def _extract_file(
        self,
        path: Path,
        dep: Dependency,
        symbols: list[Symbol],
        visited: set[Path],
    ) -> None:
        path = path.resolve()
        if path in visited:
            return
        visited.add(path)

        if not path.exists():
            return

        try:
            source = path.read_bytes()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", path, exc)
            return

        parser = _get_parser()
        tree = parser.parse(source)
        rel_path = str(path.relative_to(dep.path))

        self._walk_program(
            tree.root_node, source, dep, rel_path, symbols,
            current_file=path, visited=visited,
        )

    def _walk_program(
        self,
        root: Node,
        source: bytes,
        dep: Dependency,
        rel_path: str,
        symbols: list[Symbol],
        *,
        current_file: Path | None = None,
        visited: set[Path] | None = None,
    ) -> None:
        """Iterate top-level nodes of a parsed program.

        Two-pass approach:
        1. Build a declaration index from non-exported top-level declarations
           (e.g. bare ``interface Foo``, ``declare class Bar``).
        2. Process export statements, using the index to resolve ``export { A, B }``
           local re-exports and following ``from './file'`` paths into other files.
        """
        if visited is None:
            visited = set()

        children = root.children

        # Pass 1: collect non-exported top-level declarations for later lookup.
        decl_index = _build_decl_index(children, source)

        # Pass 2: process export statements and ambient module wrappers.
        for i, node in enumerate(children):
            preceding_comment = _extract_preceding_comment(children, i, source)

            if node.type == "export_statement":
                self._handle_export(
                    node, source, dep, rel_path, symbols, preceding_comment,
                    decl_index=decl_index, current_file=current_file, visited=visited,
                )
            elif node.type == "module":
                # bare module "..." { ... } — recurse into body
                body = _child_of_type(node, "statement_block")
                if body:
                    self._walk_program(
                        body, source, dep, rel_path, symbols,
                        current_file=current_file, visited=visited,
                    )
            elif node.type == "ambient_declaration":
                # `declare module '...' { ... }` — unwrap and recurse into body
                inner_module = _child_of_type(node, "module")
                if inner_module:
                    body = _child_of_type(inner_module, "statement_block")
                    if body:
                        self._walk_program(
                            body, source, dep, rel_path, symbols,
                            current_file=current_file, visited=visited,
                        )

    # ------------------------------------------------------------------
    # Export handling
    # ------------------------------------------------------------------

    def _handle_export(
        self,
        export_node: Node,
        source: bytes,
        dep: Dependency,
        rel_path: str,
        symbols: list[Symbol],
        docstring: str | None,
        *,
        decl_index: dict[str, "_DeclInfo"] | None = None,
        current_file: Path | None = None,
        visited: set[Path] | None = None,
    ) -> None:
        if visited is None:
            visited = set()

        # ------------------------------------------------------------------
        # Re-export from another file:
        #   export { A, B } from './foo'
        #   export * from './foo'
        #   export type { T } from './foo'
        # ------------------------------------------------------------------
        from_string_node = _child_of_type(export_node, "string")
        if from_string_node is not None:
            if current_file is not None:
                raw = _node_text(from_string_node, source).strip("'\"")
                self._follow_reexport(raw, current_file, dep, symbols, visited)
            return

        # ------------------------------------------------------------------
        # Local re-export via export clause:
        #   export { A, B }   (no 'from')
        # ------------------------------------------------------------------
        export_clause = _child_of_type(export_node, "export_clause")
        if export_clause is not None:
            if decl_index is not None:
                self._emit_from_export_clause(
                    export_clause, source, dep, rel_path, symbols, decl_index
                )
            return

        # ------------------------------------------------------------------
        # Direct export of a declaration:
        #   export function foo() ...
        #   export interface Bar { ... }
        #   export declare class Baz { ... }
        # ------------------------------------------------------------------
        # Unwrap `declare` wrapper if present.
        inner = _child_of_type(export_node, "ambient_declaration")
        if inner:
            decl = _first_named_non_keyword(inner, skip={"declare"})
        else:
            decl = _first_named_non_keyword(export_node, skip={"export", "default", "declare"})

        if decl is None:
            return

        kind = _KIND_MAP.get(decl.type)
        if kind is None:
            logger.debug("Unhandled declaration type %r — skipping", decl.type)
            return

        name = _extract_name(decl, source)
        if not name:
            return

        sig = _node_text(export_node, source)
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

        # For classes and interfaces, also extract their members.
        if kind in ("class", "interface"):
            body = _child_of_type(decl, "class_body") or _child_of_type(decl, "interface_body")
            if body:
                self._extract_members(body, source, dep, rel_path, symbols, parent_name=name)

    def _follow_reexport(
        self,
        raw_path: str,
        current_file: Path,
        dep: Dependency,
        symbols: list[Symbol],
        visited: set[Path],
    ) -> None:
        """Resolve *raw_path* relative to *current_file* and recurse into it.

        Tries (in order):
        1. The path as-is (if it is an existing ``.d.ts`` file)
        2. The path with a ``.d.ts`` extension appended
        3. The path treated as a directory: ``<path>/index.d.ts``
        """
        base = current_file.parent / raw_path
        candidates = [
            base,
            base.with_suffix(".d.ts"),
            base / "index.d.ts",
        ]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file() and resolved not in visited:
                self._extract_file(resolved, dep, symbols, visited)
                return

    def _emit_from_export_clause(
        self,
        export_clause: Node,
        source: bytes,
        dep: Dependency,
        rel_path: str,
        symbols: list[Symbol],
        decl_index: dict[str, "_DeclInfo"],
    ) -> None:
        """Emit symbols for each specifier in an ``export { A, B }`` clause."""
        for spec in export_clause.children:
            if spec.type != "export_specifier":
                continue
            # The local (original) name is the first identifier in the specifier.
            ident = _child_of_type(spec, "identifier")
            if ident is None:
                continue
            name = _node_text(ident, source)
            info = decl_index.get(name)
            if info is None:
                continue
            symbols.append(Symbol(
                name=name,
                fqn=f"{dep.name}:{name}",
                library=dep.name,
                library_version=dep.version,
                kind=info.kind,
                signature=info.signature,
                source=info.signature,
                file_path=rel_path,
                line_number=info.line,
                docstring=info.docstring,
            ))

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
            if node.type not in _METHOD_KINDS and node.type not in (
                "method_signature", "property_signature", "call_signature",
                "construct_signature", "index_signature",
            ):
                continue

            member_name = _extract_name(node, source)
            if not member_name:
                continue

            preceding_comment = _extract_preceding_comment(children, i, source)
            sig = _node_text(node, source)
            fqn = f"{dep.name}:{parent_name}.{member_name}"

            symbols.append(Symbol(
                name=member_name,
                fqn=fqn,
                library=dep.name,
                library_version=dep.version,
                kind="function" if node.type in ("method_signature", "method_definition") else "variable",
                signature=f"{parent_name}.{sig}",
                source=f"{parent_name}.{sig}",
                file_path=rel_path,
                line_number=node.start_point[0] + 1,
                docstring=preceding_comment,
            ))

    # ------------------------------------------------------------------
    # Entry-point resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _find_dts_entry(dep: Dependency) -> Path | None:
        """Find the primary .d.ts entry point for the dependency.

        Resolution order:
        1. ``types`` field in package.json
        2. ``typings`` field in package.json
        3. ``exports["."]["types"]`` conditional export in package.json
        4. ``index.d.ts`` in the package root
        """
        pkg_json = dep.path / "package.json"
        if pkg_json.exists():
            try:
                meta = json.loads(pkg_json.read_text(encoding="utf-8"))

                # 1 & 2: top-level types / typings fields
                for field in ("types", "typings"):
                    if field in meta and meta[field]:
                        candidate = dep.path / meta[field]
                        if candidate.exists():
                            return candidate

                # 3: exports map — exports["."]["types"]
                exports = meta.get("exports")
                if isinstance(exports, dict):
                    dot_export = exports.get(".")
                    if isinstance(dot_export, dict):
                        types_path = dot_export.get("types")
                        if types_path:
                            candidate = dep.path / types_path
                            if candidate.exists():
                                return candidate

            except (json.JSONDecodeError, OSError):
                pass

        # 4: fall back to index.d.ts
        fallback = dep.path / "index.d.ts"
        if fallback.exists():
            return fallback

        return None


# ------------------------------------------------------------------
# Declaration index (for local export-clause resolution)
# ------------------------------------------------------------------

class _DeclInfo:
    """Metadata for a non-exported top-level declaration."""

    __slots__ = ("kind", "signature", "docstring", "line")

    def __init__(self, kind: str, signature: str, docstring: str | None, line: int) -> None:
        self.kind = kind
        self.signature = signature
        self.docstring = docstring
        self.line = line


def _build_decl_index(children: list[Node], source: bytes) -> dict[str, _DeclInfo]:
    """
    Scan *children* (top-level AST nodes) and build a ``name → _DeclInfo`` map
    for every non-exported named declaration.

    Covers: ``interface``, ``type``, ``declare class``, ``declare function``,
    ``declare enum``, ``declare const/let/var``.
    """
    index: dict[str, _DeclInfo] = {}
    for i, node in enumerate(children):
        kind: str | None = None
        name: str | None = None
        sig: str | None = None

        if node.type in _KIND_MAP:
            # Direct declaration node (interface_declaration, type_alias_declaration, etc.)
            kind = _KIND_MAP[node.type]
            name = _extract_name(node, source)
            sig = _node_text(node, source)
        elif node.type == "ambient_declaration":
            # `declare class Foo`, `declare function foo`, `declare const x`, ...
            inner = _first_named_non_keyword(node, skip={"declare"})
            if inner is not None:
                kind = _KIND_MAP.get(inner.type)
                name = _extract_name(inner, source)
                sig = _node_text(node, source)

        if name and kind:
            docstring = _extract_preceding_comment(children, i, source)
            index[name] = _DeclInfo(
                kind=kind,
                signature=sig[:300] if sig else name,
                docstring=docstring,
                line=node.start_point[0] + 1,
            )

    return index


# ------------------------------------------------------------------
# Pure utility functions (no shared state)
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
    """Return the identifier/type name of a declaration node."""
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "property_identifier"):
            return _node_text(child, source)
    # lexical_declaration: const/let/var <variable_declarator> → identifier
    declarator = _child_of_type(node, "variable_declarator")
    if declarator is not None:
        return _extract_name(declarator, source)
    return None


def _extract_preceding_comment(siblings: list[Node], idx: int, source: bytes) -> str | None:
    """Return the text of a JSDoc/line comment immediately before *siblings[idx]*."""
    if idx == 0:
        return None
    prev = siblings[idx - 1]
    if prev.type == "comment":
        text = _node_text(prev, source).strip()
        # Clean up /** ... */ and // comments
        if text.startswith("/**"):
            text = text[3:].rstrip("*/").strip()
            # Strip leading * from each line
            lines = [ln.lstrip().lstrip("* ") for ln in text.splitlines()]
            return "\n".join(ln for ln in lines if ln).strip() or None
        if text.startswith("//"):
            return text[2:].strip() or None
    return None
