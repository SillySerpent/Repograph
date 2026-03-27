# Canonical pathway assembly implementation owned by the pathways plugin.
"""PathwayAssembler — builds PathwayDoc objects from entry points via BFS."""
from __future__ import annotations

import hashlib
import re
from collections import deque
from datetime import datetime, timezone

from repograph.core.models import PathwayDoc, PathwayStep, VariableThread
from repograph.core.confidence import geometric_mean_confidence
from repograph.graph_store.store import GraphStore
from .curator import CuratedPathwayDef
from .pathway_bfs import (
    MAX_FANOUT,
    MAX_PATHWAY_STEPS,
    MIN_CONFIDENCE,
    should_skip_cross_language_step,
)
from repograph.variables.pathway import VariableThreadBuilder

_ROUTE_FILE = re.compile(r"/(routes|handlers|views|api|endpoints|controllers)/", re.I)
_SERVICE_FILE = re.compile(r"/(services?)/", re.I)
_ADAPTER_FILE = re.compile(r"/(adapters?|repositories?|db|models?|database)/", re.I)


class PathwayAssembler:
    """Assembles PathwayDoc from an entry function ID using BFS over CALLS and MAKES_HTTP_CALL edges."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store
        self._fn_cache: dict[str, dict | None] = {}

    def assemble(
        self,
        entry_function_id: str,
        curated_def: CuratedPathwayDef | None = None,
        used_names: set[str] | None = None,
    ) -> PathwayDoc | None:
        entry_fn = self._get_fn(entry_function_id)
        if not entry_fn:
            return None

        entry_file = entry_fn.get("file_path", "") or ""

        steps: list[PathwayStep] = []
        visited: set[str] = set()
        edge_confidences: list[float] = []
        # Queue: (func_id, order, via_http, http_method_used, lang_ref_file)
        # lang_ref_file is the file path used for cross-language filtering of outgoing
        # CALLS edges.  It starts as entry_file, but resets to a callee's own file
        # when we cross a language boundary via MAKES_HTTP_CALL, so that further CALLS
        # within that new language are not incorrectly blocked.
        queue: deque[tuple[str, int, bool, str, str]] = deque(
            [(entry_function_id, 0, False, "", entry_file)]
        )

        while queue and len(steps) < MAX_PATHWAY_STEPS:
            func_id, order, via_http, via_http_method, lang_ref_file = queue.popleft()
            if func_id in visited:
                continue
            visited.add(func_id)

            fn = self._get_fn(func_id)
            if not fn:
                continue

            # Steps reached via MAKES_HTTP_CALL get a dedicated role
            role = "cross_lang_http" if via_http else self._infer_role(fn, order, steps)

            # CALLS edges — filtered by cross-language guard using the current language
            # reference file (not always the original entry_file: after an HTTP boundary
            # crossing the reference resets to the callee's own language).
            outgoing = self._store.get_callees(func_id)
            outgoing_high = sorted(
                [e for e in outgoing if e.get("confidence", 0) >= MIN_CONFIDENCE],
                key=lambda e: -e.get("confidence", 0),
            )[:MAX_FANOUT]

            filtered: list[dict] = []
            for e in outgoing_high:
                callee_fn = self._get_fn(e["id"])
                cfp = callee_fn.get("file_path", "") if callee_fn else ""
                if callee_fn and should_skip_cross_language_step(lang_ref_file, cfp):
                    continue
                filtered.append(e)
            outgoing_high = filtered

            # MAKES_HTTP_CALL edges — bypass the cross-language filter (they are
            # explicitly cross-language by definition and should always be followed)
            http_outgoing = self._store.get_http_callees(func_id)
            http_outgoing_high = sorted(
                [e for e in http_outgoing if e.get("confidence", 0) >= MIN_CONFIDENCE],
                key=lambda e: -e.get("confidence", 0),
            )[:MAX_FANOUT]

            calls_next = (
                [e["id"] for e in outgoing_high]
                + [e["id"] for e in http_outgoing_high]
            )

            step = PathwayStep(
                order=order,
                function_id=func_id,
                function_name=fn.get("name", ""),
                file_path=fn.get("file_path", ""),
                line_start=fn.get("line_start", 0),
                role=role,
                calls_next=calls_next,
                confidence=fn.get("entry_score", 1.0) or 1.0,
                decorators=fn.get("decorators") or [],
                cross_lang_step=via_http,
                http_method=via_http_method,
            )
            steps.append(step)

            # Enqueue CALLS successors — same language context propagates
            for e in outgoing_high:
                edge_confidences.append(e.get("confidence", 1.0))
                if e["id"] not in visited:
                    queue.append((e["id"], order + 1, False, "", lang_ref_file))

            # Enqueue HTTP successors — language context resets to the callee's file
            for e in http_outgoing_high:
                edge_confidences.append(e.get("confidence", 1.0))
                if e["id"] not in visited:
                    callee_fn = self._get_fn(e["id"])
                    callee_file = (
                        callee_fn.get("file_path", "") if callee_fn else ""
                    ) or ""
                    queue.append(
                        (e["id"], order + 1, True, e.get("http_method", ""), callee_file)
                    )

        if len(steps) < 2:
            return None

        # Enforce minimum pathway depth — shallow pathways are noise
        if not curated_def and len(steps) < 3:
            return None

        # Mark terminals
        step_ids = {s.function_id for s in steps}
        for step in steps:
            has_next_in_path = any(nid in step_ids for nid in step.calls_next)
            if not has_next_in_path:
                step.role = "terminal"

        # Build variable threads
        vt_builder = VariableThreadBuilder()
        flows = self._store.get_flows_into_edges()
        var_rows = self._store.query(
            "MATCH (v:Variable) RETURN v.id, v.name, v.function_id, v.inferred_type"
        )
        var_nodes = {r[0]: {"id": r[0], "name": r[1], "function_id": r[2], "type": r[3]} for r in var_rows}
        # Normalise edge dicts for thread builder
        flows_normalised = [{"from_var": e["from"], "to_var": e["to"]} for e in flows]
        threads = vt_builder.build(
            [s.function_id for s in steps], flows_normalised, var_nodes
        )

        participating_files = list(dict.fromkeys(s.file_path for s in steps))
        confidence = geometric_mean_confidence(edge_confidences) if edge_confidences else 0.5

        # importance_score: captures how much of the codebase this pathway touches
        # and how central its entry point is.  Intentionally separate from confidence
        # (which measures static-analysis reliability, not relevance).
        #   step_count      — pathway breadth
        #   file_spread     — how many distinct files are crossed
        #   ep_weight       — entry-point score from Phase 10 (0 if not an entry point)
        ep_weight = float(entry_fn.get("entry_score") or 0.0)
        importance_score = round(
            (len(steps) * len(participating_files) * (ep_weight + 1.0)) / 100.0, 4
        )

        # Determine source
        is_test = any(p in entry_file.lower() for p in ("/tests/", "/test/", "tests/", "test/"))
        if curated_def:
            source = "hybrid"
        elif is_test:
            source = "auto_detected_test"
        else:
            source = "auto_detected"
        entry_qname = entry_fn.get("qualified_name", "")
        name = curated_def.name if curated_def else _auto_name(
            entry_fn.get("name", "unknown"),
            entry_qname,
            entry_fn.get("file_path", ""),
        )
        if used_names is not None:
            if name in used_names:
                suffix = hashlib.sha256(entry_function_id.encode()).hexdigest()[:10]
                name = f"{name}_{suffix}"
            used_names.add(name)
        display = curated_def.display_name if curated_def else name.replace("_", " ").title()
        if curated_def:
            desc = curated_def.description
        else:
            from .descriptions import generate_description

            desc = generate_description(
                entry_fn,
                participating_files,
                self._store,
                [],
                step_count=len(steps),
                file_count=len(participating_files),
            )
        terminal_type = curated_def.terminal_hint if curated_def else _detect_terminal(steps)

        return PathwayDoc(
            id=f"pathway:{entry_function_id}",
            name=name,
            display_name=display,
            description=desc,
            entry_file=entry_fn.get("file_path", ""),
            entry_function=entry_fn.get("qualified_name", ""),
            terminal_type=terminal_type,
            steps=steps,
            variable_threads=threads,
            participating_files=participating_files,
            confidence=confidence,
            source=source,
            context_doc="",
            generated_at=datetime.now(timezone.utc),
            importance_score=importance_score,
        )

    def _get_fn(self, fn_id: str) -> dict | None:
        if fn_id not in self._fn_cache:
            self._fn_cache[fn_id] = self._store.get_function_by_id(fn_id)
        return self._fn_cache[fn_id]

    def _infer_role(self, fn: dict, order: int, steps: list[PathwayStep]) -> str:
        fp = fn.get("file_path", "")
        if order == 0:
            return "entry"
        if _ADAPTER_FILE.search(fp):
            return "adapter"
        if _SERVICE_FILE.search(fp):
            return "service"
        if _ROUTE_FILE.search(fp):
            return "handler"
        return "service" if order > 1 else "handler"


import os as _os

# Function names so common that they provide no path-identifying information.
# When the entry function has one of these names (and no class prefix), the
# file-stem is prepended so the pathway is distinguishable.
_GENERIC_FUNC_NAMES: frozenset[str] = frozenset({
    "run", "main", "start", "stop", "init", "execute", "process",
    "handle", "dispatch", "_", "__", "setup", "teardown", "build",
    "create", "update", "delete", "get", "post", "call", "invoke",
    "load", "save", "read", "write", "send", "recv", "close", "open",
})


def _auto_name(
    func_name: str,
    qualified_name: str = "",
    file_path: str = "",
) -> str:
    """Generate a stable, human-readable pathway name.

    Rules (applied in order):
    1. Strip common action prefixes (handle_, on_, do_, run_).
    2. Prepend snake_case class name when available (prevents collisions
       between same-named methods on different classes).
    3. If the base name is too generic (in ``_GENERIC_FUNC_NAMES``) or shorter
       than 4 chars *and* there is no class prefix, prepend the file stem so
       the name is meaningful rather than a hash-suffixed opaque token.
    4. Append ``_flow`` suffix if not already present.
    """
    base = re.sub(r"^(handle_?|on_?|do_?|run_?)", "", func_name.lower()).strip("_")

    # Build class prefix from qualified name (e.g. "LiveBroker.submit_order" → "live_broker_")
    class_prefix = ""
    if qualified_name and "." in qualified_name:
        class_part = qualified_name.split(".")[0]
        class_prefix = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", class_part).lower() + "_"

    # If no class context and name is too generic, use the file stem instead
    if not class_prefix and (base in _GENERIC_FUNC_NAMES or len(base) <= 4):
        stem = _os.path.splitext(_os.path.basename(file_path))[0] if file_path else ""
        # Strip leading phase prefixes like "p04_" or "p11b_"
        stem = re.sub(r"^p\d+[a-z]?_", "", stem)
        if stem and stem not in _GENERIC_FUNC_NAMES and len(stem) >= 2:
            base = f"{stem}_{base}" if base and base not in _GENERIC_FUNC_NAMES else stem

    name = class_prefix + base
    # Ensure the name isn't just "_flow" or empty
    if not name or name == "_flow":
        stem = _os.path.splitext(_os.path.basename(file_path))[0] if file_path else "unknown"
        name = re.sub(r"^p\d+[a-z]?_", "", stem) or "unknown"

    return (name + "_flow") if not name.endswith("_flow") else name


def _detect_terminal(steps: list[PathwayStep]) -> str:
    """Guess terminal type from last step's file path."""
    if not steps:
        return "return"
    last = steps[-1]
    fp = last.file_path.lower()
    if any(x in fp for x in ("db", "database", "model", "repository")):
        return "db_write"
    if any(x in fp for x in ("http", "request", "client", "api")):
        return "http_response"
    return "return"
