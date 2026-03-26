from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from repograph.core.evidence import CAP_CLASS_ROLES, CAP_SYMBOLS, SOURCE_INFERRED, evidence_tag
from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest
from repograph.plugins.utils import parse_file_with_plugins

_NAME_HINTS: dict[str, tuple[tuple[str, ...], int]] = {
    "component": (("component",), 2),
    "hook": (("hook", "use"), 1),
    "page": (("page",), 2),
    "layout": (("layout",), 2),
    "repository": (("repository", "repo", "store", "dao"), 3),
    "service": (("service",), 3),
    "handler": (("handler",), 3),
    "controller": (("controller", "view"), 3),
    "adapter": (("adapter", "client", "gateway"), 3),
    "validator": (("validator", "schema"), 3),
    "orchestrator": (("orchestrator", "coordinator", "manager"), 2),
    "entity": (("model", "entity", "record"), 2),
    "dto": (("dto", "payload", "request", "response"), 2),
    "config_model": (("config", "settings"), 3),
}

_PATH_HINTS: dict[str, tuple[tuple[str, ...], int]] = {
    "component": (("components",), 2),
    "hook": (("hooks",), 2),
    "page": (("pages", "app"), 2),
    "layout": (("layouts",), 2),
    "repository": (("repository", "repositories", "storage", "db", "database", "models"), 2),
    "service": (("service", "services"), 2),
    "handler": (("handler", "handlers", "events"), 2),
    "controller": (("controller", "controllers", "routes", "api", "ui", "views"), 2),
    "adapter": (("adapter", "adapters", "client", "clients", "gateway", "gateways"), 2),
    "validator": (("validator", "validators", "schema", "schemas"), 2),
    "entity": (("domain", "entities"), 1),
}

_METHOD_RULES: tuple[tuple[re.Pattern[str], str, int], ...] = (
    (re.compile(r"^(get|find|list|save|insert|update|delete|fetch_by_|upsert)"), "repository", 2),
    (re.compile(r"^(execute|run|process|perform)$"), "service", 2),
    (re.compile(r"^(orchestrate|coordinate|dispatch)$"), "orchestrator", 3),
    (re.compile(r"^handle"), "handler", 2),
    (re.compile(r"^(validate|check|assert)"), "validator", 2),
    (re.compile(r"^(to_|from_|serialize|deserialize|request|send|fetch)"), "adapter", 2),
)


class _ClassFactsVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.classes: list[dict[str, Any]] = []
        self._stack: list[ast.ClassDef] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        if self._stack:
            return  # skip nested classes for now to keep output stable/simple
        self._stack.append(node)
        methods: list[str] = []
        decorators: list[str] = []
        bases: list[str] = []
        dataclass_like = False
        for deco in node.decorator_list:
            d = ast.unparse(deco) if hasattr(ast, "unparse") else ""
            decorators.append(d)
            if d.endswith("dataclass") or d.endswith("BaseModel"):
                dataclass_like = True
        for base in node.bases:
            bases.append(ast.unparse(base) if hasattr(ast, "unparse") else "")
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(child.name)
        self.classes.append(
            {
                "name": node.name,
                "line_start": getattr(node, "lineno", 0),
                "line_end": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
                "methods": methods,
                "decorators": decorators,
                "bases": bases,
                "dataclass_like": dataclass_like,
            }
        )
        self._stack.pop()


class ClassRoleAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.class_roles",
        name="Class role analyzer",
        kind="demand_analyzer",
        description="Infers likely architectural roles for classes using names, paths, bases, and methods.",
        requires=(CAP_SYMBOLS,),
        produces=(evidence_tag(CAP_CLASS_ROLES, SOURCE_INFERRED).kind,),
        hooks=("on_analysis",),
        aliases=("analyzer.class_roles",),
    )

    def analyze(self, **kwargs):
        service = kwargs.get("service")
        if service is None:
            raise ValueError("ClassRoleAnalyzerPlugin requires service=")
        repo_path = Path(kwargs.get("repo_path") or getattr(service, "repo_path", ".")).resolve()
        results: list[dict[str, Any]] = []
        for file_entry in service.get_all_files():
            rel = file_entry.get("path", "")
            ext = Path(rel).suffix.lower()
            if ext not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
                continue
            full_path = repo_path / rel
            if not full_path.exists() or not full_path.is_file():
                continue
            text = full_path.read_text(encoding="utf-8", errors="ignore")
            if ext == ".py":
                classes = self._python_classes(text)
            else:
                classes = self._ts_js_classes(text)
            for cls in classes:
                parsed = parse_file_with_plugins(repo_path, rel, text=text) if ext == ".py" else None
                frameworks = sorted(set(getattr(parsed, "framework_hints", []) or [])) if parsed is not None else []
                plugin_artifacts = getattr(parsed, "plugin_artifacts", {}) if parsed is not None else {}
                if not any((artifact.get("route_functions") if isinstance(artifact, dict) else None) for artifact in plugin_artifacts.values()) and ("@app.route" in text or ".route(" in text or "@router." in text):
                    plugin_artifacts = dict(plugin_artifacts)
                    plugin_artifacts["textual.route"] = {"route_functions": ["<textual_route_hint>"]}
                scored = self._classify(rel, cls, frameworks=frameworks, plugin_artifacts=plugin_artifacts)
                results.append(scored)
        return results

    @staticmethod
    def _python_classes(text: str) -> list[dict[str, Any]]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        visitor = _ClassFactsVisitor()
        visitor.visit(tree)
        return visitor.classes

    @staticmethod
    def _ts_js_classes(text: str) -> list[dict[str, Any]]:
        pattern = re.compile(r"class\s+([A-Z][A-Za-z0-9_]*)")
        classes: list[dict[str, Any]] = []
        for match in pattern.finditer(text):
            classes.append(
                {
                    "name": match.group(1),
                    "line_start": text[: match.start()].count("\n") + 1,
                    "line_end": text[: match.end()].count("\n") + 1,
                    "methods": [],
                    "decorators": [],
                    "bases": [],
                    "dataclass_like": False,
                }
            )
        return classes

    def _classify(self, rel_path: str, cls: dict[str, Any], *, frameworks: list[str] | None = None, plugin_artifacts: dict[str, Any] | None = None) -> dict[str, Any]:
        scores: dict[str, int] = {}
        reasons: list[str] = []
        name_lower = cls["name"].lower()
        rel_lower = rel_path.lower()

        for role, (tokens, weight) in _NAME_HINTS.items():
            if any(token in name_lower for token in tokens):
                scores[role] = scores.get(role, 0) + weight
                reasons.append(f"name:{role}")
        path_parts = tuple(part for part in re.split(r"[/\\]", rel_lower) if part)
        for role, (tokens, weight) in _PATH_HINTS.items():
            if any(token in path_parts for token in tokens):
                scores[role] = scores.get(role, 0) + weight
                reasons.append(f"path:{role}")
        frameworks = frameworks or []
        if frameworks:
            reasons.append("framework:" + ",".join(sorted(frameworks)))
        route_functions: list[str] = []
        for artifact in (plugin_artifacts or {}).values():
            if isinstance(artifact, dict):
                route_functions.extend(artifact.get("route_functions", []) or [])
        if frameworks and ("flask" in frameworks or "fastapi" in frameworks):
            if any(token in path_parts for token in ("api", "routes", "controllers")):
                scores["controller"] = scores.get("controller", 0) + 3
                reasons.append("framework_path:controller")
            if route_functions:
                scores["controller"] = scores.get("controller", 0) + 2
                reasons.append("framework_routes:controller")
            if any(token in name_lower for token in ("router", "view", "resource", "endpoint")):
                scores["controller"] = scores.get("controller", 0) + 2
                reasons.append("framework_name:controller")
        if frameworks and ("react" in frameworks or "nextjs" in frameworks):
            component_names: list[str] = []
            hook_names: list[str] = []
            next_route_handlers: list[str] = []
            next_page = False
            next_layout = False
            next_server_action = False
            for artifact in (plugin_artifacts or {}).values():
                if isinstance(artifact, dict):
                    component_names.extend(artifact.get("component_names", []) or [])
                    hook_names.extend(artifact.get("hook_names", []) or [])
                    next_route_handlers.extend(artifact.get("route_handlers", []) or [])
                    next_page = next_page or bool(artifact.get("page_component"))
                    next_layout = next_layout or bool(artifact.get("layout_component"))
                    next_server_action = next_server_action or bool(artifact.get("server_action"))
            if cls["name"] in component_names or any(token in path_parts for token in ("components",)):
                scores["component"] = scores.get("component", 0) + 3
                reasons.append("framework_component:component")
            if cls["name"] in hook_names or cls["name"].startswith("use"):
                scores["hook"] = scores.get("hook", 0) + 3
                reasons.append("framework_hook:hook")
            if next_page:
                scores["page"] = scores.get("page", 0) + 4
                reasons.append("next_page:page")
            if next_layout:
                scores["layout"] = scores.get("layout", 0) + 4
                reasons.append("next_layout:layout")
            if next_route_handlers:
                scores["controller"] = scores.get("controller", 0) + 3
                reasons.append("next_route:controller")
            if next_server_action:
                scores["service"] = scores.get("service", 0) + 2
                reasons.append("next_server_action:service")
        if cls.get("dataclass_like"):
            scores["dto"] = scores.get("dto", 0) + 2
            reasons.append("decorator:dataclass_like")
        for base in cls.get("bases", []):
            base_lower = base.lower()
            if "basemodel" in base_lower:
                scores["dto"] = scores.get("dto", 0) + 2
                reasons.append("base:basemodel")
            if "model" in base_lower:
                scores["entity"] = scores.get("entity", 0) + 1
                reasons.append("base:model")
        for method in cls.get("methods", []):
            for pattern, role, weight in _METHOD_RULES:
                if pattern.search(method.lower()):
                    scores[role] = scores.get(role, 0) + weight
                    reasons.append(f"method:{method}->{role}")
        if cls.get("methods") and len(cls["methods"]) >= 8:
            scores["service"] = scores.get("service", 0) + 1
            reasons.append("shape:many_methods")
        if not scores:
            role = "unknown"
            confidence = 0.2
        else:
            ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
            role, best = ranked[0]
            second = ranked[1][1] if len(ranked) > 1 else 0
            confidence = min(0.95, 0.45 + 0.08 * best + 0.03 * max(best - second, 0))
        return {
            "class_name": cls["name"],
            "file_path": rel_path,
            "line_start": cls["line_start"],
            "line_end": cls["line_end"],
            "role": role,
            "confidence": round(confidence, 3),
            "frameworks": frameworks or [],
            "reasons": reasons[:6],
            "methods": cls.get("methods", [])[:20],
            "evidence": evidence_tag(CAP_CLASS_ROLES, SOURCE_INFERRED).as_dict(),
        }


def build_plugin() -> ClassRoleAnalyzerPlugin:
    return ClassRoleAnalyzerPlugin()
