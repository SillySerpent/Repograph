"""Phase 5 — Call Resolution: resolve call sites to function IDs, create CALLS edges.

Walks each parsed file’s ``CallSite`` list, resolves ``callee_text`` (the raw callee
expression at the AST) to a graph function id via the symbol table, and persists
``CALLS`` edges with confidence and deduplication.
"""
from __future__ import annotations

from repograph.core.models import ParsedFile, CallEdge, NodeID
from repograph.core.confidence import (
    CONF_DIRECT_CALL, CONF_IMPORT_RESOLVED, CONF_METHOD_CALL, CONF_FUZZY_MATCH,
)
from repograph.graph_store.store import GraphStore
from repograph.parsing.symbol_table import SymbolTable, SymbolEntry
from repograph.core.confidence import should_skip_call_edge


_MAX_FUZZY_MATCHES = 5  # ranked by source tier, so more candidates is fine

# ``dict`` / ``Mapping`` methods often collide with unrelated class methods
# (e.g. ``FlagStore.get``) when the resolver only sees the method name ``get``.
_AMBIGUOUS_MAPPING_METHODS = frozenset({
    "get", "setdefault", "pop", "keys", "values", "items", "update",
})


def run(
    parsed_files: list[ParsedFile],
    store: GraphStore,
    symbol_table: SymbolTable,
) -> None:
    """
    For each CallSite in every ParsedFile, attempt resolution in this order:
    1. Same-file scope (qualified or single candidate method)
    2. Typed-local ``obj.method`` when ``obj = SomeClass(...)`` is known (**before**
       import lookup on the method name — avoids collisions with same-named imports)
    3. Import-resolved (from symbol_table import lookup)
    4. Script-tag shared global scope (JS files co-loaded via HTML <script> tags)
    5. Fuzzy global match (low confidence)
    Creates CALLS edges with appropriate confidence and reason.
    """
    # Build import lookup: file_path -> list[ImportNode]
    file_imports: dict[str, list] = {}
    for pf in parsed_files:
        file_imports[pf.file_record.path] = pf.imports

    # Build typed-local index: (file_path, var_name) -> class_name
    typed_locals = _build_typed_local_index(parsed_files)

    # Build script-tag shared global scope for JS files.
    # JS files loaded via HTML <script> tags share the browser's global scope,
    # so any module-scope function defined in any of them is callable from
    # any co-loaded file — even though there is no explicit import statement.
    # We pre-compute a set of these files and a reverse lookup so the call
    # resolver can check the shared scope before falling back to fuzzy global.
    script_global_files = _get_html_script_tag_js_files(store)
    # name -> list[SymbolEntry] across all script-global files
    script_global_scope: dict[str, list] = {}
    if script_global_files:
        for fp in script_global_files:
            for entry in symbol_table.all_functions_in_file(fp):
                script_global_scope.setdefault(entry.name, []).append(entry)

    created_edges: set[tuple[str, str, int]] = set()  # dedup
    edges_to_insert: list[CallEdge] = []

    for pf in parsed_files:
        imports = file_imports.get(pf.file_record.path, [])

        for site in pf.call_sites:
            callee_id, confidence, reason = _resolve_call(
                site.callee_text,
                site.file_path,
                symbol_table,
                imports,
                typed_locals,
                script_global_scope=script_global_scope,
                caller_is_script_global=site.file_path in script_global_files,
            )
            if callee_id is None:
                continue

            # Deduplicate: same caller→callee at same line
            key = (site.caller_function_id, callee_id, site.call_site_line)
            if key in created_edges:
                continue
            created_edges.add(key)

            # Extract argument names (identifiers only, not complex expressions)
            arg_names = [
                expr for expr in site.argument_exprs
                if _is_simple_identifier(expr)
            ]
            arg_names += list(site.keyword_args.keys())

            edge = CallEdge(
                from_function_id=site.caller_function_id,
                to_function_id=callee_id,
                call_site_line=site.call_site_line,
                argument_names=arg_names,
                confidence=confidence,
                reason=reason,
            )
            if should_skip_call_edge(
                edge.from_function_id,
                edge.to_function_id,
                edge.confidence,
                edge.reason,
            ):
                continue
            edges_to_insert.append(edge)

    pairs = list({(e.from_function_id, e.to_function_id) for e in edges_to_insert})
    store.prefetch_call_edges_for_pairs(pairs)
    try:
        for edge in edges_to_insert:
            try:
                store.insert_call_edge(edge)
            except Exception:
                pass  # missing node — skip
    finally:
        store.clear_call_edge_prefetch()


