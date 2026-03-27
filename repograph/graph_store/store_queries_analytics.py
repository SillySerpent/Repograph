"""GraphStore call graph, pathways, stats, search, and analytics queries."""
from __future__ import annotations

import json
import re

from repograph.graph_store.store_base import GraphStoreBase

# Human-readable meaning of ``get_test_coverage_map`` / ``RepoGraph.test_coverage``.
ENTRY_POINT_TEST_COVERAGE_DEFINITION = (
    "Per production file: share of Phase-10 entry-point functions that have at "
    "least one CALLS edge from a function with is_test=true (test code). "
    "This is static graph reachability from tests to entry points, not line "
    "or branch coverage."
)

ANY_CALL_TEST_COVERAGE_DEFINITION = (
    "Per production file: share of non-test functions that have at least one "
    "CALLS edge from a function with is_test=true. Counts any callee, not only "
    "Phase-10 is_entry_point functions — closer to 'tests touch this file' when "
    "many symbols are not scored as entry points."
)


def _parse_init_type_annotations(signature: str) -> dict[str, str]:
    """Extract ``param_name → type_annotation`` from a raw ``__init__`` signature.

    Parses patterns like ``cfg: dict``, ``broker: ITraderBroker``,
    ``strategies: list | None = None``.  Returns an empty dict on any parse
    failure — callers must treat the result as best-effort only.

    INVARIANT: Pure function — no I/O, no side effects, never raises.
    """
    result: dict[str, str] = {}
    # Strip the leading "def __init__(..." wrapper to get the param list
    # Handle both single-line and multi-line signatures.
    m = re.search(r"\(\s*(.*?)\)\s*(?:->.*)?$", signature, re.DOTALL)
    if not m:
        return result
    params_str = m.group(1)
    # Split on commas that are NOT inside brackets (simple bracket-depth tracking)
    depth = 0
    current: list[str] = []
    segments: list[str] = []
    for ch in params_str:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            segments.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        segments.append("".join(current).strip())

    for seg in segments:
        seg = seg.strip()
        if not seg or seg in ("self", "cls", "*", "/", "**kwargs", "*args"):
            continue
        # Strip default: "broker: ITraderBroker = None" → "broker: ITraderBroker"
        if "=" in seg:
            seg = seg.split("=")[0].strip()
        if ":" in seg:
            name, _, ann = seg.partition(":")
            result[name.strip().lstrip("*")] = ann.strip()
        else:
            result[seg.lstrip("*")] = ""
    return result


