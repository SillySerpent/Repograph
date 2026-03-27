"""Tests for F5 — cross-language import resolution (Block F5)."""
from __future__ import annotations

from pathlib import Path


def _make_file_record(path: str, language: str):
    from repograph.core.models import FileRecord
    return FileRecord(
        path=path, abs_path=path, name=Path(path).name,
        extension=Path(path).suffix, language=language,
        size_bytes=0, line_count=5, source_hash="x",
        is_test=False, is_config=False, mtime=0.0,
    )


def _make_file_node(path: str, language: str):
    from repograph.core.models import FileNode, NodeID
    return FileNode(
        id=NodeID.make_file_id(path),
        path=path, abs_path=path, name=Path(path).name,
        extension=Path(path).suffix, language=language,
        size_bytes=0, line_count=5, source_hash="x",
        is_test=False, is_config=False,
    )


def _make_fn(fn_id: str, name: str, file_path: str):
    from repograph.core.models import FunctionNode
    return FunctionNode(
        id=fn_id, name=name, qualified_name=name,
        file_path=file_path, line_start=1, line_end=3,
        signature=f"def {name}()", docstring=None,
        is_method=False, is_async=False, is_exported=True,
        decorators=[], param_names=[], return_type=None,
        source_hash="h",
    )


def _make_import_node(file_path: str, module_path: str, imported_names: list[str]):
    from repograph.core.models import ImportNode
    return ImportNode(
        id=f"imp_{module_path}",
        file_path=file_path,
        raw_statement=f"from {module_path} import {', '.join(imported_names)}",
        module_path=module_path,
        resolved_path=None,
        imported_names=imported_names,
        is_wildcard=False,
        line_number=1,
    )


# ---------------------------------------------------------------------------
# _try_cross_language_resolve
# ---------------------------------------------------------------------------


def test_python_can_resolve_js_file():
    """_try_cross_language_resolve must find a JS file when called from Python context."""
    from repograph.pipeline.phases.p04_imports import _try_cross_language_resolve

    js_index = {"src/utils/helpers": "src/utils/helpers.ts"}
    result = _try_cross_language_resolve(
        module_path="src/utils/helpers",
        importing_file="app/main.py",
        lang="python",
        python_module_index={},
        js_path_index=js_index,
        repo_root=".",
    )
    assert result == "src/utils/helpers.ts"


def test_js_can_resolve_python_file():
    """_try_cross_language_resolve must find a Python file when called from JS context."""
    from repograph.pipeline.phases.p04_imports import _try_cross_language_resolve

    py_index = {"utils": "utils.py"}
    result = _try_cross_language_resolve(
        module_path="utils",
        importing_file="app/main.ts",
        lang="typescript",
        python_module_index=py_index,
        js_path_index={},
        repo_root=".",
    )
    assert result == "utils.py"


def test_same_language_failure_returns_none():
    """_try_cross_language_resolve returns None when cross-language index has no match."""
    from repograph.pipeline.phases.p04_imports import _try_cross_language_resolve

    result = _try_cross_language_resolve(
        module_path="nonexistent_module",
        importing_file="main.py",
        lang="python",
        python_module_index={},
        js_path_index={},
        repo_root=".",
    )
    assert result is None


# ---------------------------------------------------------------------------
# Integration: cross-language IMPORTS + CALLS edges created in p04
# ---------------------------------------------------------------------------


def test_cross_language_import_creates_imports_edge(tmp_path):
    """p04 must create an IMPORTS edge when a Python file imports from a JS file."""
    from repograph.graph_store.store import GraphStore
    from repograph.core.models import ParsedFile
    from repograph.parsing.symbol_table import SymbolTable
    from repograph.pipeline.phases import p04_imports

    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()

    # JS file with an exported function
    js_fr = _make_file_record("utils/helpers.ts", "typescript")
    js_pf = ParsedFile(file_record=js_fr)
    js_fn = _make_fn("fn::js_helper", "helper", "utils/helpers.ts")
    js_pf.functions = [js_fn]

    # Python file that imports from the JS module
    py_fr = _make_file_record("app/main.py", "python")
    py_pf = ParsedFile(file_record=py_fr)
    py_pf.imports = [_make_import_node("app/main.py", "utils/helpers", ["helper"])]

    symbol_table = SymbolTable()
    symbol_table.add_function(js_fn)

    # Upsert File and Function nodes so store has them
    store.upsert_file(_make_file_node("app/main.py", "python"))
    store.upsert_file(_make_file_node("utils/helpers.ts", "typescript"))
    store.upsert_function(js_fn)

    p04_imports.run([py_pf, js_pf], store, symbol_table, str(tmp_path))

    # The IMPORTS edge should exist
    rows = store.query(
        "MATCH (a:File)-[r:IMPORTS]->(b:File) WHERE b.path = 'utils/helpers.ts' RETURN r.confidence"
    )
    assert rows, "Expected IMPORTS edge from app/main.py to utils/helpers.ts"
    # Cross-language edges get lower confidence (0.7)
    assert rows[0][0] == pytest.approx(0.7, abs=0.01)

    store.close()


def test_cross_language_import_creates_calls_edge(tmp_path):
    """p04 must create a CALLS edge for cross-language symbol imports when call site exists."""
    import pytest
    from repograph.graph_store.store import GraphStore
    from repograph.core.models import ParsedFile, CallSite
    from repograph.parsing.symbol_table import SymbolTable
    from repograph.pipeline.phases import p04_imports

    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()

    # JS file with an exported function
    js_fr = _make_file_record("utils/helpers.ts", "typescript")
    js_pf = ParsedFile(file_record=js_fr)
    js_fn = _make_fn("fn::js_helper", "helper", "utils/helpers.ts")
    js_pf.functions = [js_fn]

    # Python caller function + call site
    py_fn = _make_fn("fn::py_caller", "do_something", "app/main.py")
    py_fr = _make_file_record("app/main.py", "python")
    py_pf = ParsedFile(file_record=py_fr)
    py_pf.functions = [py_fn]
    py_pf.imports = [_make_import_node("app/main.py", "utils/helpers", ["helper"])]
    py_pf.call_sites = [
        CallSite(
            caller_function_id="fn::py_caller",
            callee_text="helper",
            call_site_line=5,
            argument_exprs=[], keyword_args={},
            file_path="app/main.py",
        )
    ]

    symbol_table = SymbolTable()
    symbol_table.add_function(js_fn)

    store.upsert_file(_make_file_node("app/main.py", "python"))
    store.upsert_file(_make_file_node("utils/helpers.ts", "typescript"))
    store.upsert_function(js_fn)
    store.upsert_function(py_fn)

    p04_imports.run([py_pf, js_pf], store, symbol_table, str(tmp_path))

    # CALLS edge from Python fn to JS fn
    rows = store.query(
        "MATCH (a:Function {id: 'fn::py_caller'})-[r:CALLS]->(b:Function {id: 'fn::js_helper'}) "
        "RETURN r.reason, r.confidence"
    )
    assert rows, "Expected cross-language CALLS edge"
    assert rows[0][0] == "cross_lang_import"
    assert rows[0][1] == pytest.approx(0.7, abs=0.01)

    store.close()


# need pytest.approx import
import pytest