def _build_typed_local_index(
    parsed_files: list[ParsedFile],
) -> dict[tuple[str, str], str]:
    """Build a mapping of (file_path, variable_name) -> inferred_class_name.

    Only covers simple constructor assignments of the form::

        some_var = SomeClass(...)

    where the RHS is a direct call to a bare identifier (i.e. a class name).
    This lets Phase 5 resolve ``some_var.method()`` to ``SomeClass.method``
    without relying on fuzzy global matching.

    Deliberately conservative:
    - Only single-level attribute access is resolved (``obj.method``, not
      ``obj.sub.method``).
    - Assignments inside function bodies only (not bare class-level assignments
      where ``self`` is the typical receiver).
    - Skips assignments where the inferred type is ambiguous (e.g. a lowercase
      name that could be a function call rather than a class constructor).
    """
    index: dict[tuple[str, str], str] = {}
    for pf in parsed_files:
        fp = pf.file_record.path
        for var in pf.variables:
            if var.is_return:
                continue
            itype = var.inferred_type
            if not itype:
                continue
            # Only accept PascalCase / UpperCamelCase names as class constructors.
            # Lowercase names are more likely to be factory functions whose return
            # type we don't know statically.
            if itype[0].isupper() and itype.isidentifier():
                # Includes type-annotated parameters (e.g. ``fs: FlagStore``) so
                # ``fs.get`` resolves via typed_local instead of being skipped as
                # an ambiguous mapping ``.get``.
                index[(fp, var.name)] = itype
    return index


def _ambiguous_mapping_method_skip(
    file_path: str,
    obj_name: str,
    method_name: str,
    typed_locals: dict[tuple[str, str], str] | None,
) -> bool:
    """True → skip single-candidate / fuzzy method resolution (dict-like calls)."""
    if method_name not in _AMBIGUOUS_MAPPING_METHODS:
        return False
    if obj_name in ("self", "cls"):
        return False
    if typed_locals and (file_path, obj_name) in typed_locals:
        return False
    return True


def _get_html_script_tag_js_files(store: GraphStore) -> set[str]:
    """Return JS file paths loaded via HTML <script src> tags (Phase 5 scope resolution).

    These files share the browser global scope — any module-scope function
    defined in them is callable from any co-loaded file without an import.
    The IMPORTS edges from HTML→JS are written by Phase 4.

    NOTE: canonical definition — distinct from dead_code/plugin.py's
    _get_script_global_files which queries the is_script_global flag.
    """
    try:
        rows = store.query(
            """
            MATCH (h:File)-[:IMPORTS]->(js:File)
            WHERE h.language = 'html' AND js.language = 'javascript'
            RETURN DISTINCT js.path
            """
        )
        return {r[0] for r in rows if r[0]}
    except Exception:
        return set()


def _resolve_call(
    callee_text: str,
    file_path: str,
    symbol_table: SymbolTable,
    imports: list,
    typed_locals: dict[tuple[str, str], str] | None = None,
    script_global_scope: dict[str, list] | None = None,
    caller_is_script_global: bool = False,
) -> tuple[str | None, float, str]:
    """Return (function_id, confidence, reason) or (None, 0, ''). """

    # Handle attribute access: "obj.method" or "module.func"
    if "." in callee_text:
        parts = callee_text.split(".")
        # Try as qualified name in same file first
        entries = symbol_table.lookup_in_file(file_path, callee_text)
        if entries:
            return entries[0].node_id, CONF_DIRECT_CALL, "direct_call"

        method_name = parts[-1]
        obj_name = parts[0] if len(parts) >= 2 else ""

        # Typed-local ``obj.method`` **before** same-file single-candidate shortcut.
        if typed_locals and len(parts) == 2:
            tl = _resolve_typed_local_call(
                file_path, obj_name, method_name, symbol_table, typed_locals
            )
            if tl is not None:
                return tl

        if len(parts) == 2 and obj_name in ("self", "cls"):
            entries = symbol_table.lookup_in_file(file_path, method_name)
            if entries and len(entries) == 1:
                return entries[0].node_id, CONF_METHOD_CALL, "method_call"

        if not _ambiguous_mapping_method_skip(
            file_path, obj_name, method_name, typed_locals
        ):
            entries = symbol_table.lookup_in_file(file_path, method_name)
            if entries and len(entries) == 1:
                return entries[0].node_id, CONF_METHOD_CALL, "method_call"

        import_entries = symbol_table.lookup_imported_symbol(
            file_path, imports, method_name
        )
        if import_entries:
            return import_entries[0].node_id, CONF_IMPORT_RESOLVED, "import_resolved"

        if not _ambiguous_mapping_method_skip(
            file_path, obj_name, method_name, typed_locals
        ):
            global_entries = symbol_table.lookup_global(method_name)
            if 0 < len(global_entries) <= _MAX_FUZZY_MATCHES:
                best = _rank_entries(global_entries, file_path)
                return best.node_id, CONF_METHOD_CALL, "method_call"

        return None, 0.0, ""

    # Simple name
    file_entries = symbol_table.lookup_in_file(file_path, callee_text)
    import_entries = symbol_table.lookup_imported_symbol(
        file_path, imports, callee_text
    )
    # Bare ``foo()`` when the only same-file ``foo`` symbols are class methods
    # (qualified as ``Cls.foo``) should bind to a same-name import if present —
    # otherwise ``from m import foo`` is wrongly ignored in favour of ``Cls.foo``.
    if import_entries and file_entries:
        only_non_local_simple = all(
            e.qualified_name != callee_text for e in file_entries
        )
        if only_non_local_simple:
            return import_entries[0].node_id, CONF_IMPORT_RESOLVED, "import_resolved"

    if file_entries:
        return file_entries[0].node_id, CONF_DIRECT_CALL, "direct_call"

    if import_entries:
        return import_entries[0].node_id, CONF_IMPORT_RESOLVED, "import_resolved"

    # 4. Script-tag shared global scope — JS files co-loaded via HTML.
    # Only applies when the caller is also a script-tag JS file (or when
    # the caller's file is in the shared scope).  This resolves calls like
    # apiFetch() in dashboard.js when apiFetch is defined in utils.js and
    # both are loaded via <script> tags from index.html.
    if (caller_is_script_global or file_path in (script_global_scope or {}))             and script_global_scope:
        sg_entries = script_global_scope.get(callee_text, [])
        if sg_entries:
            best = _rank_entries(sg_entries, file_path)
            return best.node_id, CONF_FUZZY_MATCH, "script_global"

    # 5. Fuzzy global — ranked by source credibility
    global_entries = symbol_table.lookup_global(callee_text)
    if 0 < len(global_entries) <= _MAX_FUZZY_MATCHES:
        best = _rank_entries(global_entries, file_path)
        return best.node_id, CONF_FUZZY_MATCH, "fuzzy"

    return None, 0.0, ""


