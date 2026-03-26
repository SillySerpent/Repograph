"""Duplicate symbol static analyzer.

The duplicate-detection implementation lives here so the sync pipeline and
plugin scheduler share one source of truth.
"""
from __future__ import annotations

from repograph.core.plugin_framework import PluginManifest, StaticAnalyzerPlugin
from repograph.graph_store.store import GraphStore


class DuplicateSymbolAnalyzerPlugin(StaticAnalyzerPlugin):
    manifest = PluginManifest(
        id="static_analyzer.duplicates",
        name="Duplicate symbol analyzer",
        kind="static_analyzer",
        description="Detects duplicate symbol groups and persists canonical/superseded guidance.",
        requires=("symbols",),
        produces=("findings.duplicates",),
        hooks=("on_graph_built",),
        order=210,
        after=("static_analyzer.pathways",),
    )

    def analyze(self, store: GraphStore | None = None, config=None, **kwargs):
        if store is None:
            service = kwargs.get("service")
            if service is None:
                return []
            return service.duplicates(min_severity=kwargs.get("min_severity", "medium"))
        same_language_only = getattr(config, "duplicates_same_language_only", True) if config is not None else True
        return [g.as_dict() for g in run_duplicate_analysis(store, same_language_only=same_language_only)]


def build_plugin() -> DuplicateSymbolAnalyzerPlugin:
    return DuplicateSymbolAnalyzerPlugin()


import json
import os
import re
from collections import defaultdict

from repograph.core.models import DuplicateSymbolGroup
from repograph.graph_store.store import GraphStore
from repograph.utils.fs import EXTENSION_TO_LANGUAGE
from repograph.utils.hashing import hash_string


# Method names so common across interface implementations that same-name
# across files is expected, not a duplication problem.
_COMMON_INTERFACE_NAMES = frozenset({
    "generate", "compute", "run", "main", "start", "stop", "close",
    "tag", "name", "enabled", "update", "reset", "check", "get", "set",
    "execute", "process", "handle", "validate", "build", "create",
    "load", "save", "parse", "format", "render",
})

_DUNDER_RE = re.compile(r"^__\w+__$")

# Path patterns identifying test and script files
_NON_PROD_PATTERNS = (
    "/tests/", "/test/", "tests/", "test/",
    "/test_", "/spec/", "/specs/",
    "scripts/", "/scripts/",
)


def run_duplicate_analysis(store: GraphStore, same_language_only: bool = True) -> list[DuplicateSymbolGroup]:
    """Detect and persist duplicate symbol groups.

    Clears any existing DuplicateSymbol nodes before inserting fresh results
    so re-runs are always idempotent.

    Parameters
    ----------
    same_language_only:
        If True, skip high-severity groups whose files map to more than one
        Repograph language (e.g. same bare name in ``.py`` and ``.js``).
    """
    store.clear_duplicate_symbols()

    functions = store.get_all_functions()
    classes = store.get_all_classes()

    groups: list[DuplicateSymbolGroup] = []
    high_groups, medium_qname_groups = _find_high_severity(
        functions, classes, store, same_language_only
    )
    groups.extend(high_groups)
    groups.extend(medium_qname_groups)
    groups.extend(_find_medium_severity(functions))
    groups.extend(_find_low_severity(functions))

    # I-03: Attach canonical_path / superseded_paths to every group.
    # Build a fast lookup: file_path → caller count (proxy for "how used").
    dead_ids: set[str] = {f["id"] for f in functions if f.get("is_dead")}
    fn_by_qname: dict[str, list[dict]] = {}
    for fn in functions:
        qn = fn.get("qualified_name") or fn.get("name") or ""
        fn_by_qname.setdefault(qn, []).append(fn)

    for group in groups:
        # Collect function/class records for this group
        group_items: list[dict] = []
        for fp in group.file_paths:
            for fn in fn_by_qname.get(group.name, []):
                if fn.get("file_path") == fp:
                    group_items.append(fn)
                    break
            else:
                # Fallback: minimal dict so canonical scorer still works
                group_items.append({"file_path": fp, "name": group.name, "id": ""})

        canonical, superseded = _select_canonical(group_items, dead_ids)
        group.canonical_path = canonical
        group.superseded_paths = superseded

        try:
            store.upsert_duplicate_symbol(group)
        except Exception:
            pass

    return groups


# ---------------------------------------------------------------------------
# High severity — same qualified name + identical body hash (multi-file)
# ---------------------------------------------------------------------------

def _language_for_path(fp: str) -> str:
    ext = os.path.splitext(fp)[1].lower()
    return EXTENSION_TO_LANGUAGE.get(ext, "")


def _all_same_non_empty_source_hash(items: list[dict]) -> bool:
    """True when every item has the same non-empty ``source_hash``."""
    hashes = [(it.get("source_hash") or "").strip() for it in items]
    if not all(hashes):
        return False
    return len(set(hashes)) == 1


