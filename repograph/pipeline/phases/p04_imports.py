"""Phase 4 — Import Resolution: resolve module paths to repo files, create IMPORTS edges."""
from __future__ import annotations

import os

from repograph.core.models import CallEdge, FileRecord, ImportEdge, NodeID, ParsedFile
from repograph.core.confidence import CONF_IMPORT_EXTERNAL, CONF_IMPORT_STATIC, CONF_INLINE_IMPORT
from repograph.graph_store.store import GraphStore
from repograph.parsing.symbol_table import SymbolTable
from repograph.core.confidence import should_skip_call_edge


def run(
    parsed_files: list[ParsedFile],
    store: GraphStore,
    symbol_table: SymbolTable,
    repo_root: str,
) -> None:
    """
    For each import statement, resolve the module path to a repo file.
    Creates IMPORTS edges with confidence scores.
    Handles Python (absolute + relative) and JavaScript/TypeScript (ESM + CJS).
    """
    path_index: dict[str, ParsedFile] = {pf.file_record.path: pf for pf in parsed_files}

    # Build per-language module indices once up front
    python_module_index = _build_python_module_index(parsed_files, repo_root)
    js_path_index = _build_js_path_index(parsed_files)

    for pf in parsed_files:
        lang = pf.file_record.language
        for imp in pf.imports:
            if lang == "python":
                resolved = _resolve_python_import(
                    imp.module_path, pf.file_record.path,
                    python_module_index, repo_root,
                )
            elif lang in ("javascript", "typescript"):
                resolved = _resolve_js_import(
                    imp.module_path, pf.file_record.path,
                    js_path_index,
                )
            else:
                resolved = None

            if resolved and resolved in path_index:
                store.upsert_import(_update_resolved(imp, resolved))

                from_id = NodeID.make_file_id(pf.file_record.path)
                to_id = NodeID.make_file_id(resolved)
                edge = ImportEdge(
                    from_file_id=from_id,
                    to_file_id=to_id,
                    specific_symbols=imp.imported_names,
                    is_wildcard=imp.is_wildcard,
                    line_number=imp.line_number,
                    confidence=CONF_IMPORT_STATIC,
                )
                try:
                    store.insert_import_edge(edge)
                except Exception:
                    pass

                imp.resolved_path = resolved

    _process_inline_import_call_edges(
        parsed_files, store, symbol_table, repo_root, python_module_index
    )

    # HTML script-tag scanning — create IMPORTS edges from HTML files to the
    # JS files they load via <script src="...">.  These edges are used by
    # Phase 11 to identify JS files in script-tag (global) context.
    _process_html_script_tags(parsed_files, store, path_index)


def _process_inline_import_call_edges(
    parsed_files: list[ParsedFile],
    store: GraphStore,
    symbol_table: SymbolTable,
    repo_root: str,
    module_index: dict[str, str],
) -> None:
    """CALLS edges for ``from M import sym`` / ``import`` inside function bodies.

    Resolution strategy (in order):
    1. Direct lookup: symbol defined in the resolved module file itself.
    2. Re-export fallback: the resolved module re-exports the symbol via its own
       imports (e.g. ``store.py`` re-exports ``_delete_db_dir`` from
       ``store_utils.py``).  We follow one level of re-export by checking every
       import in the resolved file that names the symbol.
    3. Global-name fallback: look up the bare name across the whole symbol table
       (lowest confidence; only used when both above fail).

    INVARIANT: Only writes CALLS edges — never modifies ParsedFile or SymbolTable.
    NEVER creates duplicate edges; deduplication key is (caller_id, callee_id, line).
    """
    created: set[tuple[str, str, int]] = set()
    for pf in parsed_files:
        if pf.file_record.language != "python":
            continue
        for fn in pf.functions:
            for mod_path, sym_name in fn.inline_imports:
                resolved = _resolve_python_import(
                    mod_path, pf.file_record.path, module_index, repo_root
                )
                if not resolved:
                    continue

                # Strategy 1: symbol defined directly in the resolved file.
                entries = [
                    e for e in symbol_table.lookup_in_file(resolved, sym_name)
                    if e.node_type == "function"
                ]

                # Strategy 2: resolved file re-exports the symbol (one hop).
                # e.g. store.py does ``from store_utils import _delete_db_dir``
                # so the symbol lives in store_utils.py, not store.py.
                if not entries:
                    reexport_imports = [
                        imp for pf2 in parsed_files
                        for imp in pf2.imports
                        if pf2.file_record.path == resolved
                        and sym_name in imp.imported_names
                        and imp.resolved_path
                    ]
                    for reimp in reexport_imports:
                        rp = reimp.resolved_path
                        if not rp:
                            continue
                        found = [
                            e for e in symbol_table.lookup_in_file(rp, sym_name)
                            if e.node_type == "function"
                        ]
                        entries.extend(found)
                        if entries:
                            break

                if not entries:
                    continue
                callee_id = entries[0].node_id
                line = fn.line_start
                key = (fn.id, callee_id, line)
                if key in created:
                    continue
                created.add(key)
                edge = CallEdge(
                    from_function_id=fn.id,
                    to_function_id=callee_id,
                    call_site_line=line,
                    argument_names=[],
                    confidence=CONF_INLINE_IMPORT,
                    reason="inline_import",
                )
                if should_skip_call_edge(
                    edge.from_function_id,
                    edge.to_function_id,
                    edge.confidence,
                    edge.reason,
                ):
                    continue
                try:
                    store.insert_call_edge(edge)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Python resolution