def _resolve_typed_local_call(
    file_path: str,
    obj_name: str,
    method_name: str,
    symbol_table: SymbolTable,
    typed_locals: dict[tuple[str, str], str],
) -> tuple[str, float, str] | None:
    """Resolve ``obj_name.method_name`` when ``obj_name`` maps to a class constructor."""
    class_name = typed_locals.get((file_path, obj_name))
    if not class_name:
        return None
    qualified = f"{class_name}.{method_name}"
    global_entries = symbol_table.lookup_global(qualified)
    if len(global_entries) == 1:
        return global_entries[0].node_id, CONF_METHOD_CALL, "typed_local"
    global_entries = symbol_table.lookup_global(method_name)
    class_entries = [
        e for e in global_entries
        if class_name + "." in e.node_id or
           e.node_id.endswith(f":{class_name}.{method_name}")
    ]
    if len(class_entries) == 1:
        return class_entries[0].node_id, CONF_METHOD_CALL, "typed_local"
    return None


# Priority tiers for fuzzy match ranking.
# Lower number = higher priority = preferred candidate.
_FUZZY_TIER: list[tuple[int, str]] = [
    # Same directory as caller — strongest signal
    (0, "same_dir"),
    # Application source tree
    (1, "src/"),
    (1, "lib/"),
    (1, "app/"),
    # Documentation / utility scripts that shouldn't be confused with production code
    (3, "scripts/"),
    (3, "script/"),
    # Test code — rarely the intended callee
    (4, "tests/"),
    (4, "test/"),
]


def _fuzzy_tier(entry_path: str, caller_path: str) -> int:
    """Return a sort-priority for a fuzzy-match candidate.

    Lower is better.  Candidates in the same directory as the caller are
    preferred, followed by production source directories, with scripts and
    tests ranked last.  This prevents e.g. a standalone training script that
    happens to define a method with the same name as a production class from
    being chosen over the real implementation.
    """
    caller_dir = "/".join(caller_path.split("/")[:-1])
    if entry_path.startswith(caller_dir + "/"):
        return 0  # same directory

    norm = entry_path.replace("\\", "/")
    for tier, prefix in _FUZZY_TIER[1:]:  # skip same_dir
        if norm.startswith(prefix) or f"/{prefix.rstrip('/')}" in norm:
            return tier

    return 2  # unknown — middle priority


def _rank_entries(entries: list[SymbolEntry], caller_path: str) -> SymbolEntry:
    """Return the highest-priority entry from a fuzzy match list."""
    return min(entries, key=lambda e: _fuzzy_tier(e.file_path, caller_path))


def _is_simple_identifier(expr: str) -> bool:
    """Return True if expr is a valid Python identifier (no operators, spaces, etc.)."""
    return expr.isidentifier()
