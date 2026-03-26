"""Phase 5b — Callback Detection: detect registration patterns and create synthetic CALLS edges.

Many frameworks and application patterns register functions as callbacks
without a direct call-site visible to static analysis:

  - ``bus.subscribe(EventType.FOO, self.on_foo)``
  - ``register_handler("name", handler_fn)``
  - ``lifecycle.register("svc", start_fn, stop_fn)``
  - ``app.route("/path")(handler)``

This phase scans parsed call sites for these patterns and creates
synthetic CALLS edges with ``reason="callback_registration"`` and a
moderate confidence (0.6).

The detection is pattern-based and universal — it does not hard-code
specific framework APIs but instead looks for common registration idioms
where a function/method reference is passed as an argument.
"""
from __future__ import annotations

import re

from repograph.core.models import ParsedFile, CallEdge
from repograph.graph_store.store import GraphStore
from repograph.parsing.symbol_table import SymbolTable

# Confidence for callback-registration edges — higher than fuzzy (0.3)
# but lower than import-resolved (0.9) since we're inferring the
# connection from a registration pattern, not a direct call.
CONF_CALLBACK = 0.6

# Common registration method names (case-insensitive matching)
_REGISTER_PATTERNS = re.compile(
    r"^(?:register|subscribe|add_handler|add_listener|on|bind|connect|"
    r"add_callback|set_handler|set_callback|add_hook|register_handler|"
    r"add_event_listener|register_route)$",
    re.I,
)

# Patterns in the callee expression text that suggest callback registration
# e.g. "bus.subscribe", "lifecycle.register", "emitter.on"
_REGISTER_ATTR_PATTERNS = re.compile(
    r"\.(?:register|subscribe|add_handler|add_listener|on|bind|connect|"
    r"add_callback|set_handler|set_callback|add_hook|register_handler|"
    r"add_event_listener|register_route)$",
    re.I,
)


def run(
    parsed_files: list[ParsedFile],
    store: GraphStore,
    symbol_table: SymbolTable,
) -> None:
    """
    Scan all call sites for callback registration patterns.

    When we find a call like ``bus.subscribe(EventType.X, self.on_tick)``,
    we create a synthetic CALLS edge from the *registration site's caller*
    to the *registered callback function*.

    This makes the callback reachable in the call graph, which improves:
    - Dead code detection (callback won't be flagged as dead)
    - Pathway discovery (event-driven flows become visible)
    - Community detection (event subscribers cluster with publishers)
    """
    created: set[tuple[str, str]] = set()

    for pf in parsed_files:
        for site in pf.call_sites:
            # Check if this call site looks like a registration call
            callee = site.callee_text
            if not _is_registration_call(callee):
                continue

            # Look for function/method references in arguments
            # These are the callbacks being registered
            callback_refs = _extract_callback_refs(site.argument_exprs)

            for ref in callback_refs:
                # Try to resolve the callback reference
                target_id = _resolve_callback(
                    ref, site.file_path, symbol_table, pf.imports
                )
                if target_id is None:
                    continue

                # Create edge: caller → callback (not caller → register fn)
                key = (site.caller_function_id, target_id)
                if key in created:
                    continue
                created.add(key)

                edge = CallEdge(
                    from_function_id=site.caller_function_id,
                    to_function_id=target_id,
                    call_site_line=site.call_site_line,
                    argument_names=[],
                    confidence=CONF_CALLBACK,
                    reason="callback_registration",
                )
                try:
                    store.insert_call_edge(edge)
                except Exception:
                    pass


def _is_registration_call(callee_text: str) -> bool:
    """Return True if the callee looks like a callback registration method."""
    # Direct name match: register(...)
    if _REGISTER_PATTERNS.match(callee_text):
        return True
    # Attribute access: bus.subscribe(...)
    if _REGISTER_ATTR_PATTERNS.search(callee_text):
        return True
    return False


def _extract_callback_refs(arg_exprs: list[str]) -> list[str]:
    """Extract likely function/method references from argument expressions.

    Callback references are typically:
    - ``self.on_tick`` or ``self._handle_bar``
    - ``handler_fn`` (bare name)
    - ``MyClass.method``

    We skip string literals, numeric literals, enum values, and complex
    expressions to avoid false positives.
    """
    refs: list[str] = []
    for expr in arg_exprs:
        expr = expr.strip()
        # Skip obvious non-references
        if not expr:
            continue
        if expr.startswith(("'", '"', "b'", 'b"')):
            continue  # string literal
        if expr.replace(".", "").replace("_", "").isdigit():
            continue  # numeric
        if expr.startswith(("True", "False", "None", "0x", "0b")):
            continue
        # Skip enum-like references: EventType.FOO, Status.ACTIVE
        if "." in expr and expr.split(".")[-1].isupper():
            continue
        # Skip complex expressions with operators
        if any(op in expr for op in ("(", ")", "+", "-", "*", "/", "=", "[", "]", "{", "}")):
            continue
        # Looks like a function/method reference
        refs.append(expr)
    return refs


def _resolve_callback(
    ref: str,
    file_path: str,
    symbol_table: SymbolTable,
    imports: list,
) -> str | None:
    """Try to resolve a callback reference to a function ID.

    Handles:
    - ``self.method`` → look up method name in same file
    - ``module.func`` → look up via imports
    - ``bare_name`` → look up in file, then global
    """
    # self.method or cls.method
    if ref.startswith(("self.", "cls.")):
        method_name = ref.split(".", 1)[1]
        entries = symbol_table.lookup_in_file(file_path, method_name)
        if entries:
            return entries[0].node_id
        return None

    # Attribute access: obj.method
    if "." in ref:
        method_name = ref.split(".")[-1]
        # Try import-resolved first
        import_entries = symbol_table.lookup_imported_symbol(
            file_path, imports, method_name
        )
        if import_entries:
            return import_entries[0].node_id
        # Try same-file
        entries = symbol_table.lookup_in_file(file_path, method_name)
        if entries:
            return entries[0].node_id
        return None

    # Bare name
    entries = symbol_table.lookup_in_file(file_path, ref)
    if entries:
        return entries[0].node_id
    import_entries = symbol_table.lookup_imported_symbol(
        file_path, imports, ref
    )
    if import_entries:
        return import_entries[0].node_id
    return None
