"""Base parser protocol and tree-sitter utilities shared across all language parsers."""
from __future__ import annotations

from abc import ABC, abstractmethod

import tree_sitter as ts

from repograph.core.models import ParsedFile, FileRecord


class BaseParser(ABC):
    """Protocol that all language parsers must implement."""

    language_name: str = ""

    def __init__(self) -> None:
        self._parser: ts.Parser | None = None

    @property
    def parser(self) -> ts.Parser:
        if self._parser is None:
            self._parser = self._build_parser()
        return self._parser

    @abstractmethod
    def _build_parser(self) -> ts.Parser:
        """Return a configured tree-sitter Parser for this language."""
        ...

    @abstractmethod
    def parse(self, source: bytes, file_record: FileRecord) -> ParsedFile:
        """
        Parse source bytes into a ParsedFile with all extracted entities.
        Must never raise — catch internal errors and return partial results.
        """
        ...

    def parse_file(self, file_record: FileRecord) -> ParsedFile:
        """Read file from disk and parse it."""
        try:
            with open(file_record.abs_path, "rb") as f:
                source = f.read()
        except (OSError, PermissionError) as e:
            # Return empty parse result on unreadable file
            return ParsedFile(file_record=file_record)
        return self.parse(source, file_record)


# ---------------------------------------------------------------------------
# Shared tree walking helpers
# ---------------------------------------------------------------------------

def find_all_nodes(node: ts.Node, type_name: str) -> list[ts.Node]:
    """Depth-first search for all nodes of a given type."""
    results: list[ts.Node] = []
    if node.type == type_name:
        results.append(node)
    for child in node.children:
        results.extend(find_all_nodes(child, type_name))
    return results


def find_all_nodes_multi(node: ts.Node, type_names: set[str]) -> list[ts.Node]:
    """Find all nodes whose type is in the given set."""
    results: list[ts.Node] = []
    if node.type in type_names:
        results.append(node)
    for child in node.children:
        results.extend(find_all_nodes_multi(child, type_names))
    return results


def node_text(node: ts.Node, source: bytes) -> str:
    """Get raw text for a node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def child_text(node: ts.Node, field_name: str, source: bytes) -> str | None:
    """Get text of a named field child, or None."""
    child = node.child_by_field_name(field_name)
    if child is None:
        return None
    return node_text(child, source)


def first_child_of_type(node: ts.Node, type_name: str) -> ts.Node | None:
    """Find first direct child with the given type."""
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def get_docstring(body_node: ts.Node, source: bytes) -> str | None:
    """
    Extract docstring from a function/class body node.
    The docstring is the first expression_statement whose child is a string.
    """
    if body_node is None:
        return None
    for child in body_node.children:
        if child.type == "expression_statement":
            for subchild in child.children:
                if subchild.type == "string":
                    raw = node_text(subchild, source)
                    # Strip quotes
                    return _strip_docstring_quotes(raw)
    return None


def _strip_docstring_quotes(raw: str) -> str:
    """Remove surrounding quote characters from a docstring literal."""
    s = raw.strip()
    for triple in ('"""', "'''"):
        if s.startswith(triple) and s.endswith(triple) and len(s) > 6:
            return s[3:-3].strip()
    for single in ('"', "'"):
        if s.startswith(single) and s.endswith(single) and len(s) > 2:
            return s[1:-1].strip()
    return s
