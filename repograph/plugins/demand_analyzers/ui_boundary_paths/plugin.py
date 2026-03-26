from __future__ import annotations

from pathlib import Path
from typing import Any

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest
from repograph.core.evidence import annotate_finding
from repograph.plugins.rules import get_rule_pack_config, apply_rule_pack_policy
from repograph.plugins.demand_analyzers.rules_common import extract_imports, iter_code_files, parsed_framework_context

_UI_HINTS = ("ui", "frontend", "templates", "views", "pages", "components", "static")
_DOMAIN_PARTS = {"domain", "services", "service", "core"}
_DB_PARTS = {"db", "database", "storage", "repository", "repositories", "models"}

class UIBoundaryPathsAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.ui_boundary_paths",
        name="UI boundary paths analyzer",
        kind="demand_analyzer",
        description="Detects UI imports that jump directly into DB/domain layers.",
        requires=("repo_files",),
        produces=("findings.ui_boundary_paths",),
        hooks=("on_analysis",),
        aliases=("analyzer.ui_boundary_paths",),
    )

    def analyze(self, **kwargs: Any):
        service = kwargs.get("service")
        repo_path = Path(kwargs.get("repo_path") or getattr(service, "repo_path", ".")).resolve()
        findings = []
        cfg = get_rule_pack_config(service)
        for rel, text, _full in iter_code_files(service, repo_path):
            rel_lower = rel.lower()
            src_parts = set(Path(rel_lower).parts)
            if not any(part in src_parts for part in _UI_HINTS):
                continue
            frameworks, _routes = parsed_framework_context(repo_path, rel, text)
            imports = extract_imports(text)
            db_imports = [i for i in imports if set(Path(i.replace('.', '/')).parts) & _DB_PARTS]
            domain_imports = [i for i in imports if set(Path(i.replace('.', '/')).parts) & _DOMAIN_PARTS]
            if db_imports:
                findings.append(apply_rule_pack_policy(annotate_finding({
                    "kind": "ui_cross_layer_shortcut",
                    "severity": "high",
                    "file_path": rel,
                    "reason": "UI-layer file appears to import DB/repository-layer modules directly.",
                    "imports": sorted(set(db_imports))[:10],
                    "frameworks": frameworks,
                    "rule_pack": "ui_boundary_paths",
                }, family="boundary_shortcuts"), config=cfg))
            elif domain_imports and not any(part in src_parts for part in {"api", "client"}):
                findings.append(apply_rule_pack_policy(annotate_finding({
                    "kind": "ui_domain_bypass",
                    "severity": "low",
                    "file_path": rel,
                    "reason": "UI-layer file appears to reach directly into service/domain modules.",
                    "imports": sorted(set(domain_imports))[:10],
                    "frameworks": frameworks,
                    "rule_pack": "ui_boundary_paths",
                }, family="boundary_shortcuts"), config=cfg))
        return findings

def build_plugin() -> UIBoundaryPathsAnalyzerPlugin:
    return UIBoundaryPathsAnalyzerPlugin()
