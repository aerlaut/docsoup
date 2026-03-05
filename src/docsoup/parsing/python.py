"""Python symbol extractor — parses .py and .pyi files using the stdlib ast module."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from docsoup.models import Dependency, Symbol
from docsoup.parsing.base import SymbolExtractor

logger = logging.getLogger(__name__)


class PythonExtractor(SymbolExtractor):
    """
    Extracts exported symbols from Python packages.

    Parses ``.pyi`` stub files when present (preferred, like ``.d.ts`` for TypeScript),
    otherwise falls back to ``.py`` source files.

    Respects ``__all__`` when defined: only symbols listed there are emitted.
    When ``__all__`` is absent, all public names (those not starting with ``_``) are
    emitted.

    Extracts:
    - Module-level functions (sync and async) → ``kind='function'``
    - Module-level classes + their public methods → ``kind='class'`` / ``kind='function'``
    - Module-level annotated variables and assignments → ``kind='variable'``
    """

    # ------------------------------------------------------------------
    # SymbolExtractor interface
    # ------------------------------------------------------------------

    def can_extract(self, dependency: Dependency) -> bool:
        if dependency.ecosystem != "python":
            return False
        pkg_path = dependency.path
        return (
            any(pkg_path.rglob("*.pyi"))
            or any(pkg_path.rglob("*.py"))
        )

    def extract(self, dependency: Dependency) -> list[Symbol]:
        files = self._select_files(dependency.path)
        symbols: list[Symbol] = []
        for path in files:
            self._extract_file(path, dependency, symbols)
        return symbols

    # ------------------------------------------------------------------
    # File selection
    # ------------------------------------------------------------------

    @staticmethod
    def _select_files(pkg_path: Path) -> list[Path]:
        """Return .pyi files if any exist; otherwise return .py files."""
        pyi_files = sorted(pkg_path.rglob("*.pyi"))
        if pyi_files:
            return pyi_files
        return sorted(pkg_path.rglob("*.py"))

    # ------------------------------------------------------------------
    # Per-file extraction
    # ------------------------------------------------------------------

    def _extract_file(
        self,
        path: Path,
        dep: Dependency,
        symbols: list[Symbol],
    ) -> None:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", path, exc)
            return

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            logger.warning("Syntax error in %s: %s", path, exc)
            return

        rel_path = str(path.relative_to(dep.path))
        export_set = _collect_all(tree)  # None means "no __all__"

        for node in ast.iter_child_nodes(tree):
            self._visit_top_level(node, source, dep, rel_path, export_set, symbols)

    # ------------------------------------------------------------------
    # Top-level node dispatch
    # ------------------------------------------------------------------

    def _visit_top_level(
        self,
        node: ast.AST,
        source: str,
        dep: Dependency,
        rel_path: str,
        export_set: set[str] | None,
        symbols: list[Symbol],
    ) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_exported(node.name, export_set):
                sym = self._make_function_symbol(node, source, dep, rel_path)
                if sym:
                    symbols.append(sym)

        elif isinstance(node, ast.ClassDef):
            if _is_exported(node.name, export_set):
                sym = self._make_class_symbol(node, dep, rel_path)
                if sym:
                    symbols.append(sym)
                    # Extract class members
                    self._extract_methods(node, dep, rel_path, symbols)

        elif isinstance(node, ast.AnnAssign):
            # name: Type [= value]
            name = _ann_assign_name(node)
            if name and _is_exported(name, export_set):
                sym = self._make_ann_assign_symbol(node, name, dep, rel_path)
                if sym:
                    symbols.append(sym)

        elif isinstance(node, ast.Assign):
            # name = value  (simple, one target)
            for name in _assign_names(node):
                if _is_exported(name, export_set):
                    sym = self._make_assign_symbol(node, name, dep, rel_path)
                    if sym:
                        symbols.append(sym)
                    break  # only emit once per Assign node

    # ------------------------------------------------------------------
    # Symbol factories
    # ------------------------------------------------------------------

    def _make_function_symbol(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        source: str,
        dep: Dependency,
        rel_path: str,
    ) -> Symbol | None:
        sig = _function_signature(node)
        docstring = ast.get_docstring(node)
        return Symbol(
            name=node.name,
            fqn=f"{dep.name}:{node.name}",
            library=dep.name,
            library_version=dep.version,
            kind="function",
            signature=sig,
            source=sig,
            file_path=rel_path,
            line_number=node.lineno,
            docstring=docstring,
        )

    def _make_class_symbol(
        self,
        node: ast.ClassDef,
        dep: Dependency,
        rel_path: str,
    ) -> Symbol | None:
        bases = ", ".join(ast.unparse(b) for b in node.bases) if node.bases else ""
        sig = f"class {node.name}({bases})" if bases else f"class {node.name}"
        docstring = ast.get_docstring(node)
        return Symbol(
            name=node.name,
            fqn=f"{dep.name}:{node.name}",
            library=dep.name,
            library_version=dep.version,
            kind="class",
            signature=sig,
            source=sig,
            file_path=rel_path,
            line_number=node.lineno,
            docstring=docstring,
        )

    def _extract_methods(
        self,
        class_node: ast.ClassDef,
        dep: Dependency,
        rel_path: str,
        symbols: list[Symbol],
    ) -> None:
        """Emit public methods of *class_node* as function symbols."""
        for node in ast.iter_child_nodes(class_node):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Skip __dunder__ methods except __init__
            if node.name.startswith("__") and node.name.endswith("__") and node.name != "__init__":
                continue
            # Skip private methods
            if node.name.startswith("_") and not node.name.startswith("__"):
                continue
            sig = f"{class_node.name}.{_function_signature(node)}"
            docstring = ast.get_docstring(node)
            symbols.append(Symbol(
                name=node.name,
                fqn=f"{dep.name}:{class_node.name}.{node.name}",
                library=dep.name,
                library_version=dep.version,
                kind="function",
                signature=sig,
                source=sig,
                file_path=rel_path,
                line_number=node.lineno,
                docstring=docstring,
            ))

    def _make_ann_assign_symbol(
        self,
        node: ast.AnnAssign,
        name: str,
        dep: Dependency,
        rel_path: str,
    ) -> Symbol | None:
        annotation = ast.unparse(node.annotation)
        sig = f"{name}: {annotation}"
        return Symbol(
            name=name,
            fqn=f"{dep.name}:{name}",
            library=dep.name,
            library_version=dep.version,
            kind="variable",
            signature=sig,
            source=sig,
            file_path=rel_path,
            line_number=node.lineno,
            docstring=None,
        )

    def _make_assign_symbol(
        self,
        node: ast.Assign,
        name: str,
        dep: Dependency,
        rel_path: str,
    ) -> Symbol | None:
        sig = ast.unparse(node)[:120]
        return Symbol(
            name=name,
            fqn=f"{dep.name}:{name}",
            library=dep.name,
            library_version=dep.version,
            kind="variable",
            signature=sig,
            source=sig,
            file_path=rel_path,
            line_number=node.lineno,
            docstring=None,
        )


# ------------------------------------------------------------------
# Pure utility functions
# ------------------------------------------------------------------

def _collect_all(tree: ast.Module) -> set[str] | None:
    """Return the set of names in ``__all__``, or ``None`` if ``__all__`` is not defined.

    Only the simple case is handled: ``__all__ = [...]`` or ``__all__ = (...)``.
    Dynamic constructions (e.g. ``__all__ = base.__all__ + [...]``) are ignored and
    treated as if ``__all__`` were absent.
    """
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Name) and target.id == "__all__"):
            continue
        # Value must be a list or tuple of string literals.
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return None
        names: set[str] = set()
        for elt in node.value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.add(elt.value)
        return names
    return None


def _is_exported(name: str, export_set: set[str] | None) -> bool:
    """Return True if *name* should be emitted as a symbol."""
    if export_set is not None:
        return name in export_set
    # No __all__: export public names only
    return not name.startswith("_")


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Reconstruct a human-readable function signature from an AST node."""
    args = node.args

    parts: list[str] = []

    # Positional-only args (before /)
    for i, arg in enumerate(args.posonlyargs):
        default_offset = len(args.posonlyargs) - len(args.defaults)
        default_idx = i - default_offset
        annotation = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        default = f" = {ast.unparse(args.defaults[default_idx])}" if default_idx >= 0 else ""
        parts.append(f"{arg.arg}{annotation}{default}")
    if args.posonlyargs:
        parts.append("/")

    # Regular args
    posonly_count = len(args.posonlyargs)
    for i, arg in enumerate(args.args):
        all_defaults = args.defaults
        default_start = len(args.posonlyargs) + len(args.args) - len(all_defaults)
        default_idx = posonly_count + i - default_start
        annotation = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        default = f" = {ast.unparse(all_defaults[default_idx])}" if default_idx >= 0 else ""
        parts.append(f"{arg.arg}{annotation}{default}")

    # *args
    if args.vararg:
        annotation = f": {ast.unparse(args.vararg.annotation)}" if args.vararg.annotation else ""
        parts.append(f"*{args.vararg.arg}{annotation}")
    elif args.kwonlyargs:
        parts.append("*")

    # Keyword-only args
    for i, arg in enumerate(args.kwonlyargs):
        kw_default = args.kw_defaults[i]
        annotation = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        default = f" = {ast.unparse(kw_default)}" if kw_default is not None else ""
        parts.append(f"{arg.arg}{annotation}{default}")

    # **kwargs
    if args.kwarg:
        annotation = f": {ast.unparse(args.kwarg.annotation)}" if args.kwarg.annotation else ""
        parts.append(f"**{args.kwarg.arg}{annotation}")

    params = ", ".join(parts)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({params}){ret}"


def _ann_assign_name(node: ast.AnnAssign) -> str | None:
    """Return the target name of an annotated assignment, or None for complex targets."""
    if isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _assign_names(node: ast.Assign) -> list[str]:
    """Return simple identifier names from an assignment's targets."""
    names: list[str] = []
    for target in node.targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
    return names
