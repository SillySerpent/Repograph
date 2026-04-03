"""Impact and dependency RepoGraph service methods."""
from __future__ import annotations

from repograph.services.service_base import RepoGraphServiceProtocol, _observed_service_call
from repograph.services.symbol_resolution import resolve_identifier


class ServiceImpactMixin:
    """Blast-radius, dependency, and diff-impact surfaces."""

    @_observed_service_call(
        "service_impact",
        metadata_fn=lambda self, symbol, depth=3: {
            "symbol_len": len(symbol or ""),
            "depth": int(depth),
        },
    )
    def impact(self: RepoGraphServiceProtocol, symbol: str, depth: int = 3) -> dict:
        """Return approximate static blast-radius callers for a symbol."""
        from repograph.diagnostics.impact_warnings import build_impact_warnings

        store = self._get_store()
        resolution = resolve_identifier(store, symbol, limit=5)
        if resolution["kind"] == "not_found":
            return {
                "error": f"Symbol not found: {symbol}",
                "direct_callers": [],
                "transitive_callers": [],
                "files_affected": [],
                "warnings": ["symbol_not_found"],
            }
        if resolution["kind"] == "file":
            return {
                "error": f"Expected a symbol, got a file path: {symbol}",
                "direct_callers": [],
                "transitive_callers": [],
                "files_affected": [],
                "warnings": ["file_path_provided"],
            }
        if resolution["kind"] == "ambiguous":
            return {
                "ambiguous": True,
                "strategy": resolution["strategy"],
                "matches": resolution["matches"],
                "warnings": build_impact_warnings(
                    direct_callers=[],
                    has_duplicate_name_matches=True,
                ),
            }

        match = resolution["match"]
        function_id = match["id"]
        direct = store.get_callers(function_id)
        via_interface = False

        if not direct:
            interface_callers = store.get_interface_callers(function_id)
            if interface_callers:
                direct = interface_callers
                via_interface = True

        seen: set[str] = {function_id} | {caller["id"] for caller in direct}
        frontier = list(seen - {function_id})
        transitive: list[dict] = list(direct)

        for _ in range(depth - 1):
            next_frontier: list[str] = []
            for frontier_id in frontier:
                for caller in store.get_callers(frontier_id):
                    if caller["id"] not in seen:
                        seen.add(caller["id"])
                        transitive.append(caller)
                        next_frontier.append(caller["id"])
            frontier = next_frontier
            if not frontier:
                break

        warnings = build_impact_warnings(direct_callers=direct)
        if via_interface:
            warnings.append("callers_resolved_via_interface")

        return {
            "symbol": match["qualified_name"],
            "file": match["file_path"],
            "resolution_strategy": resolution["strategy"],
            "direct_callers": direct,
            "transitive_callers": transitive,
            "files_affected": sorted({caller["file_path"] for caller in transitive}),
            "warnings": warnings,
        }

    @_observed_service_call(
        "service_dependents",
        metadata_fn=lambda self, symbol, depth=3: {
            "symbol_len": len(symbol or ""),
            "depth": int(depth),
        },
    )
    def dependents(self: RepoGraphServiceProtocol, symbol: str, depth: int = 3) -> dict:
        """Return direct and transitive callers grouped by depth."""
        store = self._get_store()
        resolution = resolve_identifier(store, symbol, limit=5)
        if resolution["kind"] == "not_found":
            return {"error": f"Symbol '{symbol}' not found"}
        if resolution["kind"] == "file":
            return {"error": f"Expected a symbol, got a file path: {symbol}"}
        if resolution["kind"] == "ambiguous":
            return {
                "ambiguous": True,
                "strategy": resolution["strategy"],
                "matches": resolution["matches"],
            }

        function_id = resolution["match"]["id"]
        levels: dict[int, list[dict]] = {}
        visited: set[str] = {function_id}
        queue = [(function_id, 0)]

        while queue:
            current_id, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue
            for caller in store.get_callers(current_id):
                if caller["id"] in visited:
                    continue
                visited.add(caller["id"])
                levels.setdefault(current_depth + 1, []).append(caller)
                queue.append((caller["id"], current_depth + 1))

        return {
            "symbol": resolution["match"]["qualified_name"],
            "resolution_strategy": resolution["strategy"],
            "dependents_by_depth": levels,
        }

    @_observed_service_call(
        "service_dependencies",
        metadata_fn=lambda self, symbol, depth=3: {
            "symbol_len": len(symbol or ""),
            "depth": int(depth),
        },
    )
    def dependencies(self: RepoGraphServiceProtocol, symbol: str, depth: int = 3) -> dict:
        """Return transitive callees grouped by depth."""
        store = self._get_store()
        resolution = resolve_identifier(store, symbol, limit=5)
        if resolution["kind"] == "not_found":
            return {"error": f"Symbol '{symbol}' not found"}
        if resolution["kind"] == "file":
            return {"error": f"Expected a symbol, got a file path: {symbol}"}
        if resolution["kind"] == "ambiguous":
            return {
                "ambiguous": True,
                "strategy": resolution["strategy"],
                "matches": resolution["matches"],
            }

        function_id = resolution["match"]["id"]
        levels: dict[int, list[dict]] = {}
        visited: set[str] = {function_id}
        queue = [(function_id, 0)]

        while queue:
            current_id, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue
            for callee in store.get_callees(current_id):
                if callee["id"] in visited:
                    continue
                visited.add(callee["id"])
                levels.setdefault(current_depth + 1, []).append(callee)
                queue.append((callee["id"], current_depth + 1))

        return {
            "symbol": resolution["match"]["qualified_name"],
            "resolution_strategy": resolution["strategy"],
            "dependencies_by_depth": levels,
        }

    def compute_diff_impact(
        self: RepoGraphServiceProtocol,
        changed_paths: list[str],
        max_hops: int = 5,
    ) -> list[dict]:
        """Return a ranked list of functions impacted by changed files."""
        from repograph.services.impact_analysis import ImpactedFunction, compute_impact

        results: list[ImpactedFunction] = compute_impact(
            self._get_store(),
            changed_paths=changed_paths,
            max_hops=max_hops,
        )
        return [
            {
                "fn_id": result.fn_id,
                "qualified_name": result.qualified_name,
                "file_path": result.file_path,
                "hop": result.hop,
                "impact_score": result.impact_score,
                "via_http": result.via_http,
                "edge_path": result.edge_path,
            }
            for result in results
        ]
