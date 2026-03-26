"""Tests for logging.Handler.emit dead-code exemption."""
from __future__ import annotations

from unittest.mock import MagicMock

from repograph.plugins.static_analyzers.dead_code.plugin import is_logging_handler_emit_method


def test_emit_on_logging_handler_is_recognized() -> None:
    fn = {
        "name": "emit",
        "qualified_name": "MyH.emit",
        "file_path": "pkg/h.py",
    }
    store = MagicMock()
    store.get_all_classes.return_value = [
        {
            "file_path": "pkg/h.py",
            "qualified_name": "MyH",
            "name": "MyH",
            "base_names": ["logging.Handler"],
        },
    ]
    assert is_logging_handler_emit_method(fn, store) is True


def test_emit_on_unrelated_class_not_recognized() -> None:
    fn = {
        "name": "emit",
        "qualified_name": "X.emit",
        "file_path": "pkg/x.py",
    }
    store = MagicMock()
    store.get_all_classes.return_value = [
        {
            "file_path": "pkg/x.py",
            "qualified_name": "X",
            "name": "X",
            "base_names": ["object"],
        },
    ]
    assert is_logging_handler_emit_method(fn, store) is False
