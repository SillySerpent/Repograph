"""JavaScript language parser plugin."""
from __future__ import annotations

from repograph.core.plugin_framework import PluginManifest
from repograph.plugins.parsers.base import ParserAdapter


def build_plugin() -> ParserAdapter:
    """Called by ensure_default_parsers_registered (via aliased import)."""
    from repograph.plugins.parsers.javascript.javascript_parser import JavaScriptParser
    return ParserAdapter(
        PluginManifest(
            id="parser.javascript",
            name="JavaScript parser",
            kind="parser",
            description="Tree-sitter JavaScript parser",
            languages=("javascript",),
            requires=("files",),
            produces=("symbols", "imports", "call_edges", "variables"),
            hooks=("on_file_parsed",),
        ),
        JavaScriptParser,
    )
