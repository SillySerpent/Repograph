"""Symbol, entry-point, and code-shape RepoGraph service methods."""
from __future__ import annotations

from repograph.services.service_base import (
    EntryPointLimitArg,
    RepoGraphServiceProtocol,
    _EntryPointLimitUnset,
    _ENTRY_POINT_LIMIT_UNSET,
    _entry_points_metadata,
    _observed_service_call,
)
from repograph.services.symbol_resolution import resolve_identifier
from repograph.settings import resolve_runtime_settings

_DOC_WARN_SEV_RANK = {"high": 0, "medium": 1, "low": 2}


class ServiceSymbolsMixin:
    """Node, entry-point, and code-shape surfaces."""

    @_observed_service_call(
        "service_node",
        metadata_fn=lambda self, identifier: {"identifier_len": len(identifier or "")},
    )
    def node(self: RepoGraphServiceProtocol, identifier: str) -> dict | None:
        """Return structured data for a file path or qualified symbol name."""
        store = self._get_store()
        resolution = resolve_identifier(store, identifier, limit=5)

        if resolution["kind"] == "file":
            file_data = resolution["match"]
            file_path = file_data.get("path", identifier)
            return {
                "type": "file",
                **file_data,
                "functions": store.get_functions_in_file(file_path),
                "classes": store.get_classes_in_file(file_path),
            }

        if resolution["kind"] == "function":
            match = resolution["match"]
            function_id = match["id"]
            function = store.get_function_by_id(function_id)
            if function:
                return {
                    "type": "function",
                    "resolution_strategy": resolution["strategy"],
                    **function,
                    "callers": store.get_callers(function_id),
                    "callees": store.get_callees(function_id),
                }

        if resolution["kind"] == "ambiguous":
            return {
                "type": "ambiguous",
                "strategy": resolution["strategy"],
                "matches": resolution["matches"],
            }

        return None

    @_observed_service_call("service_get_all_files")
    def get_all_files(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return all indexed files with metadata."""
        return self._get_store().get_all_files()

    @_observed_service_call(
        "service_entry_points",
        metadata_fn=_entry_points_metadata,
    )
    def entry_points(
        self: RepoGraphServiceProtocol,
        limit: EntryPointLimitArg = _ENTRY_POINT_LIMIT_UNSET,
    ) -> list[dict]:
        """Return the top scored entry points."""
        store = self._get_store()
        if isinstance(limit, _EntryPointLimitUnset):
            resolved_limit = resolve_runtime_settings(self.repo_path).entry_point_limit
        elif limit is None:
            resolved_limit = max(1, int(store.get_stats().get("functions", 0) or 1))
        else:
            resolved_limit = int(limit)
        return store.get_entry_points(limit=resolved_limit)

    @_observed_service_call(
        "service_dead_code",
        metadata_fn=lambda self, min_tier="probably_dead": {"min_tier": min_tier},
    )
    def dead_code(
        self: RepoGraphServiceProtocol,
        min_tier: str = "probably_dead",
    ) -> list[dict]:
        """Return symbols detected as unreachable, filtered by confidence tier."""
        return self._get_store().get_dead_functions(min_tier=min_tier)

    @_observed_service_call(
        "service_duplicates",
        metadata_fn=lambda self, min_severity="medium": {"min_severity": min_severity},
    )
    def duplicates(
        self: RepoGraphServiceProtocol,
        min_severity: str = "medium",
    ) -> list[dict]:
        """Return groups of symbols that appear to be duplicated across files."""
        severity_order = {"high": 0, "medium": 1, "low": 2}
        allowed = {
            severity
            for severity, rank in severity_order.items()
            if rank <= severity_order.get(min_severity, 1)
        }
        groups = self._get_store().get_all_duplicate_symbols()
        return [group for group in groups if group.get("severity") in allowed]

    @_observed_service_call(
        "service_doc_warnings",
        metadata_fn=lambda self, severity=None, min_severity=None: {
            "severity": severity or "",
            "min_severity": min_severity or "",
        },
    )
    def doc_warnings(
        self: RepoGraphServiceProtocol,
        severity: str | None = None,
        *,
        min_severity: str | None = None,
    ) -> list[dict]:
        """Return Markdown backtick cross-checks against the symbol graph."""
        minimum = (
            min_severity
            if min_severity is not None
            else (severity if severity is not None else "high")
        )
        cap = _DOC_WARN_SEV_RANK.get(minimum, 0)
        rows = self._get_store().get_all_doc_warnings(severity=None)
        return [
            row
            for row in rows
            if _DOC_WARN_SEV_RANK.get(row.get("severity"), 99) <= cap
        ]

    @_observed_service_call(
        "service_trace_variable",
        metadata_fn=lambda self, variable_name: {"variable_name_len": len(variable_name or "")},
    )
    def trace_variable(
        self: RepoGraphServiceProtocol,
        variable_name: str,
    ) -> dict:
        """Trace occurrences and FLOWS_INTO edges for a variable name."""
        store = self._get_store()
        rows = store.query(
            """
            MATCH (v:Variable {name: $name})
            RETURN v.id, v.function_id, v.file_path, v.line_number,
                   v.inferred_type, v.is_parameter, v.is_return
            LIMIT 20
            """,
            {"name": variable_name},
        )
        if not rows:
            return {"error": f"Variable '{variable_name}' not found"}

        occurrences = [
            {
                "variable_id": row[0],
                "function_id": row[1],
                "file_path": row[2],
                "line_number": row[3],
                "inferred_type": row[4],
                "is_parameter": row[5],
                "is_return": row[6],
            }
            for row in rows
        ]
        variable_ids = {occurrence["variable_id"] for occurrence in occurrences}
        flows = store.get_flows_into_edges()
        relevant_flows = [
            edge
            for edge in flows
            if edge["from"] in variable_ids or edge["to"] in variable_ids
        ]
        return {
            "variable_name": variable_name,
            "occurrences": occurrences,
            "flows": relevant_flows,
        }
