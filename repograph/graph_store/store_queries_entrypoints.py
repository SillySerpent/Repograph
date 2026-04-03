"""GraphStore entry-point, dead-code, stats, and test-coverage queries."""
from __future__ import annotations

from repograph.graph_store.store_base import GraphStoreBase

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


class GraphStoreEntrypointQueries(GraphStoreBase):
    _STAT_LABEL_MAP: dict[str, str] = {
        "File": "files",
        "Class": "classes",
        "Variable": "variables",
        "Import": "imports",
        "Pathway": "pathways",
        "Community": "communities",
    }

    _DEAD_TIER_ORDER = {
        "definitely_dead": 0,
        "probably_dead": 1,
        "possibly_dead": 2,
    }

    def get_stats(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table, key in self._STAT_LABEL_MAP.items():
            try:
                rows = self.query(f"MATCH (n:{table}) RETURN count(n)")
                counts[key] = rows[0][0] if rows else 0
            except Exception:
                counts[key] = 0
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

    def get_dead_functions(self, min_tier: str = "probably_dead") -> list[dict]:
        allowed_tiers = [
            tier
            for tier, rank in self._DEAD_TIER_ORDER.items()
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

        results: list[dict] = []
        for row in rows:
            tier = row[4] or "probably_dead"
            if tier in allowed_tiers:
                file_path = row[2] or ""
                results.append(
                    {
                        "id": row[0],
                        "qualified_name": row[1],
                        "file_path": file_path,
                        "line_start": row[3],
                        "dead_code_tier": tier,
                        "dead_code_reason": row[5] or "",
                        "dead_context": row[6] or "",
                        "is_non_production": classify_path(file_path) != "production",
                    }
                )
        return results

    def get_entry_points(self, limit: int = 20) -> list[dict]:
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
            {"limit": limit},
        )
        return [
            {
                "id": row[0],
                "qualified_name": row[1],
                "file_path": row[2],
                "entry_score": row[3],
                "signature": row[4],
                "entry_score_base": row[5],
                "entry_score_multipliers": row[6] or "",
                "entry_callee_count": row[7],
                "entry_caller_count": row[8],
            }
            for row in rows
        ]

    def get_test_coverage_map(self) -> list[dict]:
        """Return per-production-file entry-point test reachability statistics."""
        try:
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

        from collections import defaultdict

        file_eps: dict[str, list[str]] = defaultdict(list)
        for fn_id, file_path, _qualified_name in rows:
            file_eps[file_path].append(fn_id)

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
        for file_path, ep_ids in file_eps.items():
            total = len(ep_ids)
            tested = sum(1 for fn_id in ep_ids if fn_id in tested_fns)
            test_files: set[str] = set()
            for fn_id in ep_ids:
                test_files |= test_files_for_fn.get(fn_id, set())
            pct = round(tested / total * 100, 1) if total > 0 else 0.0
            results.append(
                {
                    "file_path": file_path,
                    "entry_point_count": total,
                    "tested_entry_points": tested,
                    "coverage_pct": pct,
                    "test_files": sorted(test_files),
                }
            )
        return sorted(results, key=lambda row: row["coverage_pct"])

    def get_any_call_test_coverage_map(self) -> list[dict]:
        """Return per-file any-function test reachability statistics."""
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
        for fn_id, file_path in rows:
            if not file_path:
                continue
            by_file[str(file_path)].append(str(fn_id))

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
            for callee_id, caller_fp in caller_rows:
                callee_id_s = str(callee_id)
                tested.add(callee_id_s)
                if caller_fp:
                    test_files_by_fn[callee_id_s].add(str(caller_fp))
        except Exception:
            pass

        results: list[dict] = []
        for file_path, ids in by_file.items():
            total = len(ids)
            tested_count = sum(1 for fn_id in ids if fn_id in tested)
            test_files: set[str] = set()
            for fn_id in ids:
                if fn_id in tested:
                    test_files |= test_files_by_fn.get(fn_id, set())
            pct = round(tested_count / total * 100, 1) if total > 0 else 0.0
            results.append(
                {
                    "file_path": file_path,
                    "function_count": total,
                    "tested_functions": tested_count,
                    "coverage_pct": pct,
                    "test_files": sorted(test_files),
                }
            )
        return sorted(results, key=lambda row: row["coverage_pct"])