class GraphStoreAnalytics(GraphStoreBase):
    def get_callers(self, function_id: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (caller:Function)-[e:CALLS]->(f:Function {id: $id})
            RETURN caller.id, caller.qualified_name, caller.file_path, e.confidence, e.reason
            """,
            {"id": function_id}
        )
        return [
            {"id": r[0], "qualified_name": r[1], "file_path": r[2],
             "confidence": r[3], "reason": r[4]}
            for r in rows
        ]

    def get_interface_callers(self, function_id: str) -> list[dict]:
        """Find callers of interface/base-class methods that correspond to this
        concrete method, resolved through EXTENDS or IMPLEMENTS edges.

        This is used to surface callers that depend on an interface type
        (e.g. ``IBroker.submit_order``) when inspecting a concrete
        implementation (e.g. ``LiveBroker.submit_order``).  A slight
        confidence penalty (×0.9) is applied to signal the indirect
        resolution.

        Returns an empty list when the function is not part of an inheritance
        hierarchy or has no interface callers.

        Strategy
        --------
        1. Find the concrete function's name and its owning class (via
           qualified_name prefix).
        2. Walk up the class hierarchy through EXTENDS / IMPLEMENTS edges to
           find base classes.
        3. Find functions on those base classes whose bare name matches the
           concrete function's name.
        4. Return the callers of those base-class functions.
        """
        # Step 1: get function name and its class from qualified_name
        name_rows = self.query(
            "MATCH (f:Function {id: $id}) RETURN f.name, f.qualified_name",
            {"id": function_id}
        )
        if not name_rows:
            return []
        func_name: str = name_rows[0][0]
        qualified: str = name_rows[0][1] or ""

        # Derive expected class name (e.g. "LiveBroker.submit_order" → "LiveBroker")
        class_name = qualified.split(".")[0] if "." in qualified else ""
        if not class_name:
            return []

        # Step 2: find all base class names through EXTENDS/IMPLEMENTS
        base_rows = self.query(
            """
            MATCH (sub:Class {name: $cls})-[:EXTENDS|IMPLEMENTS*1..3]->(base:Class)
            RETURN base.name
            """,
            {"cls": class_name}
        )
        if not base_rows:
            return []
        base_names = [r[0] for r in base_rows if r[0]]

        # Step 3: find base-class functions with the same bare name
        # (qualified_name = "BaseName.func_name")
        seen: set[str] = set()
        result: list[dict] = []

        for base_name in base_names:
            base_fn_qname = f"{base_name}.{func_name}"
            caller_rows = self.query(
                """
                MATCH (base_fn:Function {qualified_name: $qname})
                MATCH (caller:Function)-[e:CALLS]->(base_fn)
                RETURN caller.id, caller.qualified_name, caller.file_path,
                       e.confidence, base_fn.qualified_name
                """,
                {"qname": base_fn_qname}
            )
            for r in caller_rows:
                caller_id = r[0]
                if caller_id in seen:
                    continue
                seen.add(caller_id)
                result.append({
                    "id": caller_id,
                    "qualified_name": r[1],
                    "file_path": r[2],
                    # Slight confidence penalty — caller targets the interface, not this impl
                    "confidence": round((r[3] or 1.0) * 0.9, 4),
                    "reason": f"via_interface:{r[4]}",
                })

        return result

    def get_callees(self, function_id: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (f:Function {id: $id})-[e:CALLS]->(callee:Function)
            RETURN callee.id, callee.qualified_name, callee.file_path, e.confidence, e.reason
            """,
            {"id": function_id}
        )
        return [
            {"id": r[0], "qualified_name": r[1], "file_path": r[2],
             "confidence": r[3], "reason": r[4]}
            for r in rows
        ]

    def get_importers(self, file_path: str) -> list[str]:
        """Return paths of all files that import the given file."""
        from repograph.core.models import NodeID
        file_id = NodeID.make_file_id(file_path)
        rows = self.query(
            "MATCH (importer:File)-[:IMPORTS]->(f:File {id: $id}) RETURN importer.path",
            {"id": file_id}
        )
        return [r[0] for r in rows]

    def get_bulk_importers(self, file_paths: list[str]) -> list[str]:
        """Return paths of all files that import any of the given files (single query).

        Replaces N calls to :meth:`get_importers` with one bulk ``IN`` query.
        """
        if not file_paths:
            return []
        rows = self.query(
            "MATCH (importer:File)-[:IMPORTS]->(f:File) WHERE f.path IN $paths RETURN DISTINCT importer.path",
            {"paths": file_paths},
        )
        return [r[0] for r in rows if r[0]]

    def get_functions_by_layer(self, layer: str) -> list[dict]:
        """Return all Function nodes with the given ``layer`` value (schema v1.6)."""
        try:
            rows = self.query(
                "MATCH (f:Function) WHERE f.layer = $layer "
                "RETURN f.id, f.qualified_name, f.file_path, f.layer, f.role, "
                "f.http_method, f.route_path",
                {"layer": layer},
            )
        except Exception:
            return []
        return [
            {
                "id": r[0], "qualified_name": r[1], "file_path": r[2],
                "layer": r[3], "role": r[4], "http_method": r[5], "route_path": r[6],
            }
            for r in rows
        ]

    def get_http_endpoints(self) -> list[dict]:
        """Return all Function nodes that are HTTP endpoints (non-empty http_method, schema v1.6)."""
        try:
            rows = self.query(
                "MATCH (f:Function) WHERE f.http_method <> '' AND f.http_method IS NOT NULL "
                "RETURN f.id, f.qualified_name, f.file_path, f.http_method, f.route_path, f.layer"
            )
        except Exception:
            return []
        return [
            {
                "id": r[0], "qualified_name": r[1], "file_path": r[2],
                "http_method": r[3], "route_path": r[4], "layer": r[5],
            }
            for r in rows
        ]

    def get_all_functions(self) -> list[dict]:
        rows = self.query(
            """
            MATCH (f:Function)
            RETURN f.id, f.name, f.qualified_name, f.file_path,
                   f.line_start, f.line_end, f.is_entry_point, f.entry_score,
                   f.is_dead, f.decorators, f.param_names, f.signature,
                   f.is_method, f.is_closure_returned, f.is_script_global,
                   f.is_module_caller, f.is_test, f.dead_code_tier, f.dead_code_reason,
                   f.source_hash, f.runtime_observed, f.runtime_observed_for_hash,
                   f.runtime_observed_calls, f.runtime_observed_at
            """
        )
        return [
            {
                "id": r[0], "name": r[1], "qualified_name": r[2],
                "file_path": r[3], "line_start": r[4], "line_end": r[5],
                "is_entry_point": r[6], "entry_score": r[7], "is_dead": r[8],
                "decorators": json.loads(r[9]) if r[9] else [],
                "param_names": json.loads(r[10]) if r[10] else [],
                "signature": r[11],
                "is_method": r[12],
                "is_closure_returned": r[13] or False,
                "is_script_global": r[14] or False,
                "is_module_caller": r[15] or False,
                "is_test": r[16] if r[16] is not None else False,
                "dead_code_tier": r[17] or "",
                "dead_code_reason": r[18] or "",
                "source_hash": r[19] or "",
                "runtime_observed": bool(r[20]) if r[20] is not None else False,
                "runtime_observed_for_hash": r[21] or "",
                "runtime_observed_calls": int(r[22] or 0),
                "runtime_observed_at": r[23] or "",
            }
            for r in rows
        ]

    def get_all_call_edges(self) -> list[dict]:
        if not self._calls_extra_lines:
            rows = self.query(
                """
                MATCH (a:Function)-[e:CALLS]->(b:Function)
                RETURN a.id, b.id, e.confidence, e.call_site_line, e.reason
                """
            )
            return [
                {"from": r[0], "to": r[1], "confidence": r[2],
                 "line": r[3], "lines": [r[3]], "reason": r[4]}
                for r in rows
            ]
        rows = self.query(
            """
            MATCH (a:Function)-[e:CALLS]->(b:Function)
            RETURN a.id, b.id, e.confidence, e.call_site_line, e.reason, e.extra_site_lines
            """
        )
        out: list[dict] = []
        for r in rows:
            primary = r[3]
            lines = [primary]
            raw = r[5]
            if raw:
                try:
                    extra = json.loads(raw)
                    if isinstance(extra, list):
                        merged = {int(primary), *(
                            int(x) for x in extra
                            if x is not None and str(x).lstrip("-").isdigit()
                        )}
                        lines = sorted(merged)
                except (json.JSONDecodeError, TypeError, ValueError):
                    lines = [primary]
            out.append({
                "from": r[0], "to": r[1], "confidence": r[2],
                "line": lines[0] if lines else primary,
                "lines": lines,
                "reason": r[4],
            })
        return out

    def get_pathway(self, name: str) -> dict | None:
        """Resolve a pathway by internal name, display name, or pathway id.

        Lookup order:
        1. Exact match on ``name`` (internal slug, e.g. ``calculator_compute_flow``)
        2. Exact match on ``display_name`` (e.g. ``Calculator Compute Flow``)
        3. Exact match on ``id``  (e.g. ``pathway:function:src/…``)
        4. Case-insensitive partial match on ``name`` or ``display_name``
        """
        _COLS = (
            "p.id, p.name, p.display_name, p.description, p.context_doc, "
            "p.confidence, p.step_count, p.entry_function, p.source, p.importance_score"
        )

        def _row_to_dict(r: list) -> dict:
            return {
                "id": r[0], "name": r[1], "display_name": r[2],
                "description": r[3], "context_doc": r[4],
                "confidence": r[5], "step_count": r[6], "entry_function": r[7],
                "source": r[8], "importance_score": r[9] or 0.0,
            }

        # 1. Exact name match
        rows = self.query(
            f"MATCH (p:Pathway {{name: $v}}) RETURN {_COLS}", {"v": name}
        )
        if rows:
            return _row_to_dict(rows[0])

        # 2. Exact display_name match
        rows = self.query(
            f"MATCH (p:Pathway) WHERE p.display_name = $v RETURN {_COLS}", {"v": name}
        )
        if rows:
            return _row_to_dict(rows[0])

        # 3. Exact id match
        rows = self.query(
            f"MATCH (p:Pathway) WHERE p.id = $v RETURN {_COLS}", {"v": name}
        )
        if rows:
            return _row_to_dict(rows[0])

        # 4. Case-insensitive partial match — pick the closest by length
        try:
            all_rows = self.query(
                f"MATCH (p:Pathway) RETURN {_COLS}"
            )
        except Exception:
            return None
        needle = name.lower()
        candidates = [
            r for r in all_rows
            if needle in (r[1] or "").lower() or needle in (r[2] or "").lower()
        ]
        if not candidates:
            return None
        # Prefer the shortest match (closest to what the user typed)
        candidates.sort(key=lambda r: len(r[1] or ""))
        return _row_to_dict(candidates[0])

    def get_all_pathways(self) -> list[dict]:
        rows = self.query(
            """
            MATCH (p:Pathway)
            RETURN p.id, p.name, p.display_name, p.description,
                   p.confidence, p.step_count, p.source, p.entry_function,
                   p.importance_score
            """
        )
        return [
            {
                "id": r[0], "name": r[1], "display_name": r[2],
                "description": r[3], "confidence": r[4],
                "step_count": r[5], "source": r[6], "entry_function": r[7],
                "importance_score": r[8] or 0.0,
            }
            for r in rows
        ]

    # Maps graph node labels to their human-readable plural stat key names.
    _STAT_LABEL_MAP: dict[str, str] = {
        "File": "files",
        "Class": "classes",
        "Variable": "variables",
        "Import": "imports",
        "Pathway": "pathways",
        "Community": "communities",
    }

    def get_stats(self) -> dict[str, int]:
        counts = {}
        for table, key in self._STAT_LABEL_MAP.items():
            try:
                rows = self.query(f"MATCH (n:{table}) RETURN count(n)")
                counts[key] = rows[0][0] if rows else 0
            except Exception:
                counts[key] = 0
        # Exclude __module__ sentinels from the function count — they are
        # internal bookkeeping nodes, not real callable symbols.
        try:
            rows = self.query(
                "MATCH (f:Function) "
                "WHERE f.is_module_caller IS NULL OR f.is_module_caller = false "
                "RETURN count(f)"
            )
            counts["functions"] = rows[0][0] if rows else 0
        except Exception:
            counts["functions"] = 0
        return counts

    # Tier ordering for min_tier filtering
    _DEAD_TIER_ORDER = {"definitely_dead": 0, "probably_dead": 1, "possibly_dead": 2}

    def get_dead_functions(self, min_tier: str = "probably_dead") -> list[dict]:
        """Return dead functions at or above the specified confidence tier.

        Parameters
        ----------
        min_tier:
            Minimum tier to include.  One of:
            - ``"definitely_dead"`` — zero callers anywhere (highest confidence)
            - ``"probably_dead"``   — only test/fuzzy callers (default)
            - ``"possibly_dead"``   — exported but uncalled (lowest confidence)

        Note: functions with a NULL tier (legacy data before tiering was
        introduced) are returned unless min_tier is ``"definitely_dead"``.
        """
        allowed_tiers = [
            t for t, rank in self._DEAD_TIER_ORDER.items()
            if rank <= self._DEAD_TIER_ORDER.get(min_tier, 1)
        ]
        rows = self.query(
            """
            MATCH (f:Function {is_dead: true})
            WHERE f.is_module_caller IS NULL OR f.is_module_caller = false
            RETURN f.id, f.qualified_name, f.file_path, f.line_start,
                   f.dead_code_tier, f.dead_code_reason, f.dead_context
            """
        )
        from repograph.utils.path_classifier import classify_path

        results = []
        for r in rows:
            tier = r[4] or "probably_dead"
            if tier in allowed_tiers:
                fp = r[2] or ""
                results.append({
                    "id": r[0], "qualified_name": r[1], "file_path": fp,
                    "line_start": r[3], "dead_code_tier": tier,
                    "dead_code_reason": r[5] or "",
                    "dead_context": r[6] or "",
                    "is_non_production": classify_path(fp) != "production",
                })
        return results

    def get_entry_points(self, limit: int = 20) -> list[dict]:
        """Return top-scored entry-point functions.

        The query uses ``coalesce`` on v1.4 columns (entry_score_base etc.)
        so it degrades gracefully on databases that predate the migration —
        they will show 0.0 for the breakdown fields rather than crashing.
        """
        rows = self.query(
            """
            MATCH (f:Function {is_entry_point: true})
            WHERE coalesce(f.is_module_caller, false) = false
            RETURN f.id, f.qualified_name, f.file_path, f.entry_score, f.signature,
                   coalesce(f.entry_score_base, 0.0),
                   coalesce(f.entry_score_multipliers, ''),
                   coalesce(f.entry_callee_count, 0),
                   coalesce(f.entry_caller_count, 0)
            ORDER BY f.entry_score DESC
            LIMIT $limit
            """,
            {"limit": limit}
        )
        return [
            {
                "id": r[0], "qualified_name": r[1], "file_path": r[2],
                "entry_score": r[3], "signature": r[4],
                "entry_score_base": r[5],
                "entry_score_multipliers": r[6] or "",
                "entry_callee_count": r[7],
                "entry_caller_count": r[8],
            }
            for r in rows
        ]

    def search_functions_by_name(self, name: str, limit: int = 10) -> list[dict]:
        """Simple name-based search (substring, case-insensitive via LOWER)."""
        rows = self.query(
            """
            MATCH (f:Function)
            WHERE lower(f.name) CONTAINS lower($name)
               OR lower(f.qualified_name) CONTAINS lower($name)
            RETURN f.id, f.qualified_name, f.file_path, f.signature
            LIMIT $limit
            """,
            {"name": name, "limit": limit}
        )
        return [
            {"id": r[0], "qualified_name": r[1], "file_path": r[2], "signature": r[3]}
            for r in rows
        ]

    def get_pathway_by_id(self, pathway_id: str) -> dict | None:
        rows = self.query(
            """
            MATCH (p:Pathway {id: $id})
            RETURN p.id, p.name, p.display_name, p.description, p.context_doc,
                   p.confidence, p.step_count, p.entry_function, p.source,
                   p.variable_threads, p.entry_file
            """,
            {"id": pathway_id}
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0], "name": r[1], "display_name": r[2], "description": r[3],
            "context_doc": r[4], "confidence": r[5], "step_count": r[6],
            "entry_function": r[7], "source": r[8], "variable_threads": r[9],
            "entry_file": r[10],
        }

    def get_pathway_steps(self, pathway_id: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (f:Function)-[r:STEP_IN_PATHWAY]->(p:Pathway {id: $pid})
            RETURN f.id, f.name, f.qualified_name, f.file_path,
                   f.line_start, f.line_end, f.decorators,
                   r.step_order, r.role
            ORDER BY r.step_order
            """,
            {"pid": pathway_id}
        )
        return [
            {
                "id": r[0], "name": r[1], "function_name": r[1],
                "qualified_name": r[2], "file_path": r[3],
                "line_start": r[4], "line_end": r[5],
                "decorators": json.loads(r[6]) if r[6] else [],
                "step_order": r[7], "order": r[7], "role": r[8],
            }
            for r in rows
        ]

    def get_variables_for_function(self, function_id: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (v:Variable {function_id: $fid})
            RETURN v.id, v.name, v.inferred_type, v.is_parameter, v.is_return, v.line_number
            """,
            {"fid": function_id}
        )
        return [
            {"id": r[0], "name": r[1], "inferred_type": r[2],
             "is_parameter": r[3], "is_return": r[4], "line_number": r[5]}
            for r in rows
        ]

    def get_flows_into_edges(self) -> list[dict]:
        rows = self.query(
            """
            MATCH (a:Variable)-[r:FLOWS_INTO]->(b:Variable)
            RETURN a.id, b.id, r.via_argument, r.confidence
            """
        )
        return [{"from": r[0], "to": r[1], "via_argument": r[2], "confidence": r[3]}
                for r in rows]

    def get_function_by_id(self, function_id: str) -> dict | None:
        rows = self.query(
            """
            MATCH (f:Function {id: $id})
            RETURN f.id, f.name, f.qualified_name, f.file_path,
                   f.line_start, f.line_end, f.signature, f.docstring,
                   f.is_entry_point, f.is_dead, f.decorators, f.param_names,
                   f.return_type, f.entry_score, f.community_id, f.is_test
            """,
            {"id": function_id}
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0], "name": r[1], "qualified_name": r[2], "file_path": r[3],
            "line_start": r[4], "line_end": r[5], "signature": r[6], "docstring": r[7],
            "is_entry_point": r[8], "is_dead": r[9],
            "decorators": json.loads(r[10]) if r[10] else [],
            "param_names": json.loads(r[11]) if r[11] else [],
            "return_type": r[12], "entry_score": r[13], "community_id": r[14],
            "is_test": r[15] if r[15] is not None else False,
        }

    def get_test_coverage_map(self) -> list[dict]:
        """Return per-production-file *entry-point test reachability* statistics.

        For each production file that contains at least one entry point
        (``is_entry_point``), counts how many of those entry-point functions
        have **at least one** incoming ``CALLS`` edge from a function whose
        ``is_test`` flag is true (see ``ENTRY_POINT_TEST_COVERAGE_DEFINITION``).

        Uses ``is_entry_point`` from Phase 10 and ``is_test`` on ``Function`` nodes.
        Test callers are identified by ``caller.is_test``, not by path heuristics.

        Returns
        -------
        list of dicts sorted by coverage_pct ascending (least covered first):
            file_path, entry_point_count, tested_entry_points,
            coverage_pct, test_files (distinct test file paths with a CALLS
            edge to at least one tested entry point in this file).
        """
        try:
            # Fetch all production entry-point functions with their callers
            rows = self.query(
                """
                MATCH (f:Function {is_entry_point: true})
                WHERE coalesce(f.is_test, false) = false
                RETURN f.id, f.file_path, f.qualified_name
                """
            )
        except Exception:
            return []

        if not rows:
            return []

        # Build per-file aggregation
        from collections import defaultdict
        file_eps: dict[str, list[str]] = defaultdict(list)
        fn_id_to_file: dict[str, str] = {}
        for fn_id, fp, qname in rows:
            file_eps[fp].append(fn_id)
            fn_id_to_file[fn_id] = fp

        # Find which entry-point functions have test callers
        tested_fns: set[str] = set()
        test_files_for_fn: dict[str, set[str]] = defaultdict(set)
        try:
            caller_rows = self.query(
                """
                MATCH (caller:Function)-[:CALLS]->(ep:Function {is_entry_point: true})
                WHERE coalesce(caller.is_test, false) = true
                  AND coalesce(ep.is_test, false) = false
                RETURN ep.id, caller.file_path
                """
            )
            for ep_id, caller_fp in caller_rows:
                tested_fns.add(ep_id)
                test_files_for_fn[ep_id].add(caller_fp)
        except Exception:
            pass

        results: list[dict] = []
        for fp, ep_ids in file_eps.items():
            total = len(ep_ids)
            tested = sum(1 for fid in ep_ids if fid in tested_fns)
            test_files: set[str] = set()
            for fid in ep_ids:
                test_files |= test_files_for_fn.get(fid, set())
            pct = round(tested / total * 100, 1) if total > 0 else 0.0
            results.append({
                "file_path": fp,
                "entry_point_count": total,
                "tested_entry_points": tested,
                "coverage_pct": pct,
                "test_files": sorted(test_files),
            })

        return sorted(results, key=lambda x: x["coverage_pct"])

    def get_any_call_test_coverage_map(self) -> list[dict]:
        """Return per-file *any-function* test reachability (non-EP callees included).

        Unlike :meth:`get_test_coverage_map`, every production ``Function`` in a
        file counts toward the denominator, not only ``is_entry_point`` nodes.
        """
        try:
            rows = self.query(
                """
                MATCH (f:Function)
                WHERE coalesce(f.is_test, false) = false
                RETURN f.id, f.file_path
                """
            )
        except Exception:
            return []

        if not rows:
            return []

        from collections import defaultdict

        by_file: dict[str, list[str]] = defaultdict(list)
        for fn_id, fp in rows:
            if not fp:
                continue
            by_file[str(fp)].append(str(fn_id))

        tested: set[str] = set()
        test_files_by_fn: dict[str, set[str]] = defaultdict(set)
        try:
            caller_rows = self.query(
                """
                MATCH (caller:Function)-[:CALLS]->(callee:Function)
                WHERE coalesce(caller.is_test, false) = true
                  AND coalesce(callee.is_test, false) = false
                RETURN callee.id, caller.file_path
                """
            )
            for cid, caller_fp in caller_rows:
                cid_s = str(cid)
                tested.add(cid_s)
                if caller_fp:
                    test_files_by_fn[cid_s].add(str(caller_fp))
        except Exception:
            pass

        results: list[dict] = []
        for fp, ids in by_file.items():
            total = len(ids)
            n_tested = sum(1 for i in ids if i in tested)
            tfiles: set[str] = set()
            for i in ids:
                if i in tested:
                    tfiles |= test_files_by_fn.get(i, set())
            pct = round(n_tested / total * 100, 1) if total > 0 else 0.0
            results.append({
                "file_path": fp,
                "function_count": total,
                "tested_functions": n_tested,
                "coverage_pct": pct,
                "test_files": sorted(tfiles),
            })

        return sorted(results, key=lambda x: x["coverage_pct"])

    def get_event_topology(self) -> list[dict]:
        """Return ``meta/event_topology.json`` records (IMP-01)."""
        import os
        path = os.path.join(os.path.dirname(self.db_path), "meta", "event_topology.json")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []

    def get_async_tasks(self) -> list[dict]:
        """Return ``meta/async_tasks.json`` records (IMP-04)."""
        import os
        path = os.path.join(os.path.dirname(self.db_path), "meta", "async_tasks.json")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []

    def get_constructor_deps(self, class_name: str, depth: int = 2) -> dict:
        """Return ``__init__`` parameter names and type annotations for a class (IMP-07).

        Uses the HAS_METHOD edge (written by Phase 3 after the p03_parse fix)
        to find the ``__init__`` function for the named class, then extracts
        parameter names and any type annotations from the stored signature.

        Args:
            class_name: Unqualified class name (e.g. ``"ChampionBot"``).
            depth: Reserved for future recursive dep-tree expansion.

        Returns:
            Dict with keys:
            - ``class``: the queried class name
            - ``parameters``: list of ``{name, type}`` dicts (type may be ``""``
              when no annotation is present)
            - ``signature``: raw ``__init__`` signature string
            - ``error``: present only when the class is not found
        """
        _ = depth
        rows = self.query(
            "MATCH (c:Class) WHERE c.name = $n RETURN c.id LIMIT 1",
            {"n": class_name},
        )
        if not rows:
            return {"class": class_name, "parameters": [], "signature": "",
                    "error": "class not found"}
        cid = rows[0][0]
        rows2 = self.query(
            """
            MATCH (c:Class {id: $cid})-[:HAS_METHOD]->(f:Function)
            WHERE f.name = '__init__'
            RETURN f.param_names, f.signature
            LIMIT 1
            """,
            {"cid": cid},
        )
        if not rows2:
            return {"class": class_name, "parameters": [], "signature": ""}

        raw_params = json.loads(rows2[0][0]) if rows2[0][0] else []
        signature = rows2[0][1] or ""

        # Strip self/cls
        if raw_params and raw_params[0] in ("self", "cls"):
            raw_params = list(raw_params[1:])

        # Extract type annotations from signature text.
        # Signature looks like:
        #   def __init__(self, cfg: dict, broker: ITraderBroker, ...) -> None
        # We parse each "name: Type" pair — best-effort, never raises.
        type_map: dict[str, str] = {}
        try:
            type_map = _parse_init_type_annotations(signature)
        except Exception:
            pass

        parameters = [
            {"name": p, "type": type_map.get(p, "")}
            for p in raw_params
        ]
        return {
            "class": class_name,
            "parameters": parameters,
            "signature": signature,
        }
