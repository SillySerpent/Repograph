from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from repograph.core.evidence import CAP_CONFIG_FLOW, SOURCE_INFERRED, evidence_tag
from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest
_ENV_PATTERNS=(re.compile(r"os\.getenv\(\s*['\"]([A-Z0-9_]+)['\"]\s*\)"),re.compile(r"environ\.get\(\s*['\"]([A-Z0-9_]+)['\"]\s*\)"),re.compile(r"process\.env\.([A-Z0-9_]+)"),)
_CONFIG_ACCESS_PATTERNS=(re.compile(r"config\[['\"]([A-Za-z0-9_.-]+)['\"]\]"),re.compile(r"config\.get\(\s*['\"]([A-Za-z0-9_.-]+)['\"]\s*\)"),re.compile(r"settings\.([A-Z0-9_]+)"),)
_KEY_PATTERN=re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*[:=]")
class ConfigFlowAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest=PluginManifest(id="demand_analyzer.config_flow",name="Config flow analyzer",kind="demand_analyzer",description="Infers config keys and maps where they are declared and read across the repo.",requires=("repo_files",),produces=(evidence_tag(CAP_CONFIG_FLOW,SOURCE_INFERRED).kind,),hooks=("on_analysis",),aliases=("analyzer.config_flow",),)
    def analyze(self, **kwargs: Any) -> list[dict]:
        service=kwargs.get("service")
        if service is None:
            raise ValueError("ConfigFlowAnalyzerPlugin requires service=")
        repo_path=Path(kwargs.get("repo_path") or getattr(service,"repo_path",".")).resolve()
        declarations: dict[str,list[dict[str,Any]]]={}
        reads: dict[str,list[dict[str,Any]]]={}
        scanned_files:list[str]=[]
        for file_entry in service.get_all_files():
            rel=file_entry.get("path","")
            ext=Path(rel).suffix.lower()
            full_path=repo_path/rel
            if not full_path.is_file():
                continue
            if ext not in {".py",".js",".jsx",".ts",".tsx",".json",".yaml",".yml",".toml",".ini",".cfg",".env"}:
                continue
            scanned_files.append(rel)
            text=full_path.read_text(encoding="utf-8",errors="ignore")
            if ext in {".json",".yaml",".yml",".toml",".ini",".cfg",".env"} or full_path.name.startswith(("config",".env")):
                for decl in self._extract_declarations(text,rel):
                    declarations.setdefault(decl["key"],[]).append(decl)
            if ext in {".py",".js",".jsx",".ts",".tsx",".toml"}:
                for read in self._extract_reads(text,rel):
                    reads.setdefault(read["key"],[]).append(read)
        keys=sorted(set(declarations)|set(reads))
        results=[]
        for key in keys:
            results.append({"key":key,"declarations":declarations.get(key,[]),"reads":reads.get(key,[]),"declaration_count":len(declarations.get(key,[])),"read_count":len(reads.get(key,[])),"evidence":evidence_tag(CAP_CONFIG_FLOW,SOURCE_INFERRED).as_dict(),})
        return [{"kind":"config_flow","keys":results,"count":len(results),"scanned_files":scanned_files}]
    @staticmethod
    def _extract_declarations(text:str,rel:str)->list[dict[str,Any]]:
        findings=[]
        for lineno,raw in enumerate(text.splitlines(),start=1):
            line=raw.strip()
            if not line or line.startswith(("#","//",";")):
                continue
            match=_KEY_PATTERN.match(line)
            if not match:
                continue
            key=match.group(1)
            if len(key)<2:
                continue
            findings.append({"key":key,"file_path":rel,"line":lineno})
        return findings
    @staticmethod
    def _extract_reads(text:str,rel:str)->list[dict[str,Any]]:
        findings=[]
        for pattern in _ENV_PATTERNS+_CONFIG_ACCESS_PATTERNS:
            for match in pattern.finditer(text):
                key=match.group(1)
                line=text[:match.start()].count("\n")+1
                findings.append({"key":key,"file_path":rel,"line":line,"pattern":pattern.pattern})
        return findings

def build_plugin()->ConfigFlowAnalyzerPlugin:
    return ConfigFlowAnalyzerPlugin()
