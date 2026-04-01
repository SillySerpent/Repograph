"""Unit tests for Phase 17 config registry key filtering."""
from __future__ import annotations

from repograph.plugins.exporters.config_registry.plugin import (
    _key_excluded,
    build_registry_with_diagnostics,
)


def test_excludes_trivial_single_letter_keys() -> None:
    assert _key_excluded("a")
    assert _key_excluded("x")
    assert _key_excluded("Z")


def test_excludes_single_digit_keys() -> None:
    assert _key_excluded("0")
    assert _key_excluded("9")


def test_allows_meaningful_keys() -> None:
    assert not _key_excluded("api")
    assert not _key_excluded("trading")
    assert not _key_excluded("market.symbol")


class _EmptyStore:
    def query(self, _cypher):
        return []

    def get_pathway_steps(self, _pathway_id):
        return []

    def get_all_files(self):
        return []


def test_build_registry_with_diagnostics_empty_valid() -> None:
    reg, diag = build_registry_with_diagnostics(_EmptyStore())  # type: ignore[arg-type]
    assert reg == {}
    assert diag.get("status") == "empty_valid"
    assert diag.get("registry_keys") == 0


class _FailingStore:
    def query(self, _cypher):
        raise RuntimeError("boom")

    def get_pathway_steps(self, _pathway_id):
        raise RuntimeError("boom")

    def get_all_files(self):
        raise RuntimeError("boom")


def test_build_registry_with_diagnostics_empty_error() -> None:
    reg, diag = build_registry_with_diagnostics(_FailingStore())  # type: ignore[arg-type]
    assert reg == {}
    assert diag.get("status") == "empty_error"
    assert diag.get("errors")


def test_build_registry_uses_pathway_contexts_and_abs_paths(tmp_path) -> None:
    source = tmp_path / "app.py"
    source.write_text('import os\nAPI_KEY = os.getenv("API_KEY")\n', encoding="utf-8")

    class _Store:
        def query(self, _cypher):
            return [("pw-1", "startup_flow", "CONFIG DEPENDENCIES\n• API_KEY\n")]

        def get_pathway_steps(self, _pathway_id):
            return [{"file_path": "app.py"}]

        def get_all_files(self):
            return [{"path": "app.py", "abs_path": str(source), "language": "python"}]

    reg, diag = build_registry_with_diagnostics(_Store())  # type: ignore[arg-type]
    assert diag["pathways_with_context"] == 1
    assert reg["API_KEY"]["pathways"] == ["startup_flow"]
    assert reg["API_KEY"]["files"] == ["app.py"]
    assert reg["API_KEY"]["usage_count"] == 2
