from __future__ import annotations

from pathlib import Path
import re

from repograph.core.plugin_framework import EvidenceProducerPlugin, PluginManifest

_REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


class DeclaredDependenciesEvidencePlugin(EvidenceProducerPlugin):
    manifest = PluginManifest(
        id="evidence.declared_dependencies",
        name="Declared dependencies scanner",
        kind="evidence_producer",
        description="Scans requirements and pyproject files for declared dependency names.",
        requires=("repo_files",),
        produces=("evidence.declared_dependencies",),
        hooks=("on_evidence",),
    )

    def produce(self, **kwargs):
        service = kwargs.get("service")
        repo_path = Path(kwargs.get("repo_path") or getattr(service, "repo_path", ".")).resolve()
        findings: dict[str, dict] = {}
        scanned_files: list[str] = []

        candidate_files = [
            repo_path / "pyproject.toml",
            repo_path / "requirements.txt",
            repo_path / "requirements-dev.txt",
            repo_path / "requirements-test.txt",
        ]
        candidate_files.extend(sorted(repo_path.glob("requirements/*.txt")))

        for path in candidate_files:
            if not path.exists() or not path.is_file():
                continue
            rel = path.relative_to(repo_path).as_posix()
            scanned_files.append(rel)
            if path.name == "pyproject.toml":
                text = path.read_text(encoding="utf-8", errors="ignore")
                for dep in self._parse_pyproject(text):
                    findings.setdefault(dep, {"name": dep, "sources": []})["sources"].append(rel)
            else:
                for dep in self._parse_requirements(path.read_text(encoding="utf-8", errors="ignore")):
                    findings.setdefault(dep, {"name": dep, "sources": []})["sources"].append(rel)

        return {
            "kind": "declared_dependencies",
            "dependencies": sorted(findings.values(), key=lambda d: d["name"].lower()),
            "scanned_files": scanned_files,
            "count": len(findings),
        }

    @staticmethod
    def _parse_requirements(text: str) -> list[str]:
        deps: list[str] = []
        for line in text.splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or raw.startswith("-"):
                continue
            match = _REQ_RE.match(raw)
            if match:
                deps.append(match.group(1).lower())
        return deps

    @staticmethod
    def _parse_pyproject(text: str) -> list[str]:
        deps: list[str] = []
        in_dep_block = False
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("dependencies = ["):
                in_dep_block = True
                continue
            if in_dep_block:
                if line.startswith("]"):
                    in_dep_block = False
                    continue
                if line.startswith('"'):
                    dep = line.strip().strip(',').strip('"').split()[0]
                    dep = re.split(r"[<>=!~\[]", dep, maxsplit=1)[0]
                    if dep:
                        deps.append(dep.lower())
        return deps


def build_plugin() -> DeclaredDependenciesEvidencePlugin:
    return DeclaredDependenciesEvidencePlugin()
