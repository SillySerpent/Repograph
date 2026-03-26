from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from repograph.core.evidence import CAP_DECOMPOSITION_SIGNALS, CAP_SYMBOLS, SOURCE_INFERRED, evidence_tag
from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest


class _TopLevelFactsVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.function_count = 0
        self.class_facts: list[dict[str, Any]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.function_count += 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.function_count += 1

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        public_methods = 0
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
                public_methods += 1
        self.class_facts.append(
            {
                "name": node.name,
                "line_start": getattr(node, "lineno", 0),
                "line_end": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
                "public_method_count": public_methods,
            }
        )


class DecompositionSignalAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.decomposition_signals",
        name="Decomposition signal analyzer",
        kind="demand_analyzer",
        description="Flags files/classes that look ready for sub-component extraction or structural split proposals.",
        requires=(CAP_SYMBOLS,),
        produces=(evidence_tag(CAP_DECOMPOSITION_SIGNALS, SOURCE_INFERRED).kind,),
        hooks=("on_analysis",),
        aliases=("analyzer.decomposition_signals",),
    )

    def analyze(self, **kwargs):
        service = kwargs.get("service")
        if service is None:
            raise ValueError("DecompositionSignalAnalyzerPlugin requires service=")
        repo_path = Path(kwargs.get("repo_path") or getattr(service, "repo_path", ".")).resolve()
        findings: list[dict[str, Any]] = []
        for file_entry in service.get_all_files():
            rel = file_entry.get("path", "")
            ext = Path(rel).suffix.lower()
            if ext not in {".py"}:
                continue
            full_path = repo_path / rel
            if not full_path.exists() or not full_path.is_file():
                continue
            text = full_path.read_text(encoding="utf-8", errors="ignore")
            facts = self._python_facts(text)
            file_reasons: list[str] = []
            score = 0
            line_count = file_entry.get("line_count") or len(text.splitlines())
            if line_count >= 250:
                score += 2
                file_reasons.append("file:large_line_count")
            if facts["function_count"] >= 8:
                score += 2
                file_reasons.append("file:many_top_level_functions")
            if len(facts["class_facts"]) >= 3:
                score += 1
                file_reasons.append("file:many_top_level_classes")
            if score >= 3:
                findings.append(
                    {
                        "target_type": "file",
                        "target": rel,
                        "severity": "medium" if score == 3 else "high",
                        "score": score,
                        "suggested_action": "promote_component_to_folder",
                        "reasons": file_reasons,
                        "evidence": evidence_tag(CAP_DECOMPOSITION_SIGNALS, SOURCE_INFERRED).as_dict(),
                    }
                )
            for cls in facts["class_facts"]:
                class_score = 0
                class_reasons: list[str] = []
                span = max(0, cls["line_end"] - cls["line_start"] + 1)
                if span >= 140:
                    class_score += 2
                    class_reasons.append("class:large_span")
                if cls["public_method_count"] >= 8:
                    class_score += 2
                    class_reasons.append("class:many_public_methods")
                if class_score >= 2:
                    findings.append(
                        {
                            "target_type": "class",
                            "target": f"{rel}:{cls['name']}",
                            "file_path": rel,
                            "class_name": cls["name"],
                            "severity": "medium" if class_score == 2 else "high",
                            "score": class_score,
                            "suggested_action": "extract_subcomponents",
                            "reasons": class_reasons,
                            "evidence": evidence_tag(CAP_DECOMPOSITION_SIGNALS, SOURCE_INFERRED).as_dict(),
                        }
                    )
        return findings

    @staticmethod
    def _python_facts(text: str) -> dict[str, Any]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return {"function_count": 0, "class_facts": []}
        visitor = _TopLevelFactsVisitor()
        visitor.visit(tree)
        return {"function_count": visitor.function_count, "class_facts": visitor.class_facts}


def build_plugin() -> DecompositionSignalAnalyzerPlugin:
    return DecompositionSignalAnalyzerPlugin()
