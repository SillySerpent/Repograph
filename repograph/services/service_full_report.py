"""Full-report shaping helpers and service method."""
from __future__ import annotations

from repograph.graph_store.store_queries_entrypoints import (
    ANY_CALL_TEST_COVERAGE_DEFINITION,
    ENTRY_POINT_TEST_COVERAGE_DEFINITION,
)
from repograph.services.service_base import (
    EntryPointLimitArg,
    RepoGraphServiceProtocol,
    _ENTRY_POINT_LIMIT_UNSET,
    _apply_limit,
    _full_report_metadata,
    _observed_service_call,
)


def _build_report_warnings(
    *,
    health: dict,
    pathways_total: int,
    pathways_shown: int,
    communities_total: int,
    communities_shown: int,
    cfg_top: dict,
    cfg_diag: dict,
) -> list[str]:
    warnings: list[str] = []
    if health.get("sync_mode") == "incremental_traces_only":
        warnings.append(
            "Report reflects a trace-only incremental refresh; run a full sync for a full static rebuild snapshot."
        )
    dynamic_analysis = health.get("dynamic_analysis") or {}
    if dynamic_analysis.get("mode") == "existing_inputs" and dynamic_analysis.get("inputs_present"):
        warnings.append(
            "Runtime evidence in this report was reused from existing trace or coverage inputs; "
            "the last sync did not start a fresh traced runtime session."
        )
    if dynamic_analysis.get("requested") and not dynamic_analysis.get("executed"):
        reason = str(dynamic_analysis.get("skipped_reason") or "").strip() or "unspecified"
        warnings.append(
            "Dynamic analysis was requested for the last full sync but skipped "
            f"({reason}). Add sync_test_command or pytest config if you want runtime overlay."
        )
    if health.get("status") == "degraded":
        warnings.append(
            "Last sync completed with degraded health (one or more optional hooks failed)."
        )
    if pathways_total > pathways_shown:
        warnings.append(
            f"Pathways are capped in this report ({pathways_shown}/{pathways_total} shown)."
        )
    if communities_total > communities_shown:
        warnings.append(
            f"Communities are capped in this report ({communities_shown}/{communities_total} shown)."
        )
    if not cfg_top and cfg_diag.get("status"):
        warnings.append(
            "Config registry empty "
            f"({cfg_diag.get('status')}); inspect config_registry_diagnostics for scan details."
        )
    return warnings


