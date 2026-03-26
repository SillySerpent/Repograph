from __future__ import annotations

from pathlib import Path
from typing import Any

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest
from repograph.core.evidence import annotate_finding
from repograph.plugins.rules import get_rule_pack_config, apply_rule_pack_policy
from repograph.plugins.demand_analyzers.rules_common import iter_code_files, looks_db_bound, parsed_framework_context

_UI_HINTS = ("ui", "frontend", "templates", "views", "pages", "components", "static")
_API_HINTS = ("api", "routes", "route", "controllers", "controller", "handlers")
_DB_PATH_HINTS = ("db", "database", "storage", "repository", "repositories", "models")

class DBShortcutsAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.db_shortcuts",
        name="DB shortcuts analyzer",
        kind="demand_analyzer",
        description="Detects direct UI/API/route access to DB/ORM layers.",
        requires=("repo_files",),
        produces=("findings.db_shortcuts",),
        hooks=("on_analysis",),
        aliases=("analyzer.db_shortcuts",),
    )

    def analyze(self, **kwargs: Any):
        service = kwargs.get("service")
        repo_path = Path(kwargs.get("repo_path") or getattr(service, "repo_path", ".")).resolve()
        findings = []
        cfg = get_rule_pack_config(service)
        for rel, text, _full in iter_code_files(service, repo_path):
            rel_lower = rel.lower()
            src_parts = set(Path(rel_lower).parts)
            frameworks, route_functions = parsed_framework_context(repo_path, rel, text)
            is_ui = any(part in src_parts for part in _UI_HINTS)
            is_api = any(part in src_parts for part in _API_HINTS)
            has_db = looks_db_bound(text)
            has_framework_routes = bool(route_functions) or rel_lower.endswith('/route.ts') or rel_lower.endswith('/route.js')
            if is_ui and has_db:
                findings.append(apply_rule_pack_policy(annotate_finding({
                    "kind": "ui_to_db_shortcut",
                    "severity": "critical",
                    "file_path": rel,
                    "reason": "UI-facing path appears to import or reference a DB driver/ORM directly.",
                    "frameworks": frameworks,
                    "rule_pack": "db_shortcuts",
                }, family="boundary_shortcuts"), config=cfg))
            if (is_api or has_framework_routes) and has_db:
                findings.append(apply_rule_pack_policy(annotate_finding({
                    "kind": "route_to_db_shortcut" if has_framework_routes else "api_to_db_shortcut",
                    "severity": "critical" if has_framework_routes else "high",
                    "file_path": rel,
                    "reason": "API/controller path appears to import a DB driver/ORM directly.",
                    "frameworks": frameworks,
                    "route_functions": route_functions,
                    "rule_pack": "db_shortcuts",
                }, family="boundary_shortcuts"), config=cfg))
            if has_db and not any(hint in rel_lower.split('/') for hint in _DB_PATH_HINTS) and not is_ui and not is_api and not has_framework_routes:
                findings.append(apply_rule_pack_policy(annotate_finding({
                    "kind": "repository_bypass",
                    "severity": "medium",
                    "file_path": rel,
                    "reason": "Non-data-layer file appears to import a DB driver/ORM directly.",
                    "frameworks": frameworks,
                    "rule_pack": "db_shortcuts",
                }, family="boundary_shortcuts"), config=cfg))
        return findings

def build_plugin() -> DBShortcutsAnalyzerPlugin:
    return DBShortcutsAnalyzerPlugin()
