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
    def get_all_pathways(self):
        return []

    def get_all_files(self):
        return []


def test_build_registry_with_diagnostics_empty_valid() -> None:
    reg, diag = build_registry_with_diagnostics(_EmptyStore())
    assert reg == {}
    assert diag.get("status") == "empty_valid"
    assert diag.get("registry_keys") == 0