# ---------------------------------------------------------------------------

def _build_python_module_index(
    parsed_files: list[ParsedFile], repo_root: str
) -> dict[str, str]:
    """
    Build dict: dotted_module_name -> relative_file_path
    e.g. "repograph.core.models" -> "repograph/core/models.py"

    Also detects Python package roots (directories like ``src/`` whose
    children contain ``__init__.py`` but which themselves are **not** a
    package).  For every file under such a root the index contains both
    the full dotted path (``src.app.event_bus``) **and** the root-stripped
    variant (``app.event_bus``).  This mirrors how ``sys.path`` typically
    points at the root directory so ``from app.event_bus import X`` works
    at runtime.
    """
    # Collect all Python file paths first
    py_paths: list[str] = []
    for pf in parsed_files:
        path = pf.file_record.path
        if path.endswith(".py"):
            py_paths.append(path)

    # Detect package roots — directories that act as implicit sys.path
    # entries (e.g. ``src/``).  A package root is a directory that contains
    # child directories with ``__init__.py`` but does NOT itself contain an
    # ``__init__.py`` at its own level (i.e. it is not itself a package).
    package_roots = _detect_package_roots(py_paths)

    index: dict[str, str] = {}
    for path in py_paths:
        without_ext = path[:-3]
        if without_ext.endswith("/__init__"):
            without_ext = without_ext[: -len("/__init__")]
        dotted = without_ext.replace("/", ".")

        # Always register the full dotted path
        index[dotted] = path

        # Register root-stripped variant(s) so ``from app.X import Y``
        # resolves when the file lives under ``src/app/X.py``.
        for root in package_roots:
            prefix = root.replace("/", ".") + "."
            if dotted.startswith(prefix):
                stripped = dotted[len(prefix):]
                if stripped and stripped not in index:
                    index[stripped] = path

        # Bare module name (last segment) as lowest-priority fallback
        last = dotted.split(".")[-1]
        if last not in index:
            index[last] = path

    return index


def _detect_package_roots(py_paths: list[str]) -> list[str]:
    """Find directories that serve as Python package roots (sys.path entries).

    A package root is a top-level directory that contains multiple child
    packages (directories with ``__init__.py``).  Common examples:
    ``src/``, ``lib/``, ``source/``.

    Unlike a naïve check that excludes directories with their own
    ``__init__.py``, this handles the common pattern where ``src/`` has
    an ``__init__.py`` but is still added to ``sys.path`` so that
    ``from app.event_bus import X`` works (rather than requiring
    ``from src.app.event_bus import X``).

    The heuristic: a first-level directory that has **2 or more** child
    directories containing ``__init__.py`` is likely a source root, not
    a regular package consumed by import.

    Returns a sorted list of root directory strings (e.g. ``["src"]``).
    """
    # Collect all directories that contain an __init__.py
    init_dirs: set[str] = set()
    for path in py_paths:
        if path.endswith("__init__.py"):
            d = path.rsplit("/", 1)[0] if "/" in path else ""
            if d:
                init_dirs.add(d)

    # Count how many child-package dirs each top-level directory has.
    # "top-level" = first path segment (depth 1 from repo root).
    from collections import Counter
    toplevel_child_counts: Counter[str] = Counter()
    for d in init_dirs:
        parts = d.split("/")
        if len(parts) >= 2:
            # e.g. "src/app" -> top="src", child="app"
            toplevel_child_counts[parts[0]] += 1

    # A directory is a package root if it has ≥2 child packages.
    # This distinguishes a source-root like ``src/`` (which typically
    # contains app/, advisor/, utils/, etc.) from a regular package
    # that happens to sit at the top level.
    roots: set[str] = set()
    for top_dir, child_count in toplevel_child_counts.items():
        if child_count >= 2:
            roots.add(top_dir)

    return sorted(roots)


