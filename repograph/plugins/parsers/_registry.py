"""Parser plugin registry — thin re-export of the existing registry."""
from repograph.plugins.parsers.registry import (
    get_registry,
    register_parser,
    ensure_default_parsers_registered,
    get_parser_plugin,
    supported_languages,
    parse_file,
)
__all__ = [
    "get_registry", "register_parser", "ensure_default_parsers_registered",
    "get_parser_plugin", "supported_languages", "parse_file",
]
