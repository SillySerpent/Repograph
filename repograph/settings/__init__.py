"""Unified settings package — paths, constants, and runtime configuration.

This is the single source of truth for all RepoGraph configuration.
Settings are layered in priority order (highest wins):

  1. ``runtime_overrides`` inside ``.repograph/settings.json`` — set via
     ``repograph config set`` (CLI), ``rg.set_config(key, value)`` (Python
     API), or the MCP ``set_config`` tool. Changes persist across runs.
  2. ``repograph.index.yaml`` in ``.repograph/`` — YAML overrides for power
     users who want version-controlled or team-shared tuning.
  3. ``repograph.index.yaml`` at the repository root — legacy location,
     still supported but discouraged (prefer the ``.repograph/`` location).
  4. Built-in defaults — always present, no setup required.

``.repograph/settings.json`` is a generated, self-describing settings document.
It keeps the editable runtime overrides separate from the current effective
values and per-setting schema metadata so the file stays useful to operators
without breaking the precedence model.
"""
from __future__ import annotations

from ._constants import (
    AGENT_GUIDE_MAX_FILE_READ_BYTES,
    DB_FILENAME,
    DEFAULT_CONTEXT_TOKENS,
    DEFAULT_ENTRY_POINT_LIMIT,
    DEFAULT_GIT_DAYS,
    DEFAULT_MIN_COMMUNITY_SIZE,
    DEFAULT_MODULE_EXPANSION_THRESHOLD,
    ERROR_TRUNCATION_CHARS,
    INDEX_CONFIG_FILENAME,
    LANGUAGE_EXTENSIONS,
    PREFETCH_CHUNK_SIZE,
    REPOGRAPH_DIR,
    SETTINGS_FILENAME,
)
from ._paths import db_path, get_repo_root, is_initialized, repograph_dir
from ._schema import (
    INDEX_YAML_SCHEMA,
    ResolvedRuntimeSettings,
    SettingSpec,
    Settings,
    SETTING_SPECS as _SETTING_SPECS,
    validate_index_yaml,
)
from ._storage import (
    _read_index_yaml,
    build_settings_document,
    describe_setting,
    ensure_settings_file,
    get_setting,
    list_setting_metadata,
    load_doc_symbol_options,
    load_extra_exclude_dirs,
    load_settings,
    load_sync_runtime_probe_url,
    load_sync_runtime_attach_policy,
    load_sync_runtime_ready_timeout,
    load_sync_runtime_scenario_driver_command,
    load_sync_runtime_scenario_urls,
    load_sync_runtime_server_command,
    load_sync_test_command,
    reset_settings,
    resolve_runtime_settings,
    save_settings,
    set_setting,
    unset_setting,
)

__all__ = [
    "REPOGRAPH_DIR",
    "INDEX_CONFIG_FILENAME",
    "SETTINGS_FILENAME",
    "DB_FILENAME",
    "DEFAULT_CONTEXT_TOKENS",
    "DEFAULT_GIT_DAYS",
    "DEFAULT_ENTRY_POINT_LIMIT",
    "DEFAULT_MIN_COMMUNITY_SIZE",
    "DEFAULT_MODULE_EXPANSION_THRESHOLD",
    "ERROR_TRUNCATION_CHARS",
    "AGENT_GUIDE_MAX_FILE_READ_BYTES",
    "PREFETCH_CHUNK_SIZE",
    "LANGUAGE_EXTENSIONS",
    "repograph_dir",
    "db_path",
    "get_repo_root",
    "is_initialized",
    "load_extra_exclude_dirs",
    "load_doc_symbol_options",
    "load_sync_test_command",
    "load_sync_runtime_server_command",
    "load_sync_runtime_probe_url",
    "load_sync_runtime_attach_policy",
    "load_sync_runtime_scenario_urls",
    "load_sync_runtime_scenario_driver_command",
    "load_sync_runtime_ready_timeout",
    "Settings",
    "ResolvedRuntimeSettings",
    "SettingSpec",
    "load_settings",
    "save_settings",
    "ensure_settings_file",
    "list_setting_metadata",
    "describe_setting",
    "get_setting",
    "set_setting",
    "unset_setting",
    "reset_settings",
    "resolve_runtime_settings",
    "INDEX_YAML_SCHEMA",
    "validate_index_yaml",
]
