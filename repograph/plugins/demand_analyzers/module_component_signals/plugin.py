from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from repograph.core.evidence import CAP_MODULE_COMPONENT_SIGNALS, SOURCE_INFERRED, evidence_tag
from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest
from repograph.plugins.utils import parse_file_with_plugins

_ROLE_TOKENS = {
    "ui": ("ui", "views"),
    "component": ("components", "component"),
    "hook": ("hooks", "hook"),
    "page": ("pages", "page"),
    "layout": ("layouts", "layout"),
    "api": ("api", "routes", "controllers"),
    "service": ("service", "services"),
    "data": ("repository", "repositories", "storage", "db", "database", "models"),
    "config": ("config", "settings"),
    "tests": ("test", "tests", "spec"),
}
_FRAMEWORK_ROUTE_PATHS = {"api", "routes", "controllers"}


class ModuleComponentSignalsAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.module_component_signals",
        name="Module/component signals analyzer",
        kind="demand_analyzer",
        description="Infers likely module roles and component-candidate signals from file paths and simple structure.",
        requires=("repo_files",),
        produces=(evidence_tag(CAP_MODULE_COMPONENT_SIGNALS, SOURCE_INFERRED).kind,),
        hooks=("on_analysis",),
        aliases=("analyzer.module_component_signals",),
    )

    def analyze(self, **kwargs: Any):
        service = kwargs.get("service")
        if service is None:
            raise ValueError("ModuleComponentSignalsAnalyzerPlugin requires service=")
        repo_path = Path(kwargs.get("repo_path") or getattr(service, "repo_path", ".")).resolve()
        results = []
        for file_entry in service.get_all_files():
            rel = file_entry.get("path", "")
            ext = Path(rel).suffix.lower()
            if ext not in {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css"}:
                continue
            full_path = repo_path / rel
            if not full_path.is_file():
                continue
            text = full_path.read_text(encoding="utf-8", errors="ignore")
            path_parts = tuple(part.lower() for part in Path(rel).parts)
            stem = Path(rel).stem.lower()
            role_scores: dict[str, int] = {}
            reasons: list[str] = []
            for role, tokens in _ROLE_TOKENS.items():
                matched = False
                for token in tokens:
                    if token in path_parts:
                        role_scores[role] = role_scores.get(role, 0) + 3
                        matched = True
                    elif f"/{token}/" in f"/{rel.lower()}/":
                        role_scores[role] = role_scores.get(role, 0) + 2
                        matched = True
                    elif token in stem:
                        role_scores[role] = role_scores.get(role, 0) + 1
                        matched = True
                if matched:
                    reasons.append(f"path:{role}")
            parsed = parse_file_with_plugins(repo_path, rel, text=text)
            frameworks = sorted(set(getattr(parsed, "framework_hints", []) or [])) if parsed is not None else []
            route_functions: list[str] = []
            if parsed is not None:
                for artifact in getattr(parsed, "plugin_artifacts", {}).values():
                    if isinstance(artifact, dict):
                        route_functions.extend(artifact.get("route_functions", []) or [])
            if not route_functions and ("@app.route" in text or ".route(" in text or "@router." in text):
                route_functions = ["<textual_route_hint>"]
            route_functions = sorted(set(route_functions))
            if frameworks:
                reasons.append("framework:" + ",".join(frameworks))
            if frameworks and any(token in path_parts for token in _FRAMEWORK_ROUTE_PATHS):
                role_scores["api"] = role_scores.get("api", 0) + 3
                reasons.append("framework_path:api")
            if route_functions:
                role_scores["api"] = role_scores.get("api", 0) + 3
                reasons.append("framework_routes:api")
            if frameworks and ("react" in frameworks or "nextjs" in frameworks):
                component_names: list[str] = []
                hook_names: list[str] = []
                next_route_handlers: list[str] = []
                next_page = False
                next_layout = False
                next_server_action = False
                if parsed is not None:
                    for artifact in getattr(parsed, "plugin_artifacts", {}).values():
                        if isinstance(artifact, dict):
                            component_names.extend(artifact.get("component_names", []) or [])
                            hook_names.extend(artifact.get("hook_names", []) or [])
                            next_route_handlers.extend(artifact.get("route_handlers", []) or [])
                            next_page = next_page or bool(artifact.get("page_component"))
                            next_layout = next_layout or bool(artifact.get("layout_component"))
                            next_server_action = next_server_action or bool(artifact.get("server_action"))
                if component_names or 'components' in path_parts or ext in {'.jsx', '.tsx'}:
                    role_scores["component"] = role_scores.get("component", 0) + 3
                    reasons.append("framework_component:component")
                if hook_names or stem.startswith('use') or 'hooks' in path_parts:
                    role_scores["hook"] = role_scores.get("hook", 0) + 3
                    reasons.append("framework_hook:hook")
                if next_page or rel.endswith(("/page.tsx", "/page.jsx")):
                    role_scores["page"] = role_scores.get("page", 0) + 4
                    reasons.append("next_page:page")
                if next_layout or rel.endswith(("/layout.tsx", "/layout.jsx")):
                    role_scores["layout"] = role_scores.get("layout", 0) + 4
                    reasons.append("next_layout:layout")
                if next_route_handlers or rel.endswith(("/route.ts", "/route.js")):
                    role_scores["api"] = role_scores.get("api", 0) + 4
                    reasons.append("next_route:api")
                if next_server_action:
                    role_scores["service"] = role_scores.get("service", 0) + 2
                    reasons.append("next_server_action:service")
            line_count = len(text.splitlines())
            class_count = len(re.findall(r"\bclass\s+[A-Z_]", text))
            func_count = len(re.findall(r"\b(def|function|const\s+[A-Za-z0-9_]+\s*=\s*\()", text))
            export_count = len(re.findall(r"\b(export\s+default|module\.exports|return\s+)", text))
            if ext in {'.js', '.jsx', '.ts', '.tsx'} and stem.startswith('use'):
                role_scores['hook'] = role_scores.get('hook', 0) + 4
                reasons.append('name_shape:hook')
            if line_count >= 120:
                reasons.append("shape:large_file")
            if class_count + func_count >= 5:
                reasons.append("shape:rich_surface")
            if export_count >= 1:
                reasons.append("shape:exports")
            role = "unknown"
            confidence = 0.25
            if role_scores:
                role, best = sorted(role_scores.items(), key=lambda item: (-item[1], item[0]))[0]
                confidence = min(0.94, 0.45 + 0.08 * best)
            component_candidate = bool(line_count >= 80 or class_count >= 1 or func_count >= 4 or route_functions)
            results.append(
                {
                    "file_path": rel,
                    "module_role": role,
                    "confidence": round(confidence, 3),
                    "frameworks": frameworks,
                    "component_candidate": component_candidate,
                    "signals": {
                        "line_count": line_count,
                        "class_count": class_count,
                        "function_count": func_count,
                        "export_count": export_count,
                        "route_function_count": len(route_functions),
                    },
                    "reasons": reasons[:6],
                    "evidence": evidence_tag(CAP_MODULE_COMPONENT_SIGNALS, SOURCE_INFERRED).as_dict(),
                }
            )
        return results


def build_plugin() -> ModuleComponentSignalsAnalyzerPlugin:
    return ModuleComponentSignalsAnalyzerPlugin()
