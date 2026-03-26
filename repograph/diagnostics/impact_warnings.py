"""Heuristic warning tags for :meth:`~repograph.services.repo_graph_service.RepoGraphService.impact`."""
from __future__ import annotations


def build_impact_warnings(
    *,
    direct_callers: list[dict],
    has_duplicate_name_matches: bool = False,
) -> list[str]:
    """Short machine-readable tags for consumers (UI, MCP)."""
    warnings: list[str] = ["static_call_graph_only"]
    if has_duplicate_name_matches:
        warnings.append("ambiguous_symbol_multiple_matches_narrow_the_query")
        return warnings
    if not direct_callers:
        warnings.append("no_direct_static_callers_may_miss_dynamic_or_typed_edges")
    return warnings
