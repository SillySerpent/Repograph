from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest
from repograph.core.evidence import annotate_finding
from repograph.plugins.rules import get_rule_pack_config, apply_rule_pack_policy
from repograph.plugins.demand_analyzers.rules_common import iter_code_files

_UI_PARTS = {"ui", "frontend", "components", "pages", "views", "app"}
_CONFIG_READ_PATTERNS = (
    re.compile(r"\bos\.getenv\("),
    re.compile(r"\bos\.environ(?:\[|\.)"),
    re.compile(r"\bprocess\.env\."),
)

class ConfigBoundaryReadsAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.config_boundary_reads",
        name="Config boundary reads analyzer",
        kind="demand_analyzer",
        description="Detects UI-facing files reading environment/config directly.",
        requires=("repo_files",),
        produces=("findings.config_boundary_reads",),
        hooks=("on_analysis",),
        aliases=("analyzer.config_boundary_reads",),
    )

    def analyze(self, **kwargs: Any):
        service = kwargs.get("service")
        repo_path = Path(kwargs.get("repo_path") or getattr(service, "repo_path", ".")).resolve()
        findings = []
        cfg = get_rule_pack_config(service)
        for rel, text, _full in iter_code_files(service, repo_path):
            parts = set(Path(rel.replace('\\','/').lower()).parts)
            if parts & _UI_PARTS and any(p.search(text) for p in _CONFIG_READ_PATTERNS):
                findings.append(apply_rule_pack_policy(annotate_finding({
                    "kind": "ui_direct_config_read",
                    "severity": "low",
                    "file_path": rel,
                    "reason": "UI-facing file appears to read environment/config values directly.",
                    "rule_pack": "config_boundary_reads",
                }, family="contract_rules"), config=cfg))
        return findings

def build_plugin() -> ConfigBoundaryReadsAnalyzerPlugin:
    return ConfigBoundaryReadsAnalyzerPlugin()
