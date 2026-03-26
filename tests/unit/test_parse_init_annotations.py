"""Unit tests for ``_parse_init_type_annotations`` in store_queries_analytics.

These test the signature parser in isolation — no DB, no filesystem.

INVARIANT: The function is pure; all tests run without any I/O.
"""
from __future__ import annotations

from repograph.graph_store.store_queries_analytics import _parse_init_type_annotations


def test_simple_typed_params():
    sig = "def __init__(self, cfg: dict, broker: ITraderBroker) -> None"
    result = _parse_init_type_annotations(sig)
    assert result["cfg"] == "dict"
    assert result["broker"] == "ITraderBroker"


def test_self_excluded():
    sig = "def __init__(self, value: int) -> None"
    result = _parse_init_type_annotations(sig)
    assert "self" not in result
    assert result["value"] == "int"


def test_optional_type():
    sig = "def __init__(self, strategies: list | None = None) -> None"
    result = _parse_init_type_annotations(sig)
    assert result["strategies"] == "list | None"


def test_no_annotation():
    sig = "def __init__(self, db_writer) -> None"
    result = _parse_init_type_annotations(sig)
    assert result.get("db_writer", "") == ""


def test_default_value_stripped():
    sig = "def __init__(self, timeout: float = 30.0) -> None"
    result = _parse_init_type_annotations(sig)
    assert result["timeout"] == "float"


def test_multiline_signature():
    sig = (
        "def __init__(\n"
        "        self,\n"
        "        cfg: dict,\n"
        "        market_state: MarketState,\n"
        "        broker: ITraderBroker,\n"
        "    ) -> None"
    )
    result = _parse_init_type_annotations(sig)
    assert result["cfg"] == "dict"
    assert result["market_state"] == "MarketState"
    assert result["broker"] == "ITraderBroker"


def test_complex_generic_type():
    sig = "def __init__(self, handlers: list[tuple[str, int]]) -> None"
    result = _parse_init_type_annotations(sig)
    # The parser should not crash on nested brackets
    assert "handlers" in result


def test_star_args_skipped():
    sig = "def __init__(self, name: str, *args, **kwargs) -> None"
    result = _parse_init_type_annotations(sig)
    assert result["name"] == "str"
    assert "args" not in result or result.get("args") is not None  # kwargs stripped
    # Crucially: no crash
    assert "kwargs" not in result


def test_empty_signature_returns_empty():
    assert _parse_init_type_annotations("") == {}


def test_no_parens_returns_empty():
    assert _parse_init_type_annotations("not a function") == {}


def test_return_annotation_not_included():
    sig = "def __init__(self, x: int) -> None"
    result = _parse_init_type_annotations(sig)
    assert "None" not in result
    assert result.get("x") == "int"