def _find_high_severity(
    functions: list[dict],
    classes: list[dict],
    store: GraphStore | None,
    same_language_only: bool = True,
) -> tuple[list[DuplicateSymbolGroup], list[DuplicateSymbolGroup]]:
    """Return (high-severity groups, medium groups for same-qname / same-cname hash mismatch)."""
    del store  # reserved for future store-based signals
    dead_ids: set[str] = {f["id"] for f in functions if f.get("is_dead")}

    high_groups: list[DuplicateSymbolGroup] = []
    medium_groups: list[DuplicateSymbolGroup] = []

    # --- Functions ---
    by_qname: defaultdict[str, list[dict]] = defaultdict(list)
    for fn in functions:
        name = fn.get("name", "") or ""
        if _DUNDER_RE.match(name):
            continue
        if name in _COMMON_INTERFACE_NAMES:
            continue
        qname = fn.get("qualified_name", "") or ""
        fp = fn.get("file_path", "") or ""
        if _is_non_prod(fp):
            continue
        by_qname[qname].append(fn)

    for qname, fns in by_qname.items():
        file_paths = list({f["file_path"] for f in fns})
        if len(file_paths) < 2:
            continue
        if same_language_only:
            langs = {_language_for_path(fp) for fp in file_paths}
            langs.discard("")
            if len(langs) > 1:
                continue
        is_superseded = any(f["id"] in dead_ids for f in fns) and any(
            f["id"] not in dead_ids for f in fns
        )
        if _all_same_non_empty_source_hash(fns):
            h = (fns[0].get("source_hash") or "").strip()
            group_id = hash_string(f"high:fn:{qname}:{h}")[:16]
            high_groups.append(DuplicateSymbolGroup(
                id=group_id,
                name=qname,
                kind="function",
                occurrence_count=len(fns),
                file_paths=sorted(file_paths),
                severity="high",
                reason="same_qualified_name_identical_body",
                is_superseded=is_superseded,
            ))
        else:
            group_id = hash_string(f"medium:qname:fn:{qname}")[:16]
            medium_groups.append(DuplicateSymbolGroup(
                id=group_id,
                name=qname,
                kind="function",
                occurrence_count=len(fns),
                file_paths=sorted(file_paths),
                severity="medium",
                reason="same_qualified_name_different_body",
                is_superseded=is_superseded,
            ))

    # --- Classes (same bare name, compare class body slice hashes) ---
    by_cname: defaultdict[str, list[dict]] = defaultdict(list)
    for cls in classes:
        name = cls.get("name", "") or ""
        if _DUNDER_RE.match(name):
            continue
        fp = cls.get("file_path", "") or ""
        if _is_non_prod(fp):
            continue
        by_cname[name].append(cls)

    for cname, clss in by_cname.items():
        file_paths = list({c["file_path"] for c in clss})
        if len(file_paths) < 2:
            continue
        if same_language_only:
            langs = {_language_for_path(fp) for fp in file_paths}
            langs.discard("")
            if len(langs) > 1:
                continue
        if _all_same_non_empty_source_hash(clss):
            h = (clss[0].get("source_hash") or "").strip()
            group_id = hash_string(f"high:cls:{cname}:{h}")[:16]
            high_groups.append(DuplicateSymbolGroup(
                id=group_id,
                name=cname,
                kind="class",
                occurrence_count=len(clss),
                file_paths=sorted(file_paths),
                severity="high",
                reason="same_class_name_identical_body",
                is_superseded=False,
            ))
        else:
            group_id = hash_string(f"medium:qname:cls:{cname}")[:16]
            medium_groups.append(DuplicateSymbolGroup(
                id=group_id,
                name=cname,
                kind="class",
                occurrence_count=len(clss),
                file_paths=sorted(file_paths),
                severity="medium",
                reason="same_class_name_different_body",
                is_superseded=False,
            ))

    return high_groups, medium_groups


# ---------------------------------------------------------------------------
# Medium severity — same name + identical signature in 2+ non-test files
# ---------------------------------------------------------------------------

