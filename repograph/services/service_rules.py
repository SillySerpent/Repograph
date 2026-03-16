"""Rule, plugin, and intelligence-snapshot RepoGraph service methods."""
from __future__ import annotations

from typing import Any

from repograph.core.evidence import summarize_findings
from repograph.services.service_base import RepoGraphServiceProtocol


class ServiceRulesMixin:
    """Plugin wrappers and higher-level rule surfaces."""

    def plugin_manifests(self: RepoGraphServiceProtocol) -> dict[str, list[dict]]:
        """Return manifests for built-in plugin families."""
        from repograph.plugins.features import built_in_plugin_manifests

        return built_in_plugin_manifests()

    def run_analyzer_plugin(
        self: RepoGraphServiceProtocol,
        plugin_id: str,
        **kwargs: Any,
    ) -> Any:
        """Run a registered demand-side analyzer plugin against this service context."""
        from repograph.plugins.features import run_analyzer

        return run_analyzer(plugin_id, service=self, **kwargs)

    def run_evidence_plugin(
        self: RepoGraphServiceProtocol,
        plugin_id: str,
        **kwargs: Any,
    ) -> Any:
        """Run a registered evidence producer against this service context."""
        from repograph.plugins.features import run_evidence_producer

        return run_evidence_producer(plugin_id, service=self, **kwargs)

    def run_exporter_plugin(
        self: RepoGraphServiceProtocol,
        plugin_id: str,
        **kwargs: Any,
    ) -> Any:
        """Run a registered exporter plugin against this service context."""
        from repograph.plugins.features import run_exporter

        return run_exporter(plugin_id, service=self, **kwargs)

    def rule_pack_config(self: RepoGraphServiceProtocol) -> dict:
        """Return enabled rule-pack registration/config for current built-ins."""
        from repograph.plugins.rules import get_rule_pack_config

        return get_rule_pack_config(self).as_dict()

    def save_rule_pack_config(
        self: RepoGraphServiceProtocol,
        packs: dict[str, dict],
    ) -> dict:
        """Persist repo-local rule-pack overrides and return the resolved config."""
        from repograph.plugins.rules import save_rule_pack_overrides

        return save_rule_pack_overrides(self, packs).as_dict()

    def finding_statuses(self: RepoGraphServiceProtocol) -> dict:
        """Return persisted finding statuses for the current repo."""
        from repograph.plugins.rules import get_finding_status_store

        return get_finding_status_store(self).as_dict()

    def update_finding_status(
        self: RepoGraphServiceProtocol,
        finding_id: str,
        status: str,
        note: str | None = None,
    ) -> dict:
        """Persist an approval-oriented status for a finding."""
        from repograph.plugins.rules import update_finding_status

        return update_finding_status(self, finding_id, status, note)

    def contract_rules(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return contract-oriented rule findings."""
        return self.run_analyzer_plugin("demand_analyzer.contract_rules")

    def boundary_shortcuts(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return likely cross-layer shortcut findings."""
        return self.run_analyzer_plugin("demand_analyzer.boundary_shortcuts")

    def boundary_rules(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return all boundary-style findings."""
        return [*self.contract_rules(), *self.boundary_shortcuts()]

    def architecture_conformance(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return architecture shortcut and boundary findings."""
        return self.run_analyzer_plugin("demand_analyzer.architecture_conformance")

    def class_roles(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return inferred class-role classifications."""
        return self.run_analyzer_plugin("demand_analyzer.class_roles")

    def decomposition_signals(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return heuristic split/modulation candidates for files and classes."""
        return self.run_analyzer_plugin("demand_analyzer.decomposition_signals")

    def config_flow(self: RepoGraphServiceProtocol) -> dict:
        """Return inferred config key declarations and reads across the repo."""
        output = self.run_analyzer_plugin("demand_analyzer.config_flow")
        if isinstance(output, list):
            if output and isinstance(output[0], dict):
                return output[0]
            return {}
        if isinstance(output, dict):
            return output
        return {}

    def module_component_signals(self: RepoGraphServiceProtocol) -> list[dict]:
        """Return inferred module roles and component-candidate signals for files."""
        return self.run_analyzer_plugin("demand_analyzer.module_component_signals")

    def intelligence_snapshot(self: RepoGraphServiceProtocol) -> dict:
        """Return a grouped evidence snapshot for higher-level consumers."""
        from repograph.plugins.rules import (
            annotate_finding_statuses,
            get_finding_status_store,
            get_rule_pack_config,
            summarize_finding_statuses,
            summarize_rule_packs,
        )

        pathways = self.pathways(min_confidence=0.4)
        dead_code = self.dead_code()[:30]
        config_flow = self.config_flow()
        status_store = get_finding_status_store(self)
        architecture_conformance = annotate_finding_statuses(
            self.architecture_conformance()[:20],
            store=status_store,
        )
        contract_rules = annotate_finding_statuses(
            self.contract_rules()[:20],
            store=status_store,
        )
        boundary_shortcuts = annotate_finding_statuses(
            self.boundary_shortcuts()[:20],
            store=status_store,
        )
        class_roles = self.class_roles()
        module_signals = self.module_component_signals()
        runtime_overlay = self.runtime_overlay_summary()
        observed_runtime = self.observed_runtime_findings()
        report_surfaces = self.report_surfaces()
        rule_summary = summarize_findings(architecture_conformance)
        rule_pack_config = get_rule_pack_config(self)
        rule_pack_summary = summarize_rule_packs(
            architecture_conformance,
            config=rule_pack_config,
        )

        rule_pack_findings: dict[str, dict[str, Any]] = {}
        for finding in architecture_conformance:
            pack = str(finding.get("rule_pack") or "unpacked")
            bucket = rule_pack_findings.setdefault(pack, {"count": 0, "top": []})
            bucket["count"] += 1
            if len(bucket["top"]) < 10:
                bucket["top"].append(finding)

        actionable_findings = sorted(
            architecture_conformance,
            key=lambda item: int(item.get("severity_score") or 0),
            reverse=True,
        )[:20]

        evidence = {
            "config_flow": config_flow,
            "architecture_conformance": architecture_conformance,
            "rule_families": {
                "contract_rules": {"count": len(contract_rules), "top": contract_rules[:10]},
                "boundary_shortcuts": {
                    "count": len(boundary_shortcuts),
                    "top": boundary_shortcuts[:10],
                },
            },
            "class_roles": {"count": len(class_roles), "top": class_roles[:20]},
            "module_component_signals": {
                "count": len(module_signals),
                "top": module_signals[:20],
            },
            "runtime_overlay": runtime_overlay,
            "observed_runtime_findings": observed_runtime,
            "report_surfaces": report_surfaces,
            "rule_packs": rule_pack_summary,
            "rule_pack_config": rule_pack_config.as_dict(),
            "rule_pack_findings": rule_pack_findings,
            "actionable_findings": actionable_findings,
            "finding_statuses": status_store.as_dict(),
            "approval_summary": summarize_finding_statuses(architecture_conformance),
            "policies": {
                "boundary_rules": {
                    **rule_summary,
                    "overlay_mode": observed_runtime.get("overlay_mode", "augment_not_replace"),
                },
                "rule_families": {
                    "contract_rules": summarize_findings(contract_rules),
                    "boundary_shortcuts": summarize_findings(boundary_shortcuts),
                },
            },
        }
        return {
            "pathways": pathways,
            "dead_code": dead_code,
            "evidence": evidence,
            "config_flow": config_flow,
            "architecture_conformance": architecture_conformance,
            "report_surfaces": report_surfaces,
            "observed_runtime_findings": observed_runtime,
        }
