from __future__ import annotations

from typing import Callable

from repograph.core.models import FileRecord, ParsedFile
from repograph.core.plugin_framework import ParserPlugin, PluginManifest
from repograph.parsing.base import BaseParser


class ParserAdapter(ParserPlugin):
    """Adapter that exposes an existing ``BaseParser`` as a ``ParserPlugin``."""

    def __init__(
        self,
        manifest: PluginManifest,
        parser_factory: Callable[[], BaseParser],
    ) -> None:
        self.manifest = manifest
        self._parser_factory = parser_factory
        self._parser: BaseParser | None = None

    @property
    def parser(self) -> BaseParser:
        if self._parser is None:
            self._parser = self._parser_factory()
        return self._parser

    def parse_file(self, file_record: FileRecord) -> ParsedFile:
        return self.parser.parse_file(file_record)