def _find_medium_severity(functions: list[dict]) -> list[DuplicateSymbolGroup]:
    """Return groups of functions with identical (name, signature) in 2+ prod files."""
    by_sig: defaultdict[tuple[str, str], list[dict]] = defaultdict(list)
    for fn in functions:
        name = fn.get("name", "") or ""
        if _DUNDER_RE.match(name):
            continue
        if name in _COMMON_INTERFACE_NAMES:
            continue
        fp = fn.get("file_path", "") or ""
        if _is_non_prod(fp):
            continue
        sig = _normalise_signature(fn.get("signature", "") or "")
        if not sig:
            continue
        by_sig[(name, sig)].append(fn)

    dead_ids: set[str] = {f["id"] for f in functions if f.get("is_dead")}

    groups: list[DuplicateSymbolGroup] = []
    for (name, sig), fns in by_sig.items():
        file_paths = list({f["file_path"] for f in fns})
        if len(file_paths) < 2:
            continue
        qnames = {f.get("qualified_name") or "" for f in fns}
        if len(qnames) == 1 and next(iter(qnames), ""):
            # Same qualified name across files — handled by qname high/medium path
            continue
        is_superseded = any(f["id"] in dead_ids for f in fns) and any(
            f["id"] not in dead_ids for f in fns
        )
        group_id = hash_string(f"medium:fn:{name}:{sig}")[:16]
        groups.append(DuplicateSymbolGroup(
            id=group_id,
            name=name,
            kind="function",
            occurrence_count=len(fns),
            file_paths=sorted(file_paths),
            severity="medium",
            reason="same_name_and_signature_multi_file",
            is_superseded=is_superseded,
        ))
    return groups


# ---------------------------------------------------------------------------
# Low severity — same bare name 3+ times in the same file (outside tests)
# ---------------------------------------------------------------------------

def _find_low_severity(functions: list[dict]) -> list[DuplicateSymbolGroup]:
    """Return groups of functions with the same name 3+ times in one non-test file."""
    by_file_name: defaultdict[tuple[str, str], list[dict]] = defaultdict(list)
    for fn in functions:
        name = fn.get("name", "") or ""
        if _DUNDER_RE.match(name):
            continue
        fp = fn.get("file_path", "") or ""
        if _is_non_prod(fp):
            continue
        by_file_name[(fp, name)].append(fn)

    groups: list[DuplicateSymbolGroup] = []
    for (fp, name), fns in by_file_name.items():
        if len(fns) < 3:
            continue
        group_id = hash_string(f"low:fn:{fp}:{name}")[:16]
        groups.append(DuplicateSymbolGroup(
            id=group_id,
            name=name,
            kind="function",
            occurrence_count=len(fns),
            file_paths=[fp],
            severity="low",
            reason="same_name_repeated_in_file",
            is_superseded=False,
        ))
    return groups


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_non_prod(file_path: str) -> bool:
    """Return True if the file path belongs to tests or scripts."""
    fp = file_path.replace("\\", "/").lower()
    return any(pat in fp for pat in _NON_PROD_PATTERNS)


def _normalise_signature(sig: str) -> str:
    """Strip whitespace and return-type annotations for signature comparison.

    We compare only the parameter shapes, not return types, since return type
    annotations are often omitted inconsistently.
    """
    # Remove return type annotation (everything after ' -> ' or ': ')
    sig = re.sub(r"\s*->.*$", "", sig)
    sig = re.sub(r"\s*:\s*\S+\s*$", "", sig)
    # Collapse whitespace
    sig = re.sub(r"\s+", " ", sig).strip()
    return sig


def _select_canonical(
    items: list[dict],
    dead_ids: set[str],
) -> tuple[str, list[str]]:
    """Choose the canonical (authoritative) file path among duplicate occurrences.

    Scoring heuristic per occurrence (higher = more canonical):
    - +3  if this copy has more callers than any other copy
    - +2  if the file's bare name matches the symbol name
          (e.g. ``idgen.py`` for ``new_advisor_decision_id``)
    - +1  if the file lives in a more specific / deeper module path
    - +1  if this copy is NOT flagged as dead
    - -5  if this copy IS flagged as dead (strong signal it is the stale copy)

    Returns
    -------
    (canonical_path, superseded_paths)
    """
    if not items:
        return "", []
    if len(items) == 1:
        return items[0].get("file_path", ""), []

    def _score(item: dict) -> int:
        fp = item.get("file_path", "") or ""
        name = item.get("name", "") or item.get("qualified_name", "") or ""
        is_dead = item.get("id", "") in dead_ids

        score = 0
        # Penalise dead copies heavily
        if is_dead:
            score -= 5
        else:
            score += 1

        # File-name match: idgen.py → score for id-related functions
        basename = os.path.splitext(os.path.basename(fp))[0].lower().replace("_", "")
        sym_lower = name.lower().replace("_", "").split(".")[-1]
        if sym_lower and (sym_lower in basename or basename in sym_lower):
            score += 2

        # Specificity: more path segments = more specific module
        score += min(fp.count("/"), 4)  # cap at 4 to avoid dominance

        # Caller count
        caller_count = item.get("_caller_count", 0) or 0
        if caller_count > 0:
            score += 3

        return score

    scored = sorted(items, key=_score, reverse=True)
    canonical = scored[0].get("file_path", "")
    superseded = [
        it.get("file_path", "")
        for it in scored[1:]
        if it.get("file_path", "") != canonical
    ]
    return canonical, superseded

run = run_duplicate_analysis