def _resolve_python_import(
    module_path: str,
    importing_file: str,
    module_to_path: dict[str, str],
    repo_root: str,
) -> str | None:
    if not module_path:
        return None
    if module_path.startswith("."):
        return _resolve_relative_import(module_path, importing_file)
    if module_path in module_to_path:
        return module_to_path[module_path]
    parts = module_path.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in module_to_path:
            return module_to_path[candidate]
    return None


def _resolve_relative_import(module_path: str, importing_file: str) -> str | None:
    level = 0
    while level < len(module_path) and module_path[level] == ".":
        level += 1
    relative_module = module_path[level:]
    parts = importing_file.split("/")
    base_parts = parts[:-1]
    go_up = level - 1
    if go_up > len(base_parts):
        return None
    base_parts = base_parts[: len(base_parts) - go_up]
    if relative_module:
        module_parts = relative_module.replace(".", "/")
        return "/".join(base_parts) + "/" + module_parts + ".py"
    return "/".join(base_parts) + "/__init__.py"


# ---------------------------------------------------------------------------
# JavaScript / TypeScript resolution
# ---------------------------------------------------------------------------

def _build_js_path_index(parsed_files: list[ParsedFile]) -> dict[str, str]:
    """
    Build a dict: normalised_path_without_ext -> relative_file_path
    Covers .js, .jsx, .ts, .tsx, and their index.* variants.
    """
    index: dict[str, str] = {}
    js_exts = {".js", ".jsx", ".ts", ".tsx"}
    for pf in parsed_files:
        path = pf.file_record.path
        ext = pf.file_record.extension
        if ext not in js_exts:
            continue
        # Strip extension for extension-less import matching
        without_ext = path[: -len(ext)]
        # e.g. "src/utils/helpers.js" -> "src/utils/helpers"
        index[without_ext] = path
        # If this is an index file: "src/utils/index.js" -> "src/utils"
        if without_ext.endswith("/index"):
            folder = without_ext[: -len("/index")]
            if folder not in index:
                index[folder] = path
    return index


def _resolve_js_import(
    module_path: str,
    importing_file: str,
    js_path_index: dict[str, str],
) -> str | None:
    """
    Resolve a JavaScript/TypeScript import specifier to a repo file path.

    Handles:
    - Relative: './foo', '../bar/baz', './Button.jsx'
    - Non-relative (external packages like 'react', 'lodash') -> None
    - @/ and ~/ path aliases are not resolved (would need tsconfig/webpack config)
    """
    if not module_path:
        return None

    # External package (no leading . or /) — cannot resolve to a repo file
    if not module_path.startswith(".") and not module_path.startswith("/"):
        return None

    # Compute the directory of the importing file
    importer_dir = "/".join(importing_file.split("/")[:-1])

    # Join importer directory with the relative specifier
    if module_path.startswith("/"):
        # Absolute-looking path — treat as relative to repo root
        candidate_base = module_path.lstrip("/")
    else:
        # Standard relative: ./foo or ../bar
        raw = importer_dir + "/" + module_path if importer_dir else module_path
        candidate_base = _normalise_path(raw)

    # The specifier may or may not have an extension.
    # Try with extension first (exact match in index), then without.
    js_exts = (".js", ".jsx", ".ts", ".tsx")

    # 1. Specifier already has a known extension
    for ext in js_exts:
        if candidate_base.endswith(ext):
            without_ext = candidate_base[: -len(ext)]
            if without_ext in js_path_index:
                return js_path_index[without_ext]
            # Also try as-is with the extension kept
            # (rare: the index is keyed without extension)
            break

    # 2. Extension-less specifier — try appending each extension
    if candidate_base in js_path_index:
        return js_path_index[candidate_base]

    # 3. Try as directory/index (import './utils' -> utils/index.ts etc.)
    index_candidate = candidate_base + "/index" if not candidate_base.endswith("/") else candidate_base + "index"
    # The js_path_index already maps "dir/index" -> file AND "dir" -> index file
    if index_candidate in js_path_index:
        return js_path_index[index_candidate]

    return None


