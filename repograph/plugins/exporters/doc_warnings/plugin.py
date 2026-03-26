"""Doc symbol cross-check exporter plugin.

Scans all Markdown files for backtick-quoted symbol references and checks
whether each still exists in the graph.  Writes DocWarning nodes and returns
a summary dict.

Fires on: on_export
"""
from __future__ import annotations

import re

from repograph.core.evidence import CAP_DOC_WARNINGS, SOURCE_STATIC, evidence_tag
from repograph.core.models import DocSymbolWarning
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest
from repograph.graph_store.store import GraphStore
from repograph.pipeline.phases.p14_context import should_skip_moved_reference_for_prose
from repograph.utils.hashing import hash_string
from repograph.utils import logging as rg_log

# ---------------------------------------------------------------------------
# Manifest + plugin class
# ---------------------------------------------------------------------------

class DocWarningsExporterPlugin(ExporterPlugin):
    """Scans Markdown docs for stale or moved symbol references."""

    manifest = PluginManifest(
        id="exporter.doc_warnings",
        name="Doc warnings exporter",
        kind="exporter",
        description="Checks backtick symbol references in Markdown against the live graph.",
        requires=(CAP_DOC_WARNINGS,),
        produces=(evidence_tag(CAP_DOC_WARNINGS, SOURCE_STATIC).kind,),
        hooks=("on_export",),
        order=170,
    )

    def export(self, store: GraphStore | None = None, repograph_dir: str = "",
               config=None, **kwargs) -> dict:
        """Run the doc symbol cross-check and return a summary."""
        if store is None:
            service = kwargs.get("service")
            if service is None:
                return {"kind": "doc_warnings", "count": 0}
            return service.doc_warnings()
        flag_unknown = False
        if config is not None:
            try:
                from repograph.settings import load_doc_symbol_options
                repo_root = getattr(config, "repo_root", ".")
                flag_unknown = load_doc_symbol_options(repo_root)["doc_symbols_flag_unknown"]
            except Exception as exc:
                rg_log.warn_once(f"doc_warnings: failed loading doc symbol options: {exc}")
        warnings = run(store, flag_unknown=flag_unknown)
        return {
            "kind": "doc_warnings",
            "count": len(warnings),
            "evidence": evidence_tag(CAP_DOC_WARNINGS, SOURCE_STATIC).as_dict(),
        }


def build_plugin() -> DocWarningsExporterPlugin:
    return DocWarningsExporterPlugin()


# ---------------------------------------------------------------------------
# Core implementation (called by plugin.export() and tests)
# ---------------------------------------------------------------------------

_INLINE_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_MIN_TOKEN_LEN = 3
_SKIP_STALENESS_FM_RE = re.compile(r"^---\s*\n(?P<body>.*?)\n---\s*", re.S | re.M)
_SKIP_STALENESS_FLAG_RE = re.compile(r"^repograph_skip_staleness:\s*true\s*$", re.M | re.I)
_EXAMPLES_ONLY_MARK = "<!-- repograph: examples-only -->"
_SKIP_TOKENS = frozenset({
    "True", "False", "None", "true", "false", "null", "undefined",
    "int", "str", "float", "bool", "list", "dict", "set", "tuple",
    "Any", "Optional", "Union", "List", "Dict", "Set", "Tuple",
    "self", "cls", "args", "kwargs",
    "async", "await", "return", "yield", "import", "from", "class",
    "def", "if", "else", "for", "while", "with", "try", "except",
    "GET", "POST", "PUT", "DELETE", "PATCH",
    "TODO", "FIXME", "NOTE", "WARNING", "ERROR",
})
_IDENT_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")


def run(store: GraphStore, flag_unknown: bool = False) -> list[DocSymbolWarning]:
    """Scan all indexed Markdown files and persist DocWarning records.

    Clears existing warnings before inserting fresh results (idempotent).
    Returns the list of warnings written.
    """
    store.clear_doc_warnings()
    symbol_index = _build_symbol_index(store)
    if not symbol_index:
        return []
    try:
        rows = store.query(
            "MATCH (f:File) WHERE f.language = 'markdown' RETURN f.path, f.id"
        )
    except Exception as exc:
        rg_log.warn_once(f"doc_warnings: failed listing indexed markdown files: {exc}")
        return []
    all_warnings: list[DocSymbolWarning] = []
    for row in rows:
        md_path = row[0]
        warnings = _check_doc_file(md_path, symbol_index, store, flag_unknown=flag_unknown)
        for w in warnings:
            try:
                store.upsert_doc_warning(w)
                all_warnings.append(w)
            except Exception as exc:
                rg_log.warn_once(f"doc_warnings: failed persisting warning for {md_path}:{w.line_number}: {exc}")
    return all_warnings


