"""Phase 15 — optional unknown qualified symbol warnings (C.1)."""
from __future__ import annotations

from repograph.plugins.exporters.doc_warnings.plugin import _check_token


def test_unknown_reference_emitted_when_flag_and_qualified() -> None:
    w = _check_token(
        "foo.bar.Nonexistent",
        1,
        "See `foo.bar.Nonexistent` in the guide.",
        "docs/guide.md",
        {},
        flag_unknown=True,
    )
    assert w is not None
    assert w.warning_type == "unknown_reference"
    assert w.severity == "medium"
    assert w.symbol_text == "foo.bar.Nonexistent"


def test_unknown_not_emitted_without_flag() -> None:
    assert _check_token(
        "foo.bar.X",
        1,
        "x",
        "d.md",
        {},
        flag_unknown=False,
    ) is None


def test_unknown_not_emitted_for_unqualified_token() -> None:
    assert _check_token(
        "MissingName",
        1,
        "x",
        "d.md",
        {},
        flag_unknown=True,
    ) is None
