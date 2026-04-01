"""repograph.index.yaml — doc_symbols_flag_unknown."""
from __future__ import annotations

from repograph.settings import load_doc_symbol_options


def test_doc_symbols_flag_unknown_false_by_default(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".repograph").mkdir()
    assert load_doc_symbol_options(str(root))["doc_symbols_flag_unknown"] is False


def test_doc_symbols_flag_unknown_from_dot_repograph_yaml(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    rg = root / ".repograph"
    rg.mkdir()
    (rg / "repograph.index.yaml").write_text("doc_symbols_flag_unknown: true\n", encoding="utf-8")
    assert load_doc_symbol_options(str(root))["doc_symbols_flag_unknown"] is True
