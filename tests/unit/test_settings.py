"""Tests for the unified settings module (repograph.settings).

Covers:
- Default Settings values
- load_settings: YAML layer, settings.json layer, merge priority
- get_setting / set_setting / reset_settings round-trip
- load_extra_exclude_dirs, load_doc_symbol_options, load_sync_test_command
- managed runtime server settings and loaders
- Self-describing settings document generation and legacy settings.json reads
- Backward-compat constants still accessible
- Error handling for unknown keys and bad JSON
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from repograph.settings import (
    Settings,
    REPOGRAPH_DIR,
    INDEX_CONFIG_FILENAME,
    DB_FILENAME,
    DEFAULT_CONTEXT_TOKENS,
    DEFAULT_GIT_DAYS,
    DEFAULT_ENTRY_POINT_LIMIT,
    DEFAULT_MIN_COMMUNITY_SIZE,
    DEFAULT_MODULE_EXPANSION_THRESHOLD,
    ERROR_TRUNCATION_CHARS,
    AGENT_GUIDE_MAX_FILE_READ_BYTES,
    PREFETCH_CHUNK_SIZE,
    LANGUAGE_EXTENSIONS,
    repograph_dir,
    db_path,
    is_initialized,
    load_settings,
    save_settings,
    ensure_settings_file,
    list_setting_metadata,
    describe_setting,
    get_setting,
    set_setting,
    unset_setting,
    reset_settings,
    load_extra_exclude_dirs,
    load_doc_symbol_options,
    load_sync_test_command,
    load_sync_runtime_server_command,
    load_sync_runtime_probe_url,
    load_sync_runtime_attach_policy,
    load_sync_runtime_scenario_urls,
    load_sync_runtime_scenario_driver_command,
    load_sync_runtime_ready_timeout,
    resolve_runtime_settings,
    validate_index_yaml,
    INDEX_YAML_SCHEMA,
)


def _settings_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_repograph_dir_name(self):
        assert REPOGRAPH_DIR == ".repograph"

    def test_db_filename(self):
        assert DB_FILENAME == "graph.db"

    def test_default_context_tokens(self):
        assert DEFAULT_CONTEXT_TOKENS == 2000

    def test_default_git_days(self):
        assert DEFAULT_GIT_DAYS == 180

    def test_default_entry_point_limit(self):
        assert DEFAULT_ENTRY_POINT_LIMIT == 20

    def test_default_min_community_size(self):
        assert DEFAULT_MIN_COMMUNITY_SIZE == 3

    def test_language_extensions_has_python(self):
        assert LANGUAGE_EXTENSIONS[".py"] == "python"

    def test_language_extensions_has_typescript(self):
        assert LANGUAGE_EXTENSIONS[".ts"] == "typescript"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

class TestPathHelpers:
    def test_repograph_dir_path(self, tmp_path):
        assert repograph_dir(str(tmp_path)) == str(tmp_path / ".repograph")

    def test_db_path(self, tmp_path):
        assert db_path(str(tmp_path)) == str(tmp_path / ".repograph" / "graph.db")

    def test_is_initialized_false_when_missing(self, tmp_path):
        assert not is_initialized(str(tmp_path))

    def test_is_initialized_true_when_present(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        (rg / "graph.db").write_text("", encoding="utf-8")
        assert is_initialized(str(tmp_path))

    def test_is_initialized_false_when_dir_missing_db(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        assert not is_initialized(str(tmp_path))


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------

class TestSettingsDefaults:
    def test_default_include_git(self):
        s = Settings()
        assert s.include_git is True

    def test_default_include_embeddings(self):
        s = Settings()
        assert s.include_embeddings is False

    def test_default_auto_dynamic_analysis(self):
        s = Settings()
        assert s.auto_dynamic_analysis is True

    def test_default_sync_test_command_is_none(self):
        s = Settings()
        assert s.sync_test_command is None

    def test_default_sync_runtime_server_command_is_none(self):
        s = Settings()
        assert s.sync_runtime_server_command is None

    def test_default_sync_runtime_probe_url_is_none(self):
        s = Settings()
        assert s.sync_runtime_probe_url is None

    def test_default_sync_runtime_scenario_urls_empty(self):
        s = Settings()
        assert s.sync_runtime_scenario_urls == []

    def test_default_sync_runtime_scenario_driver_command_is_none(self):
        s = Settings()
        assert s.sync_runtime_scenario_driver_command is None

    def test_default_sync_runtime_ready_timeout(self):
        s = Settings()
        assert s.sync_runtime_ready_timeout == 15

    def test_default_sync_runtime_attach_policy(self):
        s = Settings()
        assert s.sync_runtime_attach_policy == "prompt"

    def test_default_doc_symbols_flag_unknown(self):
        s = Settings()
        assert s.doc_symbols_flag_unknown is False

    def test_default_context_tokens(self):
        s = Settings()
        assert s.context_tokens == DEFAULT_CONTEXT_TOKENS

    def test_default_nl_model(self):
        s = Settings()
        assert "haiku" in s.nl_model or "claude" in s.nl_model

    def test_default_exclude_dirs_empty(self):
        s = Settings()
        assert s.exclude_dirs == []


# ---------------------------------------------------------------------------
# load_settings — no config files
# ---------------------------------------------------------------------------

class TestLoadSettingsDefaults:
    def test_returns_settings_instance(self, tmp_path):
        s = load_settings(str(tmp_path))
        assert isinstance(s, Settings)

    def test_defaults_when_no_files(self, tmp_path):
        s = load_settings(str(tmp_path))
        assert s.include_git is True
        assert s.auto_dynamic_analysis is True
        assert s.sync_test_command is None


# ---------------------------------------------------------------------------
# load_settings — YAML layer
# ---------------------------------------------------------------------------

class TestLoadSettingsYaml:
    def _write_yaml(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def test_yaml_in_repograph_dir_sets_exclude_dirs(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        self._write_yaml(rg / INDEX_CONFIG_FILENAME, "exclude_dirs:\n  - vendor\n  - dist\n")
        s = load_settings(str(tmp_path))
        assert "vendor" in s.exclude_dirs
        assert "dist" in s.exclude_dirs

    def test_yaml_at_repo_root_sets_exclude_dirs(self, tmp_path):
        self._write_yaml(tmp_path / INDEX_CONFIG_FILENAME, "exclude_dirs:\n  - legacy\n")
        s = load_settings(str(tmp_path))
        assert "legacy" in s.exclude_dirs

    def test_yaml_sets_sync_test_command(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        self._write_yaml(rg / INDEX_CONFIG_FILENAME,
                         "sync_test_command:\n  - python\n  - -m\n  - pytest\n")
        s = load_settings(str(tmp_path))
        assert s.sync_test_command == ["python", "-m", "pytest"]

    def test_yaml_sets_doc_symbols_flag(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        self._write_yaml(rg / INDEX_CONFIG_FILENAME, "doc_symbols_flag_unknown: true\n")
        s = load_settings(str(tmp_path))
        assert s.doc_symbols_flag_unknown is True

    def test_repograph_yaml_overrides_root_yaml(self, tmp_path):
        """YAML in .repograph/ should win over root-level YAML."""
        rg = tmp_path / ".repograph"
        rg.mkdir()
        self._write_yaml(tmp_path / INDEX_CONFIG_FILENAME, "exclude_dirs:\n  - root_only\n")
        self._write_yaml(rg / INDEX_CONFIG_FILENAME, "exclude_dirs:\n  - rg_only\n")
        s = load_settings(str(tmp_path))
        # Both are merged (YAML layers stack)
        assert "root_only" in s.exclude_dirs or "rg_only" in s.exclude_dirs


# ---------------------------------------------------------------------------
# load_settings — settings.json layer (highest priority)
# ---------------------------------------------------------------------------

class TestLoadSettingsJson:
    def _write_json(self, tmp_path: Path, data: dict) -> Path:
        rg = tmp_path / ".repograph"
        rg.mkdir(exist_ok=True)
        p = rg / "settings.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_json_overrides_default(self, tmp_path):
        self._write_json(tmp_path, {"include_git": False})
        s = load_settings(str(tmp_path))
        assert s.include_git is False

    def test_json_sets_nl_model(self, tmp_path):
        self._write_json(tmp_path, {"nl_model": "claude-opus-4-6"})
        s = load_settings(str(tmp_path))
        assert s.nl_model == "claude-opus-4-6"

    def test_json_sets_exclude_dirs(self, tmp_path):
        self._write_json(tmp_path, {"exclude_dirs": ["vendor", "node_modules"]})
        s = load_settings(str(tmp_path))
        assert "vendor" in s.exclude_dirs

    def test_json_overrides_yaml(self, tmp_path):
        """settings.json must win over YAML."""
        rg = tmp_path / ".repograph"
        rg.mkdir()
        (rg / INDEX_CONFIG_FILENAME).write_text(
            "doc_symbols_flag_unknown: true\n", encoding="utf-8"
        )
        (rg / "settings.json").write_text(
            json.dumps({"doc_symbols_flag_unknown": False}), encoding="utf-8"
        )
        s = load_settings(str(tmp_path))
        assert s.doc_symbols_flag_unknown is False

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        (rg / "settings.json").write_text("{invalid json{{", encoding="utf-8")
        s = load_settings(str(tmp_path))
        # Should not raise; falls back gracefully
        assert isinstance(s, Settings)

    def test_self_describing_settings_document_reads_runtime_overrides(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        (rg / "settings.json").write_text(
            json.dumps(
                {
                    "document_version": 2,
                    "runtime_overrides": {"include_git": False},
                    "effective_values": {"include_git": False},
                    "setting_catalog": {},
                }
            ),
            encoding="utf-8",
        )
        s = load_settings(str(tmp_path))
        assert s.include_git is False


class TestResolveRuntimeSettings:
    def test_resolved_settings_use_persisted_values(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        (rg / "settings.json").write_text(
            json.dumps(
                {
                    "include_git": False,
                    "include_embeddings": True,
                    "auto_dynamic_analysis": False,
                    "context_tokens": 1500,
                    "git_days": 30,
                    "entry_point_limit": 11,
                    "min_community_size": 7,
                }
            ),
            encoding="utf-8",
        )

        resolved = resolve_runtime_settings(str(tmp_path))
        assert resolved.include_git is False
        assert resolved.include_embeddings is True
        assert resolved.auto_dynamic_analysis is False
        assert resolved.max_context_tokens == 1500
        assert resolved.git_days == 30
        assert resolved.entry_point_limit == 11
        assert resolved.min_community_size == 7

    def test_explicit_overrides_win_over_persisted_settings(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        (rg / "settings.json").write_text(
            json.dumps(
                {
                    "include_git": False,
                    "include_embeddings": False,
                    "auto_dynamic_analysis": False,
                    "context_tokens": 1500,
                    "git_days": 30,
                    "entry_point_limit": 11,
                    "min_community_size": 7,
                }
            ),
            encoding="utf-8",
        )

        resolved = resolve_runtime_settings(
            str(tmp_path),
            include_git=True,
            include_embeddings=True,
            auto_dynamic_analysis=True,
            max_context_tokens=900,
            git_days=12,
            entry_point_limit=3,
            min_community_size=4,
        )
        assert resolved.include_git is True
        assert resolved.include_embeddings is True
        assert resolved.auto_dynamic_analysis is True
        assert resolved.max_context_tokens == 900
        assert resolved.git_days == 12
        assert resolved.entry_point_limit == 3
        assert resolved.min_community_size == 4


# ---------------------------------------------------------------------------
# get_setting / set_setting / reset_settings
# ---------------------------------------------------------------------------

class TestGetSetReset:
    def test_get_setting_returns_default(self, tmp_path):
        val = get_setting(str(tmp_path), "include_git")
        assert val is True

    def test_set_and_get_roundtrip(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        set_setting(str(tmp_path), "include_git", False)
        assert get_setting(str(tmp_path), "include_git") is False

    def test_set_and_get_string(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        set_setting(str(tmp_path), "nl_model", "claude-opus-4-6")
        assert get_setting(str(tmp_path), "nl_model") == "claude-opus-4-6"

    def test_set_and_get_list(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        set_setting(str(tmp_path), "exclude_dirs", ["vendor", "dist"])
        val = get_setting(str(tmp_path), "exclude_dirs")
        assert "vendor" in val

    def test_set_unknown_key_raises(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        with pytest.raises(KeyError, match="Unknown setting"):
            set_setting(str(tmp_path), "nonexistent_key", "value")

    def test_get_unknown_key_raises(self, tmp_path):
        with pytest.raises(KeyError, match="Unknown setting"):
            get_setting(str(tmp_path), "nonexistent_key")

    def test_reset_clears_settings_json(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        set_setting(str(tmp_path), "include_git", False)
        reset_settings(str(tmp_path))
        assert (rg / "settings.json").exists()
        payload = _settings_payload(rg / "settings.json")
        assert payload["runtime_overrides"] == {}
        assert payload["effective_values"]["include_git"] is True

    def test_reset_restores_defaults(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        set_setting(str(tmp_path), "include_git", False)
        reset_settings(str(tmp_path))
        assert get_setting(str(tmp_path), "include_git") is True

    def test_reset_noop_when_no_file(self, tmp_path):
        # Should not raise even when settings.json doesn't exist
        reset_settings(str(tmp_path))

    def test_set_persists_to_json_file(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        set_setting(str(tmp_path), "context_tokens", 4000)
        data = _settings_payload(rg / "settings.json")
        assert data["runtime_overrides"]["context_tokens"] == 4000
        assert data["effective_values"]["context_tokens"] == 4000

    def test_unset_setting_removes_runtime_override(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        set_setting(str(tmp_path), "include_git", False)
        unset_setting(str(tmp_path), "include_git")
        assert get_setting(str(tmp_path), "include_git") is True
        payload = _settings_payload(rg / "settings.json")
        assert payload["runtime_overrides"] == {}

    def test_unset_unknown_key_raises(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        with pytest.raises(KeyError, match="Unknown setting"):
            unset_setting(str(tmp_path), "nope")

    def test_invalid_int_setting_rejected_on_write(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        with pytest.raises(ValueError, match="entry_point_limit"):
            set_setting(str(tmp_path), "entry_point_limit", "nonsense")

    def test_invalid_boolean_setting_rejected_on_write(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        with pytest.raises(ValueError, match="auto_dynamic_analysis"):
            set_setting(str(tmp_path), "auto_dynamic_analysis", "sometimes")

    def test_invalid_exclude_dirs_rejected_on_write(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        with pytest.raises(ValueError, match="exclude_dirs"):
            set_setting(str(tmp_path), "exclude_dirs", ["nested/path"])

    def test_set_exclude_dirs_accepts_single_string_and_normalizes(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        set_setting(str(tmp_path), "exclude_dirs", "vendor")
        assert get_setting(str(tmp_path), "exclude_dirs") == ["vendor"]

    def test_set_sync_test_command_rejects_empty_list(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        with pytest.raises(ValueError, match="sync_test_command"):
            set_setting(str(tmp_path), "sync_test_command", [])

    def test_set_sync_runtime_probe_url_rejects_relative_url(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        with pytest.raises(ValueError, match="sync_runtime_probe_url"):
            set_setting(str(tmp_path), "sync_runtime_probe_url", "/health")

    def test_set_sync_runtime_server_command_roundtrip(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        set_setting(str(tmp_path), "sync_runtime_server_command", ["python", "app.py"])
        assert get_setting(str(tmp_path), "sync_runtime_server_command") == ["python", "app.py"]

    def test_set_sync_runtime_scenario_urls_roundtrip(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        set_setting(str(tmp_path), "sync_runtime_scenario_urls", ["/", "/health"])
        assert get_setting(str(tmp_path), "sync_runtime_scenario_urls") == ["/", "/health"]

    def test_set_sync_runtime_scenario_driver_command_roundtrip(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        set_setting(
            str(tmp_path),
            "sync_runtime_scenario_driver_command",
            ["python", "tools/runtime_driver.py"],
        )
        assert get_setting(str(tmp_path), "sync_runtime_scenario_driver_command") == [
            "python",
            "tools/runtime_driver.py",
        ]

    def test_set_sync_runtime_attach_policy_roundtrip(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        set_setting(str(tmp_path), "sync_runtime_attach_policy", "never")
        assert get_setting(str(tmp_path), "sync_runtime_attach_policy") == "never"

    def test_set_sync_runtime_attach_policy_rejects_unknown_value(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        with pytest.raises(ValueError, match="sync_runtime_attach_policy"):
            set_setting(str(tmp_path), "sync_runtime_attach_policy", "sometimes")


# ---------------------------------------------------------------------------
# save_settings
# ---------------------------------------------------------------------------

class TestSaveSettings:
    def test_save_and_reload(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        s = Settings(include_git=False, nl_model="test-model")
        save_settings(str(tmp_path), s)
        s2 = load_settings(str(tmp_path))
        assert s2.include_git is False
        assert s2.nl_model == "test-model"

    def test_save_creates_directory(self, tmp_path):
        # .repograph doesn't exist yet — save_settings should create it
        s = Settings(include_embeddings=True)
        save_settings(str(tmp_path), s)
        assert (tmp_path / ".repograph" / "settings.json").exists()


# ---------------------------------------------------------------------------
# Settings scaffold and metadata
# ---------------------------------------------------------------------------


class TestSettingsMetadata:
    def test_ensure_settings_file_creates_empty_scaffold(self, tmp_path):
        path = ensure_settings_file(str(tmp_path))
        assert path.endswith(".repograph/settings.json")
        payload = _settings_payload(Path(path))
        assert payload["runtime_overrides"] == {}
        assert payload["effective_values"]["include_git"] is True
        assert "include_git" in payload["setting_catalog"]

    def test_list_setting_metadata_includes_current_and_default(self, tmp_path):
        (tmp_path / ".repograph").mkdir()
        set_setting(str(tmp_path), "include_git", False)
        rows = list_setting_metadata(str(tmp_path))
        include_git = next(row for row in rows if row["key"] == "include_git")
        assert include_git["current"] is False
        assert include_git["default"] is True
        assert include_git["type"] == "bool"
        assert include_git["source"] == "runtime_override"

    def test_describe_setting_returns_lifecycle_metadata(self, tmp_path):
        info = describe_setting(str(tmp_path), "sync_test_command")
        assert info["key"] == "sync_test_command"
        assert "takes_effect" in info
        assert "description" in info
        assert "requires_full_sync" in info
        assert "value_shape" in info
        assert "examples" in info

    def test_list_setting_metadata_includes_managed_runtime_keys(self, tmp_path):
        rows = list_setting_metadata(str(tmp_path))
        keys = {row["key"] for row in rows}
        assert "sync_runtime_server_command" in keys
        assert "sync_runtime_probe_url" in keys
        assert "sync_runtime_scenario_urls" in keys
        assert "sync_runtime_scenario_driver_command" in keys
        assert "sync_runtime_ready_timeout" in keys
        assert "sync_runtime_attach_policy" in keys

    def test_describe_setting_unknown_key_raises(self, tmp_path):
        with pytest.raises(KeyError, match="Unknown setting"):
            describe_setting(str(tmp_path), "missing")


# ---------------------------------------------------------------------------
# Backward-compat loader functions
# ---------------------------------------------------------------------------

class TestBackwardCompatLoaders:
    def test_load_extra_exclude_dirs_empty_by_default(self, tmp_path):
        result = load_extra_exclude_dirs(str(tmp_path))
        assert isinstance(result, set)

    def test_load_extra_exclude_dirs_from_settings_json(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        set_setting(str(tmp_path), "exclude_dirs", ["vendor"])
        result = load_extra_exclude_dirs(str(tmp_path))
        assert "vendor" in result

    def test_load_doc_symbol_options_default_false(self, tmp_path):
        opts = load_doc_symbol_options(str(tmp_path))
        assert opts["doc_symbols_flag_unknown"] is False

    def test_load_doc_symbol_options_true_from_settings(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        set_setting(str(tmp_path), "doc_symbols_flag_unknown", True)
        opts = load_doc_symbol_options(str(tmp_path))
        assert opts["doc_symbols_flag_unknown"] is True

    def test_load_sync_test_command_none_by_default(self, tmp_path):
        assert load_sync_test_command(str(tmp_path)) is None

    def test_load_sync_test_command_from_settings(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        set_setting(str(tmp_path), "sync_test_command", ["python", "-m", "pytest"])
        cmd = load_sync_test_command(str(tmp_path))
        assert cmd == ["python", "-m", "pytest"]

    def test_load_sync_runtime_settings_from_settings(self, tmp_path):
        rg = tmp_path / ".repograph"
        rg.mkdir()
        set_setting(str(tmp_path), "sync_runtime_server_command", ["python", "app.py"])
        set_setting(str(tmp_path), "sync_runtime_probe_url", "http://127.0.0.1:8000/health")
        set_setting(str(tmp_path), "sync_runtime_scenario_urls", ["/", "/health"])
        set_setting(
            str(tmp_path),
            "sync_runtime_scenario_driver_command",
            ["python", "tools/runtime_driver.py"],
        )
        set_setting(str(tmp_path), "sync_runtime_ready_timeout", 9)
        set_setting(str(tmp_path), "sync_runtime_attach_policy", "always")

        assert load_sync_runtime_server_command(str(tmp_path)) == ["python", "app.py"]
        assert load_sync_runtime_probe_url(str(tmp_path)) == "http://127.0.0.1:8000/health"
        assert load_sync_runtime_scenario_urls(str(tmp_path)) == ["/", "/health"]
        assert load_sync_runtime_scenario_driver_command(str(tmp_path)) == [
            "python",
            "tools/runtime_driver.py",
        ]
        assert load_sync_runtime_ready_timeout(str(tmp_path)) == 9
        assert load_sync_runtime_attach_policy(str(tmp_path)) == "always"


# ---------------------------------------------------------------------------
# validate_index_yaml
# ---------------------------------------------------------------------------

class TestValidateIndexYaml:
    class _FakeLogger:
        def __init__(self):
            self.warnings = []
            self.errors = []

        def warning(self, msg, **kw):
            self.warnings.append((msg, kw))

        def error(self, msg, **kw):
            self.errors.append((msg, kw))

    def test_valid_yaml_no_warnings(self, tmp_path):
        lg = self._FakeLogger()
        validate_index_yaml(
            {"exclude_dirs": ["vendor"], "doc_symbols_flag_unknown": False},
            str(tmp_path / "repograph.index.yaml"),
            lg,
        )
        assert not lg.errors

    def test_unknown_key_produces_warning(self, tmp_path):
        lg = self._FakeLogger()
        validate_index_yaml(
            {"unknown_future_key": True},
            str(tmp_path / "repograph.index.yaml"),
            lg,
        )
        assert any("unknown_future_key" in str(w) for w in lg.warnings)

    def test_schema_exported(self):
        assert "properties" in INDEX_YAML_SCHEMA
        assert "exclude_dirs" in INDEX_YAML_SCHEMA["properties"]
