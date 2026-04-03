"""Overview, meta-export, and structural RepoGraph service methods."""
from __future__ import annotations

import os

from repograph.graph_store.store_queries_entrypoints import (
    ANY_CALL_TEST_COVERAGE_DEFINITION,
    ENTRY_POINT_TEST_COVERAGE_DEFINITION,
)
from repograph.services.service_base import RepoGraphServiceProtocol, _observed_service_call


def _load_json_file(path: str) -> dict | list | None:
    import json

    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


class ServiceOverviewMixin:
    """Health, meta-export, and structural overview surfaces."""

    @_observed_service_call("service_status")
    def status(self: RepoGraphServiceProtocol) -> dict:
        """Return index health, counts, and last-sync metadata."""
        if not self._is_initialized():
            return {"initialized": False}

        store = self._get_store()
        stats = store.get_stats()
        stats["initialized"] = True

        meta = _load_json_file(os.path.join(self.repograph_dir, "meta.json"))
        if isinstance(meta, dict):
            stats["last_sync"] = meta.get("generated_at", "unknown")
            stats["repo"] = meta.get("repo_name", os.path.basename(self.repo_path))

        from repograph.pipeline.health import read_health_json

        health = read_health_json(self.repograph_dir)
        if health:
            stats["health"] = {
                "contract_version": health.get("contract_version"),
                "sync_mode": health.get("sync_mode"),
                "call_edges_total": health.get("call_edges_total"),
                "generated_at": health.get("generated_at"),
                "strict": health.get("strict"),
                "status": health.get("status"),
                "error_phase": health.get("error_phase"),
                "error_message": health.get("error_message"),
                "partial_completion": health.get("partial_completion"),
                "hook_summary": health.get("hook_summary"),
                "dynamic_analysis": health.get("dynamic_analysis") or {},
                "analysis_readiness": health.get("analysis_readiness") or {},
            }
        return stats

    @_observed_service_call("service_modules")
    def modules(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return the per-directory module index built by the modules exporter."""
        payload = _load_json_file(os.path.join(self.repograph_dir, "meta", "modules.json"))
        return payload if isinstance(payload, list) else []

    @_observed_service_call(
        "service_config_registry",
        metadata_fn=lambda self, key=None: {"has_key_filter": key is not None},
    )
    def config_registry(
        self: RepoGraphServiceProtocol,
        key: str | None = None,
    ) -> dict:
        """Return the global config-key to consumer mapping."""
        payload = _load_json_file(
            os.path.join(self.repograph_dir, "meta", "config_registry.json")
        )
        if not isinstance(payload, dict):
            return {}
        if key is not None:
            return {key: payload[key]} if key in payload else {}
        return payload

    @_observed_service_call("service_config_registry_diagnostics")
    def config_registry_diagnostics(self: RepoGraphServiceProtocol) -> dict:
        """Return exporter diagnostics for config-registry generation."""
        payload = _load_json_file(
            os.path.join(
                self.repograph_dir,
                "meta",
                "config_registry_diagnostics.json",
            )
        )
        return payload if isinstance(payload, dict) else {}

    @_observed_service_call("service_test_coverage")
    def test_coverage(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return per-file entry-point reachability from test code."""
        return self._get_store().get_test_coverage_map()

    @_observed_service_call("service_test_coverage_any_call")
    def test_coverage_any_call(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return per-file share of non-test functions with a test caller."""
        return self._get_store().get_any_call_test_coverage_map()

    @property
    def coverage_definition(self: RepoGraphServiceProtocol) -> str:
        """Short explanation of what ``test_coverage()`` measures."""
        return ENTRY_POINT_TEST_COVERAGE_DEFINITION

    @property
    def coverage_definition_any_call(self: RepoGraphServiceProtocol) -> str:
        """Short explanation of what ``test_coverage_any_call()`` measures."""
        return ANY_CALL_TEST_COVERAGE_DEFINITION

    @_observed_service_call(
        "service_invariants",
        metadata_fn=lambda self, inv_type=None, file_path=None: {
            "has_inv_type_filter": inv_type is not None,
            "has_file_filter": file_path is not None,
        },
    )
    def invariants(
        self: RepoGraphServiceProtocol,
        inv_type: str | None = None,
        file_path: str | None = None,
    ) -> list[dict]:
        """Return documented architectural invariants extracted by the exporter."""
        payload = _load_json_file(os.path.join(self.repograph_dir, "meta", "invariants.json"))
        if not isinstance(payload, list):
            return []

        invariants = payload
        if inv_type:
            invariants = [
                invariant
                for invariant in invariants
                if invariant.get("invariant_type") == inv_type
            ]
        if file_path:
            invariants = [
                invariant
                for invariant in invariants
                if invariant.get("file_path") == file_path
            ]
        return invariants

    @_observed_service_call("service_event_topology")
    def event_topology(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return heuristic event-bus call sites."""
        return self._get_store().get_event_topology()

    @_observed_service_call("service_async_tasks")
    def async_tasks(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return asyncio task spawn records."""
        return self._get_store().get_async_tasks()

    @_observed_service_call("service_interface_map")
    def interface_map(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return inheritance-based interface-to-implementation mapping."""
        from repograph.plugins.static_analyzers.interface_map.plugin import get_interface_map

        return get_interface_map(self._get_store())

    @_observed_service_call(
        "service_constructor_deps",
        metadata_fn=lambda self, class_name, depth=2: {
            "class_name_len": len(class_name or ""),
            "depth": int(depth),
        },
    )
    def constructor_deps(
        self: RepoGraphServiceProtocol,
        class_name: str,
        depth: int = 2,
    ) -> dict:
        """Return ``__init__`` parameter names for a class."""
        return self._get_store().get_constructor_deps(class_name, depth=depth)

    @_observed_service_call("service_communities")
    def communities(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return all detected communities sorted by member count."""
        rows = self._get_store().query(
            "MATCH (c:Community) RETURN c.id, c.label, c.member_count, c.cohesion "
            "ORDER BY c.member_count DESC"
        )
        return [
            {
                "id": row[0],
                "label": row[1],
                "member_count": row[2],
                "cohesion": row[3],
            }
            for row in rows
        ]
