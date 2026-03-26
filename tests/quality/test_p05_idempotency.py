"""Q7: Re-running Phase 5 on the same parse snapshot does not change CALLS edges."""
from __future__ import annotations

import pytest

from repograph.pipeline.phases import p01_walk, p03_parse, p04_imports, p05_calls
from repograph.parsing.symbol_table import SymbolTable

pytestmark = [pytest.mark.quality, pytest.mark.integration]


def _normalize_call_edges(store) -> list[tuple]:
    """Stable comparison key for CALLS rows (matches merge semantics under test)."""
    rows = []
    for e in store.get_all_call_edges():
        lines = e.get("lines") or [e.get("line")]
        try:
            line_tuple = tuple(sorted(int(x) for x in lines if x is not None))
        except (TypeError, ValueError):
            line_tuple = (e.get("line"),)
        rows.append(
            (
                e["from"],
                e["to"],
                round(float(e.get("confidence") or 0.0), 6),
                line_tuple,
                (e.get("reason") or ""),
            )
        )
    return sorted(rows)


def test_p05_calls_twice_is_idempotent(simple_store, python_simple_fixture_dir) -> None:
    """Second p05_calls.run leaves CALLS identical to after first (on same parsed+table)."""
    repo_root = python_simple_fixture_dir
    files = p01_walk.run(repo_root)
    symbol_table = SymbolTable()
    for fn_dict in simple_store.get_all_functions_for_symbol_table():
        symbol_table.add_function_from_dict(fn_dict)
    for cls_dict in simple_store.get_all_classes_for_symbol_table():
        symbol_table.add_class_from_dict(cls_dict)

    parsed = p03_parse.run(files, simple_store, symbol_table)
    p04_imports.run(parsed, simple_store, symbol_table, repo_root)

    before = _normalize_call_edges(simple_store)
    p05_calls.run(parsed, simple_store, symbol_table)
    after_first = _normalize_call_edges(simple_store)
    p05_calls.run(parsed, simple_store, symbol_table)
    after_second = _normalize_call_edges(simple_store)

    assert before == after_first == after_second
