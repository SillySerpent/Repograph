from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repograph.core.evidence import CAP_OBSERVED_RUNTIME_FINDINGS, CAP_RUNTIME_OVERLAY, SOURCE_OBSERVED, evidence_tag
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest


class ObservedRuntimeFindingsExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.observed_runtime_findings",
        name="Observed runtime findings exporter",
        kind="exporter",
        description="Consumes optional runtime overlay files and summarizes observed routes, symbols, and paths without replacing static evidence.",
        requires=(CAP_RUNTIME_OVERLAY,),
        produces=(evidence_tag(CAP_OBSERVED_RUNTIME_FINDINGS, SOURCE_OBSERVED).kind,),
        hooks=("on_export",),
        order=200,
    )

    def export(self, **kwargs: Any):
        service = kwargs.get("service")
        if service is not None:
            observed = service.run_evidence_plugin("evidence.runtime_overlay")
            repograph_dir = Path(getattr(service, "repograph_dir", ".repograph"))
        else:
            repograph_dir = Path(kwargs.get("repograph_dir") or ".repograph")
            runtime_dir = repograph_dir / "runtime"
            trace_files = sorted(p.relative_to(repograph_dir).as_posix() for p in runtime_dir.rglob("*") if p.is_file()) if runtime_dir.exists() else []
            observed = {"trace_files": trace_files}
        trace_files = observed.get("trace_files", [])
        routes: set[str] = set()
        symbols: set[str] = set()
        paths: set[str] = set()
        for rel in trace_files:
            full = repograph_dir / rel
            if not full.is_file():
                continue
            try:
                payload = json.loads(full.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            self._collect(payload, routes, symbols, paths)
        return {
            "kind": "observed_runtime_findings",
            "overlay_mode": "augment_not_replace",
            "replaces_static": False,
            "count": len(trace_files),
            "observed_route_count": len(routes),
            "observed_symbol_count": len(symbols),
            "observed_path_count": len(paths),
            "top_routes": sorted(routes)[:20],
            "top_symbols": sorted(symbols)[:20],
            "top_paths": sorted(paths)[:20],
            "trace_files": trace_files[:50],
            "evidence": evidence_tag(CAP_OBSERVED_RUNTIME_FINDINGS, SOURCE_OBSERVED).as_dict(),
        }

    def _collect(self, value: Any, routes: set[str], symbols: set[str], paths: set[str]) -> None:
        if isinstance(value, dict):
            for key in ("route", "path", "url", "endpoint"):
                v = value.get(key)
                if isinstance(v, str) and v.startswith("/"):
                    routes.add(v)
            for key in ("symbol", "function", "qualified_name", "handler"):
                v = value.get(key)
                if isinstance(v, str) and v:
                    symbols.add(v)
            for key in ("file", "file_path", "module"):
                v = value.get(key)
                if isinstance(v, str) and v:
                    paths.add(v)
            for v in value.values():
                self._collect(v, routes, symbols, paths)
        elif isinstance(value, list):
            for item in value:
                self._collect(item, routes, symbols, paths)


def build_plugin() -> ObservedRuntimeFindingsExporterPlugin:
    return ObservedRuntimeFindingsExporterPlugin()
