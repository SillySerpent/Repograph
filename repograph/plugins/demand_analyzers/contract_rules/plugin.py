from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest
from repograph.plugins.rules import get_rule_pack_config

class ContractRulesAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.contract_rules",
        name="Contract rules analyzer",
        kind="demand_analyzer",
        description="Aggregates contract-oriented rule packs such as private-surface bypasses and direct config reads from UI files.",
        requires=("repo_files",),
        produces=("findings.contract_rules",),
        hooks=("on_analysis",),
        aliases=("analyzer.contract_rules",),
    )

    def analyze(self, **kwargs: Any):
        service = kwargs.get("service")
        if service is None:
            return []
        cfg = get_rule_pack_config(service)
        findings = []
        for plugin_id in cfg.enabled_for_family("contract_rules"):
            findings.extend(service.run_analyzer_plugin(f"demand_analyzer.{plugin_id}"))
        return findings

def build_plugin() -> ContractRulesAnalyzerPlugin:
    return ContractRulesAnalyzerPlugin()
