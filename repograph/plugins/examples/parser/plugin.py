"""REFERENCE ONLY — not registered in production.

How to implement a parser plugin
--------------------------------
1. Subclass ``ParserPlugin`` (or wrap a ``BaseParser`` via ``ParserAdapter`` in
   ``repograph.plugins.parsers.base`` — see ``plugins/parsers/python/plugin.py``).
2. Set ``manifest.kind`` to ``"parser"`` and list handled languages in
   ``manifest.languages``.
3. Declare ``hooks=("on_file_parsed",)``. The scheduler calls ``parse_file`` for each
   file whose ``FileRecord.language`` maps to this plugin.
4. ``parse_file`` must return a ``ParsedFile``; on failure, return an empty
   ``ParsedFile(file_record=file_record)`` rather than raising.
5. Register: add your package name to ``PARSER_ORDER`` in ``discovery.py`` and ship tests.

This stub uses language ``"example"`` so it never matches real files unless you
extend the file walk to emit that language.
"""
from __future__ import annotations

from repograph.core.models import FileRecord, ParsedFile
from repograph.core.plugin_framework import ParserPlugin, PluginManifest


class ExampleParserPlugin(ParserPlugin):
    """Minimal parser — returns an empty graph for the file."""

    manifest = PluginManifest(
        id="parser.example_reference",
        name="Example parser (reference)",
        kind="parser",
        description="Reference stub — not used in production.",
        languages=("example",),
        requires=("files",),
        produces=("symbols",),
        hooks=("on_file_parsed",),
    )

    def parse_file(self, file_record: FileRecord) -> ParsedFile:
        return ParsedFile(file_record=file_record)


def build_plugin() -> ExampleParserPlugin:
    """Entry point used by discovery for real parsers."""
    return ExampleParserPlugin()
