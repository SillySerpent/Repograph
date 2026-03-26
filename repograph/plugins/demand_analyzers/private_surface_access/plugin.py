from __future__ import annotations

from pathlib import Path
from typing import Any

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest
from repograph.core.evidence import annotate_finding
from repograph.plugins.rules import get_rule_pack_config, apply_rule_pack_policy
from repograph.plugins.demand_analyzers.rules_common import extract_imports, iter_code_files

_PRIVATE_TOKENS = ("._", "/_", ".internal", "/internal/", ".private", "/private/", ".impl", "/impl/")

class PrivateSurfaceAccessAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.private_surface_access",
        name="Private surface access analyzer",
        kind="demand_analyzer",
        description="Detects imports that bypass private/internal implementation boundaries.",
        requires=("repo_files",),
        produces=("findings.private_surface_access",),
        hooks=("on_analysis",),
        aliases=("analyzer.private_surface_access",),
    )

    def analyze(self, **kwargs: Any):
        service = kwargs.get("service")
        repo_path = Path(kwargs.get("repo_path") or getattr(service, "repo_path", ".")).resolve()
        findings = []
        cfg = get_rule_pack_config(service)
        for rel, text, _full in iter_code_files(service, repo_path):
            private_imports = [i for i in extract_imports(text) if any(t in i for t in _PRIVATE_TOKENS)]
            if private_imports:
                findings.append(apply_rule_pack_policy(annotate_finding({
                    "kind": "private_surface_bypass",
                    "severity": "medium",
                    "file_path": rel,
                    "reason": "File appears to import an internal/private implementation path directly.",
                    "imports": sorted(set(private_imports))[:10],
                    "rule_pack": "private_surface_access",
                }, family="contract_rules"), config=cfg))
        return findings

def build_plugin() -> PrivateSurfaceAccessAnalyzerPlugin:
    return PrivateSurfaceAccessAnalyzerPlugin()