def _normalise_path(path: str) -> str:
    """Resolve '.' and '..' components in a path string without touching the filesystem."""
    parts = path.split("/")
    resolved: list[str] = []
    for part in parts:
        if part == "..":
            if resolved:
                resolved.pop()
        elif part and part != ".":
            resolved.append(part)
    return "/".join(resolved)


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _update_resolved(imp, resolved_path: str):
    from repograph.core.models import ImportNode
    return ImportNode(
        id=imp.id,
        file_path=imp.file_path,
        raw_statement=imp.raw_statement,
        module_path=imp.module_path,
        resolved_path=resolved_path,
        imported_names=imp.imported_names,
        is_wildcard=imp.is_wildcard,
        line_number=imp.line_number,
    )


# ---------------------------------------------------------------------------
# HTML script-tag import edges
# ---------------------------------------------------------------------------

def _process_html_script_tags(
    parsed_files: list[ParsedFile],
    store: GraphStore,
    path_index: dict[str, "ParsedFile"],
) -> None:
    """Create IMPORTS edges from HTML files to JS files loaded via <script src>.

    Reads each HTML file from disk (the parsed file only has import records
    for ES-module imports, not script-tag includes), scans for
    ``<script src="...">`` tags, and inserts a synthetic IMPORTS edge for
    each local JS path found.

    Path resolution notes
    ----------------------
    Script ``src`` values are often server-relative URL paths that don't
    directly match repo file paths.  For example a Flask app may serve
    ``/static/js/utils.js`` from ``src/ui/static/js/utils.js``.  When the
    scanner-returned path doesn't appear in the file index verbatim we try a
    *suffix match*: find any indexed file whose path ends with the scanned
    path (or its normalised form without a leading ``/``).  The first and only
    match is used; if multiple files share the same suffix the path is
    ambiguous and we skip it to avoid false edges.
    """
    from repograph.parsing.html_scanner import scan_script_tags

    # Build a reverse suffix index once: suffix -> [full_path, ...]
    # Used for fuzzy resolution of server-relative URL paths.
    suffix_index: dict[str, list[str]] = {}
    for full_path in path_index:
        # Register every possible trailing suffix segment
        # e.g. "src/ui/static/js/utils.js" registers:
        #   "utils.js", "js/utils.js", "static/js/utils.js", ...
        parts = full_path.replace("\\", "/").split("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            suffix_index.setdefault(suffix, []).append(full_path)

    for pf in parsed_files:
        if pf.file_record.language != "html":
            continue

        try:
            with open(pf.file_record.abs_path, "rb") as fh:
                html_bytes = fh.read()
        except (OSError, PermissionError):
            continue

        js_paths = scan_script_tags(html_bytes, pf.file_record.path)
        from_id = NodeID.make_file_id(pf.file_record.path)

        for js_path in js_paths:
            # Direct match (happy path — no URL prefix remapping needed)
            if js_path in path_index:
                resolved_path = js_path
            else:
                # Suffix-fallback: strip leading path segments until we find
                # a unique match in the index.  This handles server-relative
                # paths like "/static/js/utils.js" that map to a repo path
                # with a deeper prefix like "src/ui/static/js/utils.js".
                normalised = js_path.lstrip("/")
                candidates = suffix_index.get(normalised, [])
                if len(candidates) != 1:
                    continue  # ambiguous or not found — skip safely
                resolved_path = candidates[0]

            to_id = NodeID.make_file_id(resolved_path)
            edge = ImportEdge(
                from_file_id=from_id,
                to_file_id=to_id,
                specific_symbols=[],
                is_wildcard=False,
                line_number=0,
                confidence=CONF_IMPORT_STATIC,
            )
            try:
                store.insert_import_edge(edge)
            except Exception:
                pass
