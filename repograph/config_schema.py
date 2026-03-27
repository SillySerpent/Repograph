"""JSON schema for repograph.index.yaml.

Validation is intentionally lenient: unknown keys emit a WARNING (not ERROR)
so that forward-compatible configs work across versions.  Only structural
errors (wrong type, invalid constraint) produce an ERROR.
"""
from __future__ import annotations

INDEX_YAML_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "exclude_dirs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Top-level directory names to skip during file walk.",
        },
        "disable_auto_excludes": {
            "type": "boolean",
            "description": "When true, skip automatic exclusion of vendored repograph copies.",
        },
        "doc_symbols_flag_unknown": {
            "type": "boolean",
            "description": "When true, Phase 15 flags unknown qualified symbol references.",
        },
    },
    # Allow additional keys so forward-compatible configs don't hard-fail,
    # but we warn on them in the validation helper below.
    "additionalProperties": True,
}

_KNOWN_KEYS: frozenset[str] = frozenset(INDEX_YAML_SCHEMA["properties"].keys())


def validate_index_yaml(data: dict, path: str, logger) -> None:
    """Validate *data* against :data:`INDEX_YAML_SCHEMA`.

    Logs at WARNING for unknown keys and at ERROR for structural violations.
    Does not raise — validation is advisory only so a bad config file never
    prevents a sync.
    """
    try:
        import jsonschema
    except ImportError:
        return  # optional dependency not installed — skip validation

    try:
        jsonschema.validate(data, INDEX_YAML_SCHEMA)
    except jsonschema.ValidationError as exc:
        logger.error(
            "repograph.index.yaml has an invalid structure — some settings may be ignored",
            path=path,
            schema_error=exc.message,
        )
        return

    # Warn on any keys not in the known set (typos, removed options, etc.)
    unknown = sorted(set(data.keys()) - _KNOWN_KEYS)
    for key in unknown:
        logger.warning(
            "unknown key in repograph.index.yaml — check for typos or outdated config",
            path=path,
            key=key,
        )