class ServiceFullReportMixin:
    """Canonical deep-report service surface."""

    @_observed_service_call(
        "service_full_report",
        metadata_fn=_full_report_metadata,
    )
    def full_report(
        self: RepoGraphServiceProtocol,
        max_pathways: int | None = 10,
        max_dead: int | None = 20,
        entry_point_limit: EntryPointLimitArg = _ENTRY_POINT_LIMIT_UNSET,
        max_config_keys: int | None = 30,
        max_communities: int | None = 20,
    ) -> dict:
        """Return every piece of intelligence the tool can provide in one call."""
        from repograph.plugins.exporters.agent_guide.generator import _extract_repo_summary

        if not self._is_initialized():
            return {"meta": {"initialized": False, "repo_path": self.repo_path}}

        status = self.status()
        health = status.get("health", {})
        stats = {key: value for key, value in status.items() if key != "health"}

        purpose = ""
        try:
            purpose = _extract_repo_summary(self.repo_path)
        except Exception:
            purpose = ""

        entry_points = self.entry_points(limit=entry_point_limit)

        all_pathways = self.pathways(min_confidence=0.0, include_tests=False)
        top_pathway_meta = sorted(
            all_pathways,
            key=lambda pathway: (
                -(pathway.get("importance_score") or 0),
                -(pathway.get("confidence") or 0),
            ),
        )
        top_pathway_meta = _apply_limit(top_pathway_meta, max_pathways)
        pathways_total = len(all_pathways)

        store = self._get_store()
        top_pathways = [
            store.get_pathway(pathway["name"]) or pathway
            for pathway in top_pathway_meta
        ]

        all_definitely_dead = self.dead_code(min_tier="definitely_dead")
        all_probably_dead = [
            row
            for row in self.dead_code(min_tier="probably_dead")
            if row.get("dead_code_tier") == "probably_dead"
        ]
        definitely_dead = _apply_limit(
            [row for row in all_definitely_dead if not row.get("is_non_production")],
            max_dead,
        )
        probably_dead = _apply_limit(
            [row for row in all_probably_dead if not row.get("is_non_production")],
            max_dead,
        )
        definitely_dead_tooling = _apply_limit(
            [row for row in all_definitely_dead if row.get("is_non_production")],
            max_dead,
        )
        probably_dead_tooling = _apply_limit(
            [row for row in all_probably_dead if row.get("is_non_production")],
            max_dead,
        )

        duplicates = self.duplicates(min_severity="medium")
        modules = self.modules()
        invariants = self.invariants()
        config_registry = self.config_registry()
        config_registry_diagnostics = self.config_registry_diagnostics()
        config_top = (
            config_registry
            if max_config_keys is None
            else dict(list(config_registry.items())[:max_config_keys])
        )
        test_coverage = self.test_coverage()
        test_coverage_any_call = self.test_coverage_any_call()
        doc_warnings = self.doc_warnings(min_severity="medium")
        all_communities = self.communities()
        communities = _apply_limit(all_communities, max_communities)
        communities_total = len(all_communities)

        runtime_valid_count = sum(
            1
            for function in store.get_all_functions()
            if function.get("runtime_observed")
            and (function.get("runtime_observed_for_hash") or "")
            == (function.get("source_hash") or "")
        )

        report_warnings = _build_report_warnings(
            health=health,
            pathways_total=pathways_total,
            pathways_shown=len(top_pathways),
            communities_total=communities_total,
            communities_shown=len(communities),
            cfg_top=config_top,
            cfg_diag=config_registry_diagnostics,
        )

        return {
            "meta": {
                "repo_path": self.repo_path,
                "repograph_dir": self.repograph_dir,
                "initialized": True,
            },
            "health": health,
            "stats": stats,
            "count_semantics": {
                "functions": (
                    "Reported function counts exclude internal is_module_caller sentinel nodes."
                ),
                "pathways": (
                    "Default pathway/report views exclude auto_detected_test pathways unless include_tests=True."
                ),
            },
            "sync_semantics": {
                "dynamic_analysis": health.get("dynamic_analysis") or {},
                "coverage_metric": "entry_point_reachability_not_line_coverage",
            },
            "purpose": purpose,
            "modules": modules,
            "entry_points": entry_points,
            "pathways": top_pathways,
            "pathways_summary": {
                "total": pathways_total,
                "shown": len(top_pathways),
                "limit": max_pathways,
            },
            "runtime_observations": {
                "functions_with_valid_runtime_revision": runtime_valid_count,
                "note": (
                    "Counts Function nodes where runtime traces matched the current source_hash. "
                    "Stale rows clear when the file is re-indexed."
                ),
            },
            "dead_code": {
                "definitely_dead": definitely_dead,
                "probably_dead": probably_dead,
                "definitely_dead_tooling": definitely_dead_tooling,
                "probably_dead_tooling": probably_dead_tooling,
            },
            "duplicates": duplicates,
            "invariants": invariants,
            "config_registry": config_top,
            "config_registry_diagnostics": config_registry_diagnostics,
            "test_coverage": test_coverage,
            "coverage_definition": ENTRY_POINT_TEST_COVERAGE_DEFINITION,
            "test_coverage_any_call": test_coverage_any_call,
            "coverage_definition_any_call": ANY_CALL_TEST_COVERAGE_DEFINITION,
            "doc_warnings": doc_warnings,
            "communities": communities,
            "communities_summary": {
                "total": communities_total,
                "shown": len(communities),
                "limit": max_communities,
            },
            "report_warnings": report_warnings,
        }
