from repograph.core.plugin_framework.contracts import (
    AnalyzerPlugin,          # legacy alias for DemandAnalyzerPlugin
    DemandAnalyzerPlugin,
    DynamicAnalyzerPlugin,
    EvidenceProducerPlugin,
    ExporterPlugin,
    FrameworkAdapterPlugin,
    ParserPlugin,
    PluginKind,
    PluginManifest,
    RepoGraphPlugin,
    StaticAnalyzerPlugin,
    TracerPlugin,
)
from repograph.core.plugin_framework.hooks import HookExecution, PluginHookScheduler
from repograph.core.plugin_framework.pipeline_phases import PipelinePhasePlugin
from repograph.core.plugin_framework.registry import PluginRegistry

__all__ = [
    "AnalyzerPlugin",
    "DemandAnalyzerPlugin",
    "DynamicAnalyzerPlugin",
    "EvidenceProducerPlugin",
    "ExporterPlugin",
    "FrameworkAdapterPlugin",
    "HookExecution",
    "ParserPlugin",
    "PluginKind",
    "PluginHookScheduler",
    "PluginManifest",
    "PipelinePhasePlugin",
    "PluginRegistry",
    "RepoGraphPlugin",
    "StaticAnalyzerPlugin",
    "TracerPlugin",
]