def _build_symbol_index(store: GraphStore) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    try:
        for row in store.query(
            "MATCH (f:Function) WHERE f.is_module_caller = false OR f.is_module_caller IS NULL "
            "RETURN f.name, f.qualified_name, f.file_path"
        ):
            name, qname, fp = row[0], row[1], row[2]
            if name: index.setdefault(name, []).append(fp)
            if qname and qname != name: index.setdefault(qname, []).append(fp)
    except Exception as exc:
        rg_log.warn_once(f"doc_warnings: failed indexing functions: {exc}")
    try:
        for row in store.query("MATCH (c:Class) RETURN c.name, c.qualified_name, c.file_path"):
            name, qname, fp = row[0], row[1], row[2]
            if name: index.setdefault(name, []).append(fp)
            if qname and qname != name: index.setdefault(qname, []).append(fp)
    except Exception as exc:
        rg_log.warn_once(f"doc_warnings: failed indexing classes: {exc}")
    return index


def _check_doc_file(md_path, symbol_index, store, *, flag_unknown=False):
    try:
        if not store.query("MATCH (f:File {path: $p}) RETURN f.id", {"p": md_path}):
            return []
    except Exception as exc:
        rg_log.warn_once(f"doc_warnings: failed querying markdown files: {exc}")
        return []
    content = _read_doc_file(md_path, store)
    if content is None or _file_skipped_by_front_matter(content):
        return []
    skip_lines = _examples_only_skip_line_numbers(content)
    warnings = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if lineno in skip_lines: continue
        for m in _INLINE_BACKTICK_RE.finditer(line):
            w = _check_token(m.group(1).strip(), lineno, line, md_path,
                             symbol_index, flag_unknown=flag_unknown)
            if w: warnings.append(w)
    return warnings


def _check_token(token, lineno, line, doc_path, symbol_index, *, flag_unknown=False):
    if len(token) < _MIN_TOKEN_LEN or token in _SKIP_TOKENS or not _IDENT_RE.match(token):
        return None
    file_paths = symbol_index.get(token)
    if file_paths is None:
        if flag_unknown and "." in token:
            return DocSymbolWarning(
                id=hash_string(f"unknown:{doc_path}:{lineno}:{token}")[:24],
                doc_path=doc_path, line_number=lineno, symbol_text=token,
                warning_type="unknown_reference", severity="medium",
                context_snippet=line.strip()[:120],
            )
        return None
    path_hint = _extract_path_hint(line, token)
    if path_hint and not any(path_hint in fp for fp in file_paths):
        if should_skip_moved_reference_for_prose(line, token):
            return None
        return DocSymbolWarning(
            id=hash_string(f"moved:{doc_path}:{lineno}:{token}")[:24],
            doc_path=doc_path, line_number=lineno, symbol_text=token,
            warning_type="moved_reference", severity="high",
            context_snippet=line.strip()[:120],
        )
    return None


def _extract_path_hint(line, token):
    if "." in token:
        return "/".join(token.split(".")[:-1])
    m = re.search(r"(\w[\w/.-]+\.py)\b", line)
    return m.group(1) if m else None


def _file_skipped_by_front_matter(content):
    m = _SKIP_STALENESS_FM_RE.match(content)
    return bool(m and _SKIP_STALENESS_FLAG_RE.search(m.group("body")))


def _examples_only_skip_line_numbers(content):
    skip = set()
    lines = content.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        if _EXAMPLES_ONLY_MARK not in lines[i]:
            i += 1; continue
        i += 1
        while i < len(lines) and not lines[i].strip(): i += 1
        if i >= len(lines): break
        if lines[i].lstrip().startswith("```"):
            skip.add(i + 1); i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                skip.add(i + 1); i += 1
            if i < len(lines): skip.add(i + 1); i += 1
        else:
            while i < len(lines) and lines[i].strip():
                skip.add(i + 1); i += 1
    return skip


def _read_doc_file(md_path, store):
    try:
        rows = store.query(
            "MATCH (f:File {path: $p}) RETURN f.abs_path LIMIT 1",
            {"p": md_path},
        )
        if not rows or not rows[0][0]:
            return None
        with open(rows[0][0], encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception as exc:
        rg_log.warn_once(f"doc_warnings: failed reading markdown file {md_path}: {exc}")
    return None
