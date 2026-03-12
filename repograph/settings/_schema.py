"""Settings dataclasses, schema metadata, and YAML validation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from repograph.runtime.session import RuntimeAttachPolicy

from ._constants import (
    DEFAULT_CONTEXT_TOKENS,
    DEFAULT_ENTRY_POINT_LIMIT,
    DEFAULT_GIT_DAYS,
    DEFAULT_MIN_COMMUNITY_SIZE,
)


@dataclass
class Settings:
    """All configurable RepoGraph settings with their defaults."""

    exclude_dirs: list[str] = field(default_factory=list)
    disable_auto_excludes: bool = False
    include_git: bool = True
    include_embeddings: bool = False
    auto_dynamic_analysis: bool = True
    sync_test_command: list[str] | None = None
    sync_runtime_server_command: list[str] | None = None
    sync_runtime_probe_url: str | None = None
    sync_runtime_scenario_urls: list[str] = field(default_factory=list)
    sync_runtime_scenario_driver_command: list[str] | None = None
    sync_runtime_ready_timeout: int = 15
    sync_runtime_attach_policy: RuntimeAttachPolicy = "prompt"
    doc_symbols_flag_unknown: bool = False
    context_tokens: int = DEFAULT_CONTEXT_TOKENS
    git_days: int = DEFAULT_GIT_DAYS
    entry_point_limit: int = DEFAULT_ENTRY_POINT_LIMIT
    min_community_size: int = DEFAULT_MIN_COMMUNITY_SIZE
    nl_model: str = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class SettingSpec:
    """Metadata and lifecycle information for a single setting."""

    key: str
    type_name: str
    default: Any
    description: str
    takes_effect: str
    requires_reindex: bool = False
    requires_full_sync: bool = False
    affects_runtime_only: bool = False
    stability: str = "stable"
    allow_none: bool = False

    def to_dict(self, *, current: Any = None, include_current: bool = False) -> dict[str, Any]:
        payload = {
            "key": self.key,
            "type": self.type_name,
            "default": deepcopy(self.default),
            "value_shape": _setting_value_shape(self.key, self.type_name),
            "allowed_values": deepcopy(_setting_allowed_values(self.type_name)),
            "examples": deepcopy(_setting_examples(self.key)),
            "description": self.description,
            "takes_effect": self.takes_effect,
            "requires_reindex": self.requires_reindex,
            "requires_full_sync": self.requires_full_sync,
            "affects_runtime_only": self.affects_runtime_only,
            "stability": self.stability,
        }
        if include_current:
            payload["current"] = deepcopy(current)
        return payload


@dataclass(frozen=True)
class ResolvedRuntimeSettings:
    """Effective runtime settings after explicit overrides are applied."""

    settings: Settings
    include_git: bool
    include_embeddings: bool
    auto_dynamic_analysis: bool
    max_context_tokens: int
    git_days: int
    entry_point_limit: int
    min_community_size: int


DEFAULT_SETTINGS = Settings()

_SETTING_VALUE_SHAPES: dict[str, str] = {
    "exclude_dirs": "JSON array of top-level directory names",
    "disable_auto_excludes": "boolean",
    "include_git": "boolean",
    "include_embeddings": "boolean",
    "auto_dynamic_analysis": "boolean",
    "sync_test_command": "null or JSON array of command arguments",
    "sync_runtime_server_command": "null or JSON array of command arguments",
    "sync_runtime_probe_url": "null or absolute http(s) URL",
    "sync_runtime_scenario_urls": "JSON array of absolute URLs or path fragments",
    "sync_runtime_scenario_driver_command": "null or JSON array of command arguments",
    "sync_runtime_ready_timeout": "integer >= 1",
    "sync_runtime_attach_policy": 'one of "prompt", "always", "never"',
    "doc_symbols_flag_unknown": "boolean",
    "context_tokens": "integer >= 1",
    "git_days": "integer >= 0",
    "entry_point_limit": "integer >= 1",
    "min_community_size": "integer >= 1",
    "nl_model": "non-empty string",
}

_SETTING_EXAMPLES: dict[str, list[Any]] = {
    "exclude_dirs": [["vendor", "dist"]],
    "disable_auto_excludes": [False, True],
    "include_git": [True, False],
    "include_embeddings": [False, True],
    "auto_dynamic_analysis": [True, False],
    "sync_test_command": [None, ["python", "-m", "pytest", "tests"]],
    "sync_runtime_server_command": [None, ["python", "app.py"]],
    "sync_runtime_probe_url": [None, "http://127.0.0.1:8000/health"],
    "sync_runtime_scenario_urls": [[], ["/", "/health"]],
    "sync_runtime_scenario_driver_command": [None, ["python", "tools/runtime_driver.py"]],
    "sync_runtime_ready_timeout": [15, 30],
    "sync_runtime_attach_policy": ["prompt", "always", "never"],
    "doc_symbols_flag_unknown": [False, True],
    "context_tokens": [2000, 4000],
    "git_days": [180, 30],
    "entry_point_limit": [20, 10],
    "min_community_size": [3, 5],
    "nl_model": ["claude-haiku-4-5-20251001", "claude-opus-4-6"],
}


def _setting_value_shape(key: str, type_name: str) -> str:
    return _SETTING_VALUE_SHAPES.get(key, type_name)


def _setting_allowed_values(type_name: str) -> list[Any] | None:
    if type_name == "bool":
        return [True, False]
    if type_name == "runtime_attach_policy":
        return ["prompt", "always", "never"]
    return None


def _setting_examples(key: str) -> list[Any]:
    return deepcopy(_SETTING_EXAMPLES.get(key, []))


SETTING_SPECS: dict[str, SettingSpec] = {
    "exclude_dirs": SettingSpec(
        key="exclude_dirs",
        type_name="list[str]",
        default=list(DEFAULT_SETTINGS.exclude_dirs),
        description="Top-level directory names to skip during the file walk.",
        takes_effect="next_sync",
        requires_reindex=True,
    ),
    "disable_auto_excludes": SettingSpec(
        key="disable_auto_excludes",
        type_name="bool",
        default=DEFAULT_SETTINGS.disable_auto_excludes,
        description="Disable automatic vendored-RepoGraph exclusion.",
        takes_effect="next_sync",
        requires_reindex=True,
    ),
    "include_git": SettingSpec(
        key="include_git",
        type_name="bool",
        default=DEFAULT_SETTINGS.include_git,
        description="Include git-history coupling analysis during sync.",
        takes_effect="next_sync",
        requires_reindex=True,
    ),
    "include_embeddings": SettingSpec(
        key="include_embeddings",
        type_name="bool",
        default=DEFAULT_SETTINGS.include_embeddings,
        description="Generate semantic-search embeddings during sync.",
        takes_effect="next_full_sync",
        requires_reindex=True,
        requires_full_sync=True,
    ),
    "auto_dynamic_analysis": SettingSpec(
        key="auto_dynamic_analysis",
        type_name="bool",
        default=DEFAULT_SETTINGS.auto_dynamic_analysis,
        description="Allow `repograph sync --full` to run automatic runtime analysis when a supported signal exists.",
        takes_effect="next_full_sync",
        requires_full_sync=True,
        affects_runtime_only=True,
    ),
    "sync_test_command": SettingSpec(
        key="sync_test_command",
        type_name="list[str] | null",
        default=DEFAULT_SETTINGS.sync_test_command,
        description="Exact argv override for the traced test command used by CLI full sync.",
        takes_effect="next_full_sync",
        requires_full_sync=True,
        affects_runtime_only=True,
        allow_none=True,
    ),
    "sync_runtime_server_command": SettingSpec(
        key="sync_runtime_server_command",
        type_name="list[str] | null",
        default=DEFAULT_SETTINGS.sync_runtime_server_command,
        description="Optional Python server argv to run under trace before driving runtime HTTP scenarios.",
        takes_effect="next_full_sync",
        requires_full_sync=True,
        affects_runtime_only=True,
        allow_none=True,
    ),
    "sync_runtime_probe_url": SettingSpec(
        key="sync_runtime_probe_url",
        type_name="str | null",
        default=DEFAULT_SETTINGS.sync_runtime_probe_url,
        description="HTTP URL used to detect readiness for a managed traced runtime server.",
        takes_effect="next_full_sync",
        requires_full_sync=True,
        affects_runtime_only=True,
        allow_none=True,
    ),
    "sync_runtime_scenario_urls": SettingSpec(
        key="sync_runtime_scenario_urls",
        type_name="list[str]",
        default=list(DEFAULT_SETTINGS.sync_runtime_scenario_urls),
        description="Ordered HTTP URLs or path fragments to request once a managed traced runtime server is ready.",
        takes_effect="next_full_sync",
        requires_full_sync=True,
        affects_runtime_only=True,
    ),
    "sync_runtime_scenario_driver_command": SettingSpec(
        key="sync_runtime_scenario_driver_command",
        type_name="list[str] | null",
        default=DEFAULT_SETTINGS.sync_runtime_scenario_driver_command,
        description="Optional scenario-driver argv to run after the managed traced runtime server is ready.",
        takes_effect="next_full_sync",
        requires_full_sync=True,
        affects_runtime_only=True,
        allow_none=True,
    ),
    "sync_runtime_ready_timeout": SettingSpec(
        key="sync_runtime_ready_timeout",
        type_name="int",
        default=DEFAULT_SETTINGS.sync_runtime_ready_timeout,
        description="Seconds to wait for a managed traced runtime server to become reachable.",
        takes_effect="next_full_sync",
        requires_full_sync=True,
        affects_runtime_only=True,
    ),
    "sync_runtime_attach_policy": SettingSpec(
        key="sync_runtime_attach_policy",
        type_name="runtime_attach_policy",
        default=DEFAULT_SETTINGS.sync_runtime_attach_policy,
        description="How full sync handles an attachable live runtime target: prompt in CLI sessions, always attach automatically, or never attach and fall back.",
        takes_effect="next_full_sync",
        requires_full_sync=True,
        affects_runtime_only=True,
    ),
    "doc_symbols_flag_unknown": SettingSpec(
        key="doc_symbols_flag_unknown",
        type_name="bool",
        default=DEFAULT_SETTINGS.doc_symbols_flag_unknown,
        description="Flag unknown qualified symbol references during doc validation.",
        takes_effect="next_sync",
        requires_reindex=True,
    ),
    "context_tokens": SettingSpec(
        key="context_tokens",
        type_name="int",
        default=DEFAULT_SETTINGS.context_tokens,
        description="Token budget for generated pathway context documents.",
        takes_effect="next_sync",
        requires_reindex=True,
    ),
    "git_days": SettingSpec(
        key="git_days",
        type_name="int",
        default=DEFAULT_SETTINGS.git_days,
        description="How many days of git history to consider for coupling analysis.",
        takes_effect="next_sync",
        requires_reindex=True,
    ),
    "entry_point_limit": SettingSpec(
        key="entry_point_limit",
        type_name="int",
        default=DEFAULT_SETTINGS.entry_point_limit,
        description="Default limit used when listing entry points without an explicit limit.",
        takes_effect="immediate",
    ),
    "min_community_size": SettingSpec(
        key="min_community_size",
        type_name="int",
        default=DEFAULT_SETTINGS.min_community_size,
        description="Minimum detected community size to persist.",
        takes_effect="next_sync",
        requires_reindex=True,
    ),
    "nl_model": SettingSpec(
        key="nl_model",
        type_name="str",
        default=DEFAULT_SETTINGS.nl_model,
        description="Model name used for natural-language graph querying.",
        takes_effect="immediate",
    ),
}


def get_setting_spec(key: str) -> SettingSpec:
    """Return the metadata record for *key* or raise a helpful ``KeyError``."""
    spec = SETTING_SPECS.get(key)
    if spec is None:
        raise KeyError(
            f"Unknown setting {key!r}. "
            f"Known settings: {', '.join(sorted(SETTING_SPECS))}"
        )
    return spec


def _schema_property_for_spec(spec: SettingSpec) -> dict[str, Any]:
    if spec.type_name.startswith("list["):
        return {
            "type": "array",
            "items": {"type": "string"},
            "description": spec.description,
        }
    if spec.type_name == "bool":
        return {"type": "boolean", "description": spec.description}
    if spec.type_name == "int":
        return {"type": "integer", "description": spec.description}
    return {"type": "string", "description": spec.description}


INDEX_YAML_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        key: _schema_property_for_spec(spec)
        for key, spec in SETTING_SPECS.items()
    },
    "additionalProperties": True,
}

_KNOWN_YAML_KEYS: frozenset[str] = frozenset(SETTING_SPECS.keys())


def validate_index_yaml(data: dict, path: str, logger) -> None:
    """Validate *data* against :data:`INDEX_YAML_SCHEMA`."""
    try:
        import jsonschema
    except ImportError:
        return

    try:
        jsonschema.validate(data, INDEX_YAML_SCHEMA)
    except jsonschema.ValidationError as exc:
        logger.error(
            "repograph.index.yaml has an invalid structure — some settings may be ignored",
            path=path,
            schema_error=exc.message,
        )
        return

    unknown = sorted(set(data.keys()) - _KNOWN_YAML_KEYS)
    for key in unknown:
        logger.warning(
            "unknown key in repograph.index.yaml — check for typos or outdated config",
            path=path,
            key=key,
        )
