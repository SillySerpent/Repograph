from __future__ import annotations

import threading

from repograph.core.models import FileRecord, ParsedFile
from repograph.core.plugin_framework import ParserPlugin, PluginManifest, PluginRegistry
from repograph.plugins.discovery import PARSER_ORDER, iter_build_plugins
from repograph.plugins.lifecycle import get_hook_scheduler
from repograph.plugins.parsers.base import ParserAdapter

_PARSER_REGISTRY: PluginRegistry[ParserPlugin] = PluginRegistry("parser")
_LANGUAGE_TO_PLUGIN: dict[str, str] = {}
_DEFAULTS_REGISTERED = False
_DEFAULTS_LOCK = threading.Lock()


def get_registry() -> PluginRegistry[ParserPlugin]:
    ensure_default_parsers_registered()
    return _PARSER_REGISTRY


def register_parser(plugin: ParserPlugin, *, replace: bool = False) -> None:
    _PARSER_REGISTRY.register(plugin, replace=replace)
    for language in plugin.supported_languages():
        if language in _LANGUAGE_TO_PLUGIN and not replace:
            raise ValueError(f"language '{language}' already mapped to parser plugin '{_LANGUAGE_TO_PLUGIN[language]}'")
        _LANGUAGE_TO_PLUGIN[language] = plugin.plugin_id()


def get_parser_plugin(language: str) -> ParserPlugin | None:
    ensure_default_parsers_registered()
    plugin_id = _LANGUAGE_TO_PLUGIN.get(language)
    if plugin_id is None:
        return None
    return _PARSER_REGISTRY.get(plugin_id)


def parse_file(file_record: FileRecord) -> ParsedFile:
    plugin = get_parser_plugin(file_record.language)
    if plugin is None:
        parsed = ParsedFile(file_record=file_record)
    else:
        parsed = plugin.parse_file(file_record)

    scheduler = get_hook_scheduler()
    for execution in scheduler.run_hook(
        "on_file_parsed",
        kind="framework_adapter",
        file_record=file_record,
        parsed_file=parsed,
    ):
        result = execution.result or {}
        if not isinstance(result, dict):
            continue
        frameworks = result.get("frameworks", []) or []
        for framework in frameworks:
            if framework not in parsed.framework_hints:
                parsed.framework_hints.append(framework)
        parsed.plugin_artifacts[execution.plugin_id] = result
    return parsed


def supported_languages() -> list[str]:
    ensure_default_parsers_registered()
    return sorted(_LANGUAGE_TO_PLUGIN.keys())


def parser_manifests() -> list[dict]:
    ensure_default_parsers_registered()
    return _PARSER_REGISTRY.manifests()


def ensure_default_parsers_registered() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    with _DEFAULTS_LOCK:
        if _DEFAULTS_REGISTERED:
            return
        for build in iter_build_plugins(
            "repograph.plugins.parsers",
            PARSER_ORDER,
            skip_import_error=True,
        ):
            register_parser(build())
        _DEFAULTS_REGISTERED = True
