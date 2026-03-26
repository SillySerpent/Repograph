"""TypeScript language parser plugin."""
from __future__ import annotations

from repograph.core.plugin_framework import PluginManifest
from repograph.plugins.parsers.base import ParserAdapter


def build_plugin() -> ParserAdapter:
    """Called by ensure_default_parsers_registered (via aliased import)."""
    from repograph.plugins.parsers.typescript.typescript_parser import TypeScriptParser
    return ParserAdapter(
        PluginManifest(
            id="parser.typescript",
            name="TypeScript parser",
            kind="parser",
            description="Tree-sitter TypeScript parser",
            languages=("typescript",),
            requires=("files",),
            produces=("symbols", "imports", "call_edges", "variables"),
            hooks=("on_file_parsed",),
        ),
        TypeScriptParser,
    )
