"""Value coercion and settings-layer application helpers."""
from __future__ import annotations

import json
from typing import Any

from repograph.observability import get_logger

from ._constants import SETTINGS_FILENAME
from ._schema import SETTING_SPECS, Settings, get_setting_spec

_logger = get_logger(__name__, subsystem="settings")
_SKIP_SETTING = object()


def _normalize_top_level_dir(value: str) -> str:
    cleaned = str(value).strip().strip("/")
    if not cleaned:
        raise ValueError("directory names must not be empty")
    if "/" in cleaned or ".." in cleaned:
        raise ValueError("directory names must be top-level names without '/' or '..'")
    return cleaned


def _coerce_bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ValueError("expected a boolean value")


def _coerce_int_value(value: Any, *, min_value: int | None = None) -> int:
    if isinstance(value, bool):
        raise ValueError("expected an integer, not a boolean")
    if isinstance(value, int):
        out = value
    elif isinstance(value, str) and value.strip():
        out = int(value.strip())
    else:
        raise ValueError("expected an integer value")
    if min_value is not None and out < min_value:
        raise ValueError(f"expected an integer >= {min_value}")
    return out


def _coerce_string_value(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("expected a string value")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("string value must not be empty")
    return cleaned


def _coerce_exclude_dirs_value(value: Any) -> list[str]:
    raw = value
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = [value]
    if raw is None or not isinstance(raw, list):
        raise ValueError("expected a list of top-level directory names")
    return list(dict.fromkeys(_normalize_top_level_dir(item) for item in raw))


def _coerce_command_list_value(
    value: Any,
    *,
    key: str,
    allow_none: bool,
    allow_empty: bool,
) -> list[str] | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{key} must not be null")
    raw = value
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                "expected a JSON array of command arguments, e.g. "
                '[\"python\", \"-m\", \"pytest\", \"tests\"]'
            ) from exc
    if not isinstance(raw, list):
        raise ValueError("expected a list of command arguments or null")
    if not raw and not allow_empty:
        raise ValueError(
            f"{key} must not be empty; use unset/null to restore auto-detection"
        )
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} entries must be non-empty strings")
        out.append(item.strip())
    return out


def _coerce_string_list_value(
    value: Any,
    *,
    key: str,
    allow_empty: bool = True,
) -> list[str]:
    raw = value
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = [value]
    if raw is None or not isinstance(raw, list):
        raise ValueError(f"{key} must be a list of strings")
    if not raw and not allow_empty:
        raise ValueError(f"{key} must not be empty")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} entries must be non-empty strings")
        out.append(item.strip())
    return out


def _coerce_http_url_value(value: Any, *, key: str, allow_none: bool) -> str | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{key} must not be null")
    cleaned = _coerce_string_value(value)
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise ValueError(f"{key} must be an absolute http:// or https:// URL")
    return cleaned


def _coerce_runtime_attach_policy(value: Any) -> str:
    cleaned = _coerce_string_value(value).lower()
    if cleaned not in {"prompt", "always", "never"}:
        raise ValueError('expected one of "prompt", "always", or "never"')
    return cleaned


def coerce_setting_value(key: str, value: Any) -> Any:
    """Coerce and validate a single setting value."""
    get_setting_spec(key)

    if key == "exclude_dirs":
        return _coerce_exclude_dirs_value(value)
    if key in {
        "disable_auto_excludes",
        "include_git",
        "include_embeddings",
        "auto_dynamic_analysis",
        "doc_symbols_flag_unknown",
    }:
        return _coerce_bool_value(value)
    if key == "sync_test_command":
        return _coerce_command_list_value(
            value,
            key="sync_test_command",
            allow_none=True,
            allow_empty=False,
        )
    if key == "sync_runtime_server_command":
        return _coerce_command_list_value(
            value,
            key="sync_runtime_server_command",
            allow_none=True,
            allow_empty=False,
        )
    if key == "sync_runtime_probe_url":
        return _coerce_http_url_value(value, key="sync_runtime_probe_url", allow_none=True)
    if key == "sync_runtime_scenario_urls":
        return _coerce_string_list_value(
            value,
            key="sync_runtime_scenario_urls",
            allow_empty=True,
        )
    if key == "sync_runtime_scenario_driver_command":
        return _coerce_command_list_value(
            value,
            key="sync_runtime_scenario_driver_command",
            allow_none=True,
            allow_empty=False,
        )
    if key == "sync_runtime_ready_timeout":
        return _coerce_int_value(value, min_value=1)
    if key == "sync_runtime_attach_policy":
        return _coerce_runtime_attach_policy(value)
    if key == "context_tokens":
        return _coerce_int_value(value, min_value=1)
    if key == "git_days":
        return _coerce_int_value(value, min_value=0)
    if key == "entry_point_limit":
        return _coerce_int_value(value, min_value=1)
    if key == "min_community_size":
        return _coerce_int_value(value, min_value=1)
    if key == "nl_model":
        return _coerce_string_value(value)

    raise KeyError(f"Unknown setting coercion path for {key!r}")


def _coerce_setting_value_for_source(key: str, value: Any, *, source: str) -> Any:
    try:
        return coerce_setting_value(key, value)
    except (TypeError, ValueError) as exc:
        _logger.warning(
            "settings mapping: bad value for key, ignored",
            source=source,
            key=key,
            value=repr(value),
            expected=get_setting_spec(key).type_name,
            reason=str(exc),
        )
        return _SKIP_SETTING


def apply_settings_mapping(
    settings: Settings,
    stored: dict[str, Any],
    *,
    merge_exclude_dirs: bool,
    source: str,
) -> None:
    """Apply key/value pairs from *stored* onto *settings* in-place."""
    unknown_keys = sorted(set(stored.keys()) - set(SETTING_SPECS))
    for key in unknown_keys:
        _logger.warning(
            "settings mapping: unknown key ignored",
            source=source,
            key=key,
        )

    for key in SETTING_SPECS:
        if key not in stored:
            continue
        coerced = _coerce_setting_value_for_source(key, stored[key], source=source)
        if coerced is _SKIP_SETTING:
            continue
        if key == "exclude_dirs":
            if merge_exclude_dirs:
                settings.exclude_dirs = list(
                    dict.fromkeys(settings.exclude_dirs + coerced)
                )
            else:
                settings.exclude_dirs = coerced
            continue
        setattr(settings, key, coerced)


def apply_stored_settings(settings: Settings, stored: dict[str, Any]) -> None:
    """Apply runtime overrides from ``settings.json`` onto *settings* in-place."""
    apply_settings_mapping(
        settings,
        stored,
        merge_exclude_dirs=False,
        source=SETTINGS_FILENAME,
    )
