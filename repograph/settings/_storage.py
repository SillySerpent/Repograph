"""Settings document, persistence, and runtime-loading helpers."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from repograph.observability import get_logger

from ._coercion import apply_settings_mapping, apply_stored_settings, coerce_setting_value
from ._constants import (
    INDEX_CONFIG_FILENAME,
    SETTINGS_DOCUMENT_VERSION,
    SETTINGS_FILENAME,
)
from ._paths import repograph_dir
from ._schema import (
    DEFAULT_SETTINGS,
    INDEX_YAML_SCHEMA,
    ResolvedRuntimeSettings,
    SETTING_SPECS,
    Settings,
    get_setting_spec,
    validate_index_yaml,
)

_logger = get_logger(__name__, subsystem="settings")


def _read_index_yaml(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        import yaml

        with open(path, encoding="utf-8", errors="replace") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception as exc:
        _logger.warning(
            "could not load index YAML — config file will be ignored",
            path=path,
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )
        return None

    if isinstance(data, dict):
        validate_index_yaml(data, path, _logger)
    return data


def _exclude_dirs_from_mapping(data: dict[str, Any]) -> set[str]:
    raw = data.get("exclude_dirs") or []
    out: set[str] = set()
    for item in raw:
        cleaned = str(item).strip().strip("/")
        if cleaned and "/" not in cleaned and ".." not in cleaned:
            out.add(cleaned)
    return out


def _default_embedded_repograph_exclude(repo_root: str) -> set[str]:
    inner = os.path.join(repo_root, "repograph", "pyproject.toml")
    if os.path.isfile(inner):
        return {"repograph"}
    return set()


def _settings_json_path(repo_root: str) -> str:
    return os.path.join(repograph_dir(repo_root), SETTINGS_FILENAME)


def _read_settings_payload(json_path: str) -> dict[str, Any]:
    if not os.path.isfile(json_path):
        return {}
    try:
        with open(json_path, encoding="utf-8") as handle:
            payload = json.load(handle) or {}
    except Exception as exc:
        _logger.warning(
            "could not load settings.json — runtime overrides ignored",
            path=json_path,
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )
        return {}
    if not isinstance(payload, dict):
        _logger.warning(
            "settings.json must contain a JSON object — runtime overrides ignored",
            path=json_path,
            payload_type=type(payload).__name__,
        )
        return {}
    return payload


def _extract_runtime_overrides(payload: dict[str, Any]) -> dict[str, Any]:
    runtime_overrides = payload.get("runtime_overrides")
    if isinstance(runtime_overrides, dict):
        return deepcopy(runtime_overrides)

    document_keys = {
        "document_version",
        "generated_at",
        "repo_root",
        "editable_section",
        "notes",
        "runtime_overrides",
        "effective_values",
        "setting_catalog",
    }
    if any(key in payload for key in document_keys):
        return {}
    return deepcopy(payload)


def _load_runtime_overrides(repo_root: str) -> dict[str, Any]:
    return _extract_runtime_overrides(_read_settings_payload(_settings_json_path(repo_root)))


def _layer_has_valid_value(data: dict[str, Any], key: str) -> bool:
    if key not in data:
        return False
    try:
        coerce_setting_value(key, data[key])
    except (TypeError, ValueError):
        return False
    return True


def _setting_source_details(
    *,
    key: str,
    repo_root_yaml: dict[str, Any],
    repograph_yaml: dict[str, Any],
    runtime_overrides: dict[str, Any],
    repo_root: str,
) -> tuple[str, list[str]]:
    if _layer_has_valid_value(runtime_overrides, key):
        return "runtime_override", [_settings_json_path(repo_root)]

    yaml_sources: list[str] = []
    root_yaml_path = os.path.join(repo_root, INDEX_CONFIG_FILENAME)
    repograph_yaml_path = os.path.join(repograph_dir(repo_root), INDEX_CONFIG_FILENAME)
    if _layer_has_valid_value(repo_root_yaml, key):
        yaml_sources.append(root_yaml_path)
    if _layer_has_valid_value(repograph_yaml, key):
        yaml_sources.append(repograph_yaml_path)
    if not yaml_sources:
        return "default", []
    if len(yaml_sources) == 1:
        source = "repo_root_yaml" if yaml_sources[0] == root_yaml_path else "repograph_yaml"
        return source, yaml_sources
    return "merged_yaml", yaml_sources


def _resolve_settings_layers(
    repo_root: str,
    *,
    runtime_overrides: dict[str, Any] | None = None,
) -> tuple[Settings, dict[str, Any], dict[str, Any]]:
    settings = Settings()
    repo_root_yaml_path = os.path.join(repo_root, INDEX_CONFIG_FILENAME)
    repograph_yaml_path = os.path.join(repograph_dir(repo_root), INDEX_CONFIG_FILENAME)
    repo_root_yaml = _read_index_yaml(repo_root_yaml_path) or {}
    repograph_yaml = _read_index_yaml(repograph_yaml_path) or {}

    apply_settings_mapping(
        settings,
        repo_root_yaml,
        merge_exclude_dirs=True,
        source=os.path.basename(repo_root_yaml_path) or INDEX_CONFIG_FILENAME,
    )
    apply_settings_mapping(
        settings,
        repograph_yaml,
        merge_exclude_dirs=True,
        source=os.path.basename(repograph_yaml_path) or INDEX_CONFIG_FILENAME,
    )

    resolved_overrides = (
        deepcopy(runtime_overrides)
        if runtime_overrides is not None
        else _load_runtime_overrides(repo_root)
    )
    apply_stored_settings(settings, resolved_overrides)

    layers = {
        "repo_root_yaml": repo_root_yaml,
        "repograph_yaml": repograph_yaml,
        "runtime_overrides": resolved_overrides,
    }
    return settings, layers, asdict(settings)


def build_settings_document(
    repo_root: str,
    *,
    runtime_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings, layers, effective_values = _resolve_settings_layers(
        repo_root,
        runtime_overrides=runtime_overrides,
    )
    catalog: dict[str, dict[str, Any]] = {}
    for key in sorted(SETTING_SPECS):
        source, source_paths = _setting_source_details(
            key=key,
            repo_root_yaml=layers["repo_root_yaml"],
            repograph_yaml=layers["repograph_yaml"],
            runtime_overrides=layers["runtime_overrides"],
            repo_root=repo_root,
        )
        entry = get_setting_spec(key).to_dict(
            current=effective_values.get(key),
            include_current=True,
        )
        entry["source"] = source
        entry["source_paths"] = source_paths
        entry["is_runtime_override"] = key in layers["runtime_overrides"]
        entry["runtime_override"] = deepcopy(layers["runtime_overrides"].get(key))
        catalog[key] = entry

    return {
        "document_version": SETTINGS_DOCUMENT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": os.path.abspath(repo_root),
        "editable_section": "runtime_overrides",
        "notes": [
            "Edit runtime_overrides directly or use `repograph config set KEY VALUE`.",
            "effective_values is the merged result of defaults, YAML, and runtime_overrides.",
            "setting_catalog documents current values, lifecycle details, and accepted value shapes.",
        ],
        "runtime_overrides": deepcopy(layers["runtime_overrides"]),
        "effective_values": effective_values,
        "setting_catalog": catalog,
    }


def _write_settings_document(
    repo_root: str,
    *,
    runtime_overrides: dict[str, Any] | None = None,
) -> str:
    json_path = _settings_json_path(repo_root)
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    payload = build_settings_document(repo_root, runtime_overrides=runtime_overrides)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return json_path


def ensure_settings_file(repo_root: str) -> str:
    """Ensure the self-describing settings document exists and is refreshed."""
    return _write_settings_document(repo_root)


def list_setting_metadata(repo_root: str | None = None) -> list[dict[str, Any]]:
    """Return metadata for all known settings."""
    if repo_root is None:
        return [
            get_setting_spec(key).to_dict(include_current=False)
            for key in sorted(SETTING_SPECS)
        ]
    document = build_settings_document(repo_root)
    catalog = document.get("setting_catalog") or {}
    return [catalog[key] for key in sorted(catalog)]


def describe_setting(repo_root: str | None, key: str) -> dict[str, Any]:
    """Return schema and current-value details for a single setting."""
    spec = get_setting_spec(key)
    if repo_root is None:
        return spec.to_dict(current=deepcopy(spec.default), include_current=True)
    document = build_settings_document(repo_root)
    catalog = document.get("setting_catalog") or {}
    return dict(catalog[key])


def load_settings(repo_root: str) -> Settings:
    """Load the effective settings for *repo_root*."""
    settings, _, _ = _resolve_settings_layers(repo_root)
    return settings


def resolve_runtime_settings(
    repo_root: str,
    *,
    include_git: bool | None = None,
    include_embeddings: bool | None = None,
    auto_dynamic_analysis: bool | None = None,
    max_context_tokens: int | None = None,
    git_days: int | None = None,
    entry_point_limit: int | None = None,
    min_community_size: int | None = None,
) -> ResolvedRuntimeSettings:
    """Return effective runtime settings with explicit overrides applied."""
    settings = load_settings(repo_root)

    def _resolve(explicit: Any, configured: Any, fallback: Any) -> Any:
        if explicit is not None:
            return explicit
        if configured is not None:
            return configured
        return fallback

    return ResolvedRuntimeSettings(
        settings=settings,
        include_git=bool(_resolve(include_git, settings.include_git, DEFAULT_SETTINGS.include_git)),
        include_embeddings=bool(
            _resolve(
                include_embeddings,
                settings.include_embeddings,
                DEFAULT_SETTINGS.include_embeddings,
            )
        ),
        auto_dynamic_analysis=bool(
            _resolve(
                auto_dynamic_analysis,
                settings.auto_dynamic_analysis,
                DEFAULT_SETTINGS.auto_dynamic_analysis,
            )
        ),
        max_context_tokens=int(
            _resolve(
                max_context_tokens,
                settings.context_tokens,
                DEFAULT_SETTINGS.context_tokens,
            )
        ),
        git_days=int(_resolve(git_days, settings.git_days, DEFAULT_SETTINGS.git_days)),
        entry_point_limit=int(
            _resolve(
                entry_point_limit,
                settings.entry_point_limit,
                DEFAULT_SETTINGS.entry_point_limit,
            )
        ),
        min_community_size=int(
            _resolve(
                min_community_size,
                settings.min_community_size,
                DEFAULT_SETTINGS.min_community_size,
            )
        ),
    )


def save_settings(repo_root: str, settings: Settings) -> None:
    """Persist an explicit runtime-override snapshot to ``settings.json``."""
    _write_settings_document(repo_root, runtime_overrides=asdict(settings))


def get_setting(repo_root: str, key: str) -> Any:
    """Return the effective value of *key* for *repo_root*."""
    settings_dict = asdict(load_settings(repo_root))
    get_setting_spec(key)
    return settings_dict[key]


def set_setting(repo_root: str, key: str, value: Any) -> None:
    """Persist a single runtime override to ``settings.json``."""
    get_setting_spec(key)
    stored = _load_runtime_overrides(repo_root)
    try:
        stored[key] = coerce_setting_value(key, value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid value for setting {key!r}: {exc}") from exc
    _write_settings_document(repo_root, runtime_overrides=stored)


def unset_setting(repo_root: str, key: str) -> None:
    """Remove a runtime override for *key* from ``settings.json``."""
    get_setting_spec(key)
    stored = _load_runtime_overrides(repo_root)
    stored.pop(key, None)
    _write_settings_document(repo_root, runtime_overrides=stored)


def reset_settings(repo_root: str) -> None:
    """Clear runtime overrides and refresh the settings document."""
    _write_settings_document(repo_root, runtime_overrides={})


def load_extra_exclude_dirs(repo_root: str) -> set[str]:
    """Return extra directory names to skip during the file walk."""
    settings = load_settings(repo_root)
    out: set[str] = set(settings.exclude_dirs)
    if not settings.disable_auto_excludes:
        out |= _default_embedded_repograph_exclude(repo_root)
    return out


def load_doc_symbol_options(repo_root: str) -> dict[str, Any]:
    """Return doc-symbol phase flags from effective settings."""
    settings = load_settings(repo_root)
    return {"doc_symbols_flag_unknown": settings.doc_symbols_flag_unknown}


def load_sync_test_command(repo_root: str) -> list[str] | None:
    settings = load_settings(repo_root)
    return settings.sync_test_command


def load_sync_runtime_server_command(repo_root: str) -> list[str] | None:
    settings = load_settings(repo_root)
    return settings.sync_runtime_server_command


def load_sync_runtime_probe_url(repo_root: str) -> str | None:
    settings = load_settings(repo_root)
    return settings.sync_runtime_probe_url


def load_sync_runtime_scenario_urls(repo_root: str) -> list[str]:
    settings = load_settings(repo_root)
    return list(settings.sync_runtime_scenario_urls)


def load_sync_runtime_scenario_driver_command(repo_root: str) -> list[str] | None:
    settings = load_settings(repo_root)
    return settings.sync_runtime_scenario_driver_command


def load_sync_runtime_ready_timeout(repo_root: str) -> int:
    settings = load_settings(repo_root)
    return int(settings.sync_runtime_ready_timeout)


def load_sync_runtime_attach_policy(repo_root: str) -> str:
    settings = load_settings(repo_root)
    return str(settings.sync_runtime_attach_policy)
