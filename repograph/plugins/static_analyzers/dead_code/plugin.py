"""Dead code static analyzer.

All dead-code detection logic lives here: the main analyzer plugin,
JavaScript/TypeScript heuristics, inheritance-based reachability, and
framework/stdlib dispatch exemptions.

Plugin contract
---------------
  kind:   static_analyzer
  hook:   on_graph_built
  input:  store (GraphStore)
  output: list[dict] — dead-code findings

`run_dead_code_analysis` is the shared entry used by `analyze()` and tests.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from repograph.core.plugin_framework import PluginManifest, StaticAnalyzerPlugin
from repograph.graph_store.store import GraphStore
from repograph.utils.fs import _is_utility_file, read_file_content
from repograph.utils.path_classifier import is_script_path, is_test_path


# ---------------------------------------------------------------------------
# Plugin manifest + class
# ---------------------------------------------------------------------------

class DeadCodeAnalyzerPlugin(StaticAnalyzerPlugin):
    """Detects dead (unreachable) symbols using multi-pass static analysis.

    Tiers
    -----
    definitely_dead  — zero incoming callers of any kind
    probably_dead    — only callers from test or script paths
    possibly_dead    — exported symbol with very few callers (optional tier)
    """

    manifest = PluginManifest(
        id="static_analyzer.dead_code",
        name="Dead code analyzer",
        kind="static_analyzer",
        description="Multi-pass dead symbol detection with confidence tiers.",
        requires=("call_edges", "symbols"),
        produces=("findings.dead_code",),
        hooks=("on_graph_built",),
        order=200,
        after=("static_analyzer.pathways",),
    )

    def analyze(self, store: GraphStore | None = None, **kwargs) -> list[dict]:
        """Return all dead-code findings from the graph store."""
        if store is None:
            # Demand-side call via service.run_analyzer_plugin
            service = kwargs.get("service")
            if service is None:
                return []
            return service.dead_code(min_tier="probably_dead")
        return run_dead_code_analysis(store)


def build_plugin() -> DeadCodeAnalyzerPlugin:
    """Called dynamically by ensure_default_static_analyzers_registered."""
    return DeadCodeAnalyzerPlugin()


# ---------------------------------------------------------------------------
# Main analysis entry point
# ---------------------------------------------------------------------------

def run_dead_code_analysis(store: GraphStore) -> list[dict]:
    """Run the full dead-code detection pass and return findings."""
    functions = store.get_all_functions()
    if not functions:
        return []

    call_edges = store.get_all_call_edges()

    # Build caller info per function
    caller_info = _build_caller_info(functions, call_edges, store)

    script_global_files = _get_script_global_files(store)
    html_reachable_names = _get_html_reachable_symbols(store)
    type_ref_file_paths = _get_type_referenced_file_paths(store)
    subclass_class_names = _get_subclass_class_names(store)

    findings: list[dict] = []

    for fn in functions:
        if _is_hard_exempt(fn):
            continue
        # Runtime traces proved this revision was executed — do not re-apply static dead flags
        # until source_hash changes (invalidated in upsert_function).
        if fn.get("runtime_observed") and (fn.get("runtime_observed_for_hash") or "") == (
            fn.get("source_hash") or ""
        ):
            continue
        if fn.get("is_closure_returned"):
            continue
        if fn.get("is_module_caller"):
            continue

        fp = fn.get("file_path") or ""

        if class_method_in_html_script_loaded_file(fn, script_global_files):
            continue

        fn_name = fn.get("name") or ""
        fn_qname = fn.get("qualified_name") or ""
        if fn_name in html_reachable_names or fn_qname in html_reachable_names:
            continue

        is_method_or_unknown = fn.get("is_method") is not False
        if is_method_or_unknown and fp in type_ref_file_paths:
            continue
        if is_method_or_unknown and _is_subclass_method(fn, subclass_class_names):
            continue
        if method_may_be_invoked_via_superclass_chain(fn, store):
            continue
        if is_logging_handler_emit_method(fn, store):
            continue
        if js_constructor_or_class_method_may_be_live(fn):
            continue
        if fn_name in _LIFECYCLE_NAMES:
            continue

        info = caller_info.get(fn["id"], _CallerInfo())
        tier, reason = _classify_tier(fn, info)

        ext = os.path.splitext(fp)[1].lower()
        if ext in _JS_EXTENSIONS and fn.get("is_script_global") and tier == "definitely_dead":
            tier = "probably_dead"
            reason = "js_global_scope_uncertain"

        if info.total == 0:
            dctx = "dead_everywhere"
        elif info.total <= (info.from_test + info.from_script):
            dctx = "dead_in_production"
        else:
            dctx = "dead_everywhere"

        store.update_function_flags(
            fn["id"],
            is_dead=True,
            dead_code_tier=tier,
            dead_code_reason=reason,
            dead_context=dctx,
        )
        findings.append({
            "id": fn["id"],
            "qualified_name": fn_qname,
            "file_path": fp,
            "line_start": fn.get("line_start", 0),
            "dead_code_tier": tier,
            "dead_code_reason": reason,
            "dead_context": dctx,
        })

    return findings


# ---------------------------------------------------------------------------
# JavaScript / TypeScript heuristics
# ---------------------------------------------------------------------------

_NEW_CLASS = re.compile(r"\bnew\s+([A-Za-z_$][\w$]*)\s*\(")
_HTML_INLINE_CALL = re.compile(
    r"(?:onclick|onload|onerror|onchange|onsubmit|onkeyup|onkeydown|"
    r"onmouseover|onfocus|onblur)\s*=\s*[\"'][^\"']*?([A-Za-z_$][\w$.]*)\s*\(",
    re.I,
)
_HTML_ADD_EVENT = re.compile(
    r"addEventListener\s*\(\s*[\"'][^\"']+[\"']\s*,\s*([A-Za-z_$][\w$.]*)\b",
    re.I,
)
_JS_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx"})


def js_class_likely_instantiated_in_file(class_name: str, file_path: str) -> bool:
    """True if source at *file_path* contains ``new ClassName(``."""
    try:
        src = read_file_content(file_path)
    except OSError:
        return False
    return any(m.group(1) == class_name for m in _NEW_CLASS.finditer(src))


def js_constructor_or_class_method_may_be_live(fn: dict) -> bool:
    fp = fn.get("file_path") or ""
    if not fp.endswith((".js", ".jsx", ".ts", ".tsx")):
        return False
    qn = (fn.get("qualified_name") or "").strip()
    if "." not in qn:
        return False
    cls = qn.split(".", 1)[0]
    return bool(cls) and js_class_likely_instantiated_in_file(cls, fp)


def class_method_in_html_script_loaded_file(fn: dict, script_global_files: set[str]) -> bool:
    fp = fn.get("file_path") or ""
    if fp not in script_global_files:
        return False
    return "." in (fn.get("qualified_name") or "")


def extract_html_reachable_symbols(html_source: str) -> set[str]:
    """Return symbol names referenced in HTML event handlers."""
    symbols: set[str] = set()
    for pattern in (_HTML_INLINE_CALL, _HTML_ADD_EVENT):
        for m in pattern.finditer(html_source):
            sym = m.group(1).strip()
            if sym:
                symbols.add(sym.split(".")[-1])
                symbols.add(sym)
    return symbols


# ---------------------------------------------------------------------------
# Inheritance-based reachability
# ---------------------------------------------------------------------------

_STDLIB_BASES = frozenset({"object", "Exception", "BaseException", "ABC", "Protocol"})


def method_may_be_invoked_via_superclass_chain(fn: dict, store: GraphStore) -> bool:
    qn = (fn.get("qualified_name") or "").strip()
    if "." not in qn:
        return False
    method_name = qn.rsplit(".", 1)[-1]
    child_class = qn.rsplit(".", 1)[0]
    fp = fn.get("file_path") or ""
    child_id = _find_class_id(store, child_class, fp)
    if not child_id:
        return False
    for base_name in _ancestor_class_names(store, child_id):
        if base_name in _STDLIB_BASES:
            continue
        if _function_exists(store, f"{base_name}.{method_name}"):
            return True
    return False


def rollup_override_incoming_callers(store: GraphStore, caller_counts: dict[str, int]) -> None:
    """Add base-method incoming caller counts onto subclass override nodes."""
    for fn in store.get_all_functions():
        parent_id = _base_method_id(fn, store)
        if parent_id:
            caller_counts[fn["id"]] = (
                caller_counts.get(fn["id"], 0) + caller_counts.get(parent_id, 0)
            )


def _find_class_id(store: GraphStore, class_name: str, fp: str) -> str | None:
    for cls in store.get_all_classes():
        if cls.get("file_path") != fp:
            continue
        if cls.get("qualified_name") == class_name or cls.get("name") == class_name:
            return cls.get("id")
    return None


def _ancestor_class_names(store: GraphStore, child_id: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    try:
        for r in store.query(
            "MATCH (c:Class {id: $cid})-[:EXTENDS]->(b:Class) RETURN b.name",
            {"cid": child_id},
        ):
            if r and r[0] and r[0] not in seen:
                seen.add(r[0]); names.append(r[0])
    except Exception:
        pass
    cls = next((c for c in store.get_all_classes() if c.get("id") == child_id), None)
    if cls:
        for b in cls.get("base_names") or []:
            if b and b not in seen:
                seen.add(b); names.append(b)
    return names


def _function_exists(store: GraphStore, qualified_name: str) -> bool:
    return any(f.get("qualified_name") == qualified_name for f in store.get_all_functions())


def _base_method_id(fn: dict, store: GraphStore) -> str | None:
    qn = (fn.get("qualified_name") or "").strip()
    if "." not in qn:
        return None
    method_name = qn.rsplit(".", 1)[-1]
    child_class = qn.rsplit(".", 1)[0]
    child_id = _find_class_id(store, child_class, fn.get("file_path") or "")
    if not child_id:
        return None
    for base_name in _ancestor_class_names(store, child_id):
        if base_name in _STDLIB_BASES:
            continue
        for f in store.get_all_functions():
            if f.get("qualified_name") == f"{base_name}.{method_name}":
                return f.get("id")
    return None


# ---------------------------------------------------------------------------
# Framework / stdlib dispatch exemptions
# ---------------------------------------------------------------------------

def is_logging_handler_emit_method(fn: dict, store: GraphStore) -> bool:
    if (fn.get("name") or "") != "emit":
        return False
    qn = (fn.get("qualified_name") or "").strip()
    if "." not in qn:
        return False
    class_name = qn.rsplit(".", 1)[0]
    fp = fn.get("file_path") or ""
    for cls in store.get_all_classes():
        if cls.get("file_path") != fp:
            continue
        if cls.get("qualified_name") != class_name and cls.get("name") != class_name:
            continue
        for base in cls.get("base_names") or []:
            b = (base or "").strip()
            if b == "logging.Handler" or (b.endswith(".Handler") and "logging" in b):
                return True
    return False


# ---------------------------------------------------------------------------
# Internal helpers (tier classification, caller info, exemptions)
# ---------------------------------------------------------------------------

_LIFECYCLE_NAMES = frozenset({
    "setUp", "tearDown", "setUpClass", "tearDownClass",
    "setUpModule", "tearDownModule",
    "setup_method", "teardown_method",
    "conftest", "fixture",
    "on_startup", "on_shutdown", "on_event",
    "lifespan",
    "emit",
})

_DUNDER = re.compile(r"^__\w+__$")
_TEST_PREFIX = re.compile(r"^test_|^Test[A-Z]")


class _CallerInfo:
    __slots__ = ("total", "from_test", "from_script", "from_prod", "fuzzy")

    def __init__(self) -> None:
        self.total = self.from_test = self.from_script = self.from_prod = self.fuzzy = 0


def _build_caller_info(
    functions: list[dict],
    call_edges: list[dict],
    store: GraphStore,
) -> dict[str, _CallerInfo]:
    fn_paths = {f["id"]: (f.get("file_path") or "") for f in functions}
    info: dict[str, _CallerInfo] = {f["id"]: _CallerInfo() for f in functions}
    for edge in call_edges:
        callee_id = edge.get("to") or edge.get("callee_id") or ""
        caller_id = edge.get("from") or edge.get("caller_id") or ""
        if callee_id not in info:
            continue
        ci = info[callee_id]
        ci.total += 1
        reason = (edge.get("reason") or "").strip().lower()
        if reason == "fuzzy":
            ci.fuzzy += 1
            continue
        caller_path = fn_paths.get(caller_id, "")
        if is_test_path(caller_path):
            ci.from_test += 1
        elif is_script_path(caller_path):
            ci.from_script += 1
        else:
            ci.from_prod += 1
    return info


def _classify_tier(fn: dict, info: _CallerInfo) -> tuple[str, str]:
    """Assign dead-code tier; utility/exported heuristics (F-02) before caller buckets."""
    fp = fn.get("file_path") or ""
    is_exported = bool(fn.get("is_exported"))

    if info.total == 0:
        if _is_utility_file(fp):
            return "possibly_dead", "utility_module_uncalled"
        if is_exported:
            return "possibly_dead", "exported_but_uncalled"
        return "definitely_dead", "zero_callers"

    if info.fuzzy > 0 and info.fuzzy == info.total:
        return "probably_dead", "only_fuzzy_callers"

    if info.from_prod == 0 and info.from_script == 0 and info.from_test > 0:
        return "probably_dead", "only_test_callers"

    if info.from_prod == 0 and info.from_script > 0:
        return "probably_dead", "script_callers_only"

    return "possibly_dead", "low_caller_count"


def _is_hard_exempt(fn: dict) -> bool:
    name = fn.get("name") or ""
    if fn.get("is_entry_point"):
        return True
    if _DUNDER.match(name):
        return True
    if _TEST_PREFIX.match(name):
        return True
    if is_test_path(fn.get("file_path") or ""):
        return True
    if fn.get("decorators"):
        return True
    return False


def _is_subclass_method(fn: dict, subclass_class_names: set[str]) -> bool:
    qn = fn.get("qualified_name") or ""
    if "." not in qn:
        return False
    return qn.split(".", 1)[0] in subclass_class_names


# ---------------------------------------------------------------------------
# Store queries used by run_dead_code_analysis
# ---------------------------------------------------------------------------

def _get_script_global_files(store: GraphStore) -> set[str]:
    try:
        rows = store.query(
            "MATCH (f:Function {is_script_global: true}) RETURN DISTINCT f.file_path"
        )
        return {r[0] for r in rows if r and r[0]}
    except Exception:
        return set()


def _get_html_reachable_symbols(store: GraphStore) -> set[str]:
    symbols: set[str] = set()
    try:
        rows = store.query(
            "MATCH (f:File) WHERE f.extension IN ['.html', '.htm'] RETURN f.abs_path"
        )
        for r in rows:
            abs_path = r[0] if r else None
            if not abs_path:
                continue
            try:
                src = read_file_content(abs_path)
                symbols |= extract_html_reachable_symbols(src)
            except Exception:
                pass
    except Exception:
        pass
    return symbols


def _get_type_referenced_file_paths(store: GraphStore) -> set[str]:
    try:
        rows = store.query(
            """
            MATCH (f:Function)-[:CALLS]->(t:Function)
            WHERE t.is_method = true
            RETURN DISTINCT t.file_path
            """
        )
        return {r[0] for r in rows if r and r[0]}
    except Exception:
        return set()


def _get_subclass_class_names(store: GraphStore) -> set[str]:
    try:
        rows = store.query(
            "MATCH (c:Class)-[:EXTENDS]->(:Class) RETURN DISTINCT c.name"
        )
        return {r[0] for r in rows if r and r[0]}
    except Exception:
        return set()
