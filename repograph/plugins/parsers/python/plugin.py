"""Python language parser plugin.

Implementation: ``plugins/parsers/python/python_parser.py`` (``PythonParser``),
wrapped here with ``ParserAdapter`` for the parser registry.
"""
from __future__ import annotations

from repograph.core.plugin_framework import PluginManifest
from repograph.plugins.parsers.base import ParserAdapter


def build_plugin() -> ParserAdapter:
    """Called by ensure_default_parsers_registered (via aliased import)."""
    from repograph.plugins.parsers.python.python_parser import PythonParser
    return ParserAdapter(
        PluginManifest(
            id="parser.python",
            name="Python parser",
            kind="parser",
            description="Tree-sitter Python parser",
            languages=("python",),
            requires=("files",),
            produces=("symbols", "imports", "call_edges", "class_heritage", "variables"),
            hooks=("on_file_parsed",),
        ),
        PythonParser,
    )
