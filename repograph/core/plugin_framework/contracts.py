"""Plugin contracts for RepoGraph.

Authoring guide (manifest fields, hooks, registration, tests):
  ``docs/plugins/AUTHORING.md``
Reference stubs (one per kind, not loaded in production):
  ``repograph/plugins/examples/``

Every plugin in the system implements exactly one of the concrete base classes
defined here.  The kind hierarchy is:

Static analysis (fired during / after graph build)
  ParserPlugin          — parse source files into ParsedFile objects
  FrameworkAdapterPlugin — enrich a ParsedFile with framework-specific hints
  StaticAnalyzerPlugin  — query the finished graph, produce sync-time findings
  DemandAnalyzerPlugin  — service/query-time analyzers for UI and API consumers
  EvidenceProducerPlugin — collect declared/observed evidence (deps, configs)
  ExporterPlugin        — write output artefacts after the graph is complete

Dynamic analysis (fired when runtime trace files are present)
  TracerPlugin          — instrument a repo and collect raw execution traces
  DynamicAnalyzerPlugin — consume trace files, overlay findings onto the graph

AnalyzerPlugin is kept as a backwards-compatible alias for DemandAnalyzerPlugin.

Hook firing order during a full sync
  on_registry_bootstrap   (once, at scheduler init)
  on_files_discovered     (after file walk)
  on_file_parsed          (per file, inside the parse phase)
  on_graph_built          (after p12 — static analyzers fire here)
  on_analysis             (service/query-time demand analyzers)
  on_evidence             (after on_graph_built — evidence producers fire here)
  on_export               (after on_evidence — exporters write artefacts here)
  on_traces_collected     (if .repograph/runtime/ has files — dynamic analyzers)
  on_traces_analyzed      (after dynamic analyzers complete)

Hook firing order for tracer commands (repograph trace install / collect)
  on_tracer_install       (write instrumentation config)
  on_tracer_collect       (finalise and return trace file paths)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

# ---------------------------------------------------------------------------
# Kind and hook literals
# ---------------------------------------------------------------------------

PluginKind = Literal[
    "parser",
    "framework_adapter",
    "static_analyzer",
    "dynamic_analyzer",
    "tracer",
    "evidence_producer",
    "exporter",
    "demand_analyzer",
]

HookName = Literal[
    # Lifecycle
    "on_registry_bootstrap",   # once after all plugins are registered
    # Static pipeline (runner.py fires these)
    "on_files_discovered",     # after p01_walk        — files, config
    "on_file_parsed",          # per file              — file_record, parsed_file
    "on_graph_built",          # after p12             — store, config
    "on_evidence",             # after graph           — store, repo_path, repograph_dir
    "on_export",               # after evidence        — store, repograph_dir, config
    # Dynamic analysis
    "on_traces_collected",     # when runtime/ has files — trace_dir, store, config
    "on_traces_analyzed",      # after dynamic overlay — store, config
    # Tracer CLI commands
    "on_tracer_install",       # repograph trace install — repo_root, trace_dir
    "on_tracer_collect",       # repograph trace collect — trace_dir
    # Demand-side / legacy
    "on_analysis",
]


# ---------------------------------------------------------------------------
# PluginManifest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PluginManifest:
    """Stable metadata descriptor attached to every plugin.

    Fields
    ------
    id
        Globally unique dotted identifier, e.g. ``"static_analyzer.dead_code"``.
    name
        Human-readable label shown in listings.
    kind
        One of the PluginKind literals — determines which base class is
        expected and which registry accepts the plugin.
    version
        Semver string for the plugin implementation.
    description
        One-line summary of what the plugin does.
    requires
        Capability tokens needed before this plugin runs,
        e.g. ``("symbols", "call_edges")``.
    produces
        Capability tokens this plugin emits,
        e.g. ``("findings.dead_code",)``.
    languages
        Source languages handled (parsers / framework adapters).
    frameworks
        Framework names targeted (framework adapters).
    hooks
        HookName values this plugin responds to.  The scheduler only
        invokes a plugin for hooks declared here.
    default_enabled
        Whether active when no user config overrides.
    trace_formats
        For DynamicAnalyzerPlugins — trace format tokens this plugin
        can consume, e.g. ``("jsonl_call_trace",)``.
    trace_format
        For TracerPlugins — the single format this tracer produces.
    """

    id: str
    name: str
    kind: PluginKind
    version: str = "1.0"
    description: str = ""
    requires: tuple[str, ...] = field(default_factory=tuple)
    produces: tuple[str, ...] = field(default_factory=tuple)
    languages: tuple[str, ...] = field(default_factory=tuple)
    frameworks: tuple[str, ...] = field(default_factory=tuple)
    hooks: tuple[HookName, ...] = field(default_factory=tuple)
    default_enabled: bool = True
    trace_formats: tuple[str, ...] = field(default_factory=tuple)
    trace_format: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    order: int = 1000
    after: tuple[str, ...] = field(default_factory=tuple)
    before: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "version": self.version,
            "description": self.description,
            "requires": list(self.requires),
            "produces": list(self.produces),
            "languages": list(self.languages),
            "frameworks": list(self.frameworks),
            "hooks": list(self.hooks),
            "default_enabled": self.default_enabled,
            "trace_formats": list(self.trace_formats),
            "trace_format": self.trace_format,
            "aliases": list(self.aliases),
            "order": self.order,
            "after": list(self.after),
            "before": list(self.before),
        }


# ---------------------------------------------------------------------------
# Base plugin class
# ---------------------------------------------------------------------------

class RepoGraphPlugin(ABC):
    """Root base class for every RepoGraph plugin."""

    manifest: PluginManifest

    def plugin_id(self) -> str:
        return self.manifest.id

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.manifest.id!r}>"


# ---------------------------------------------------------------------------
# Static analysis contracts
# ---------------------------------------------------------------------------

class ParserPlugin(RepoGraphPlugin, ABC):
    """Parses a source file into a ParsedFile.  Fires on: on_file_parsed."""

    @abstractmethod
    def parse_file(self, file_record: Any) -> Any: ...

    def supported_languages(self) -> tuple[str, ...]:
        return self.manifest.languages


class FrameworkAdapterPlugin(RepoGraphPlugin, ABC):
    """Enriches a ParsedFile with framework metadata.  Fires on: on_file_parsed.

    Returns a dict that may include:
      frameworks: list[str]        — detected framework names
      route_functions: list[str]   — route handler qualified names
    """

    @abstractmethod
    def inspect(self, **kwargs: Any) -> dict[str, Any]: ...


class StaticAnalyzerPlugin(RepoGraphPlugin, ABC):
    """Queries the finished graph and produces structured findings.

    Fires on: on_graph_built

    Kwargs received: store, service, repo_path, repograph_dir
    Returns: list[dict] — each dict should include at least
             {"kind": str, "severity": str}
    """

    @abstractmethod
    def analyze(self, **kwargs: Any) -> list[dict]: ...


class DemandAnalyzerPlugin(RepoGraphPlugin, ABC):
    """Runs on demand from service/query contexts and returns structured findings.

    Fires on: on_analysis

    Kwargs received: typically ``service`` plus any analyzer-specific overrides.
    Returns: list[dict] — each dict should include at least
             {"kind": str, "severity": str}
    """

    @abstractmethod
    def analyze(self, **kwargs: Any) -> list[dict]: ...


# Backwards-compatible alias.
AnalyzerPlugin = DemandAnalyzerPlugin


class EvidenceProducerPlugin(RepoGraphPlugin, ABC):
    """Collects declared or observed evidence.  Fires on: on_evidence.

    Returns a dict, e.g.:
      {"kind": "declared_dependencies", "dependencies": [...], "count": N}
    """

    @abstractmethod
    def produce(self, **kwargs: Any) -> dict[str, Any]: ...


class ExporterPlugin(RepoGraphPlugin, ABC):
    """Writes output artefacts to .repograph/meta/.  Fires on: on_export.

    Kwargs received: store, repograph_dir, config
    Returns: dict summarising what was written.
    """

    @abstractmethod
    def export(self, **kwargs: Any) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Dynamic analysis contracts
# ---------------------------------------------------------------------------

class DynamicAnalyzerPlugin(RepoGraphPlugin, ABC):
    """Consumes runtime trace files and overlays findings onto the graph.

    Fires on: on_traces_collected  (when .repograph/runtime/ has files)

    Kwargs received: trace_dir (Path), store, repo_path
    Returns: list[dict] using the same schema as StaticAnalyzerPlugin.

    Declare consumable trace formats in manifest.trace_formats — the
    scheduler only fires this plugin when a matching file exists.
    """

    @abstractmethod
    def analyze_traces(
        self,
        trace_dir: Path,
        store: Any,
        **kwargs: Any,
    ) -> list[dict]: ...

    def supported_trace_formats(self) -> tuple[str, ...]:
        return self.manifest.trace_formats


class TracerPlugin(RepoGraphPlugin, ABC):
    """Instruments a repo to produce execution trace files.

    A TracerPlugin does NOT analyze — it only collects.
    DynamicAnalyzerPlugins consume what TracerPlugins produce.

    Fires on: on_tracer_install, on_tracer_collect
    (triggered by repograph trace install / repograph trace collect)

    install() writes instrumentation config so the next test run generates
    trace files in trace_dir.

    collect() finalises buffered output and returns written file paths.

    manifest.trace_format must match a token in a DynamicAnalyzerPlugin's
    manifest.trace_formats for the overlay to activate automatically.
    """

    @abstractmethod
    def install(self, repo_root: Path, trace_dir: Path, **kwargs: Any) -> dict:
        """Write instrumentation config.  Return metadata dict."""
        ...

    @abstractmethod
    def collect(self, trace_dir: Path, **kwargs: Any) -> list[Path]:
        """Finalise traces.  Return list of written file paths."""
        ...

    def trace_format(self) -> str:
        return self.manifest.trace_format


