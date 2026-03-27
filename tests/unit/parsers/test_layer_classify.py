"""Tests for Block G1 — architecture layer classification (p06b_layer_classify)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file_record(path: str, language: str = "python", is_test: bool = False):
    from repograph.core.models import FileRecord
    return FileRecord(
        path=path, abs_path=path, name=Path(path).name,
        extension=Path(path).suffix, language=language,
        size_bytes=0, line_count=5, source_hash="x",
        is_test=is_test, is_config=False, mtime=0.0,
    )


def _make_fn(fn_id: str, name: str, file_path: str):
    from repograph.core.models import FunctionNode
    return FunctionNode(
        id=fn_id, name=name, qualified_name=name,
        file_path=file_path, line_start=1, line_end=5,
        signature=f"def {name}()", docstring=None,
        is_method=False, is_async=False, is_exported=True,
        decorators=[], param_names=[], return_type=None, source_hash="x",
    )


def _make_import_node(file_path: str, module_path: str):
    from repograph.core.models import ImportNode
    return ImportNode(
        id=f"imp_{module_path}",
        file_path=file_path,
        raw_statement=f"import {module_path}",
        module_path=module_path,
        resolved_path=None,
        imported_names=[],
        is_wildcard=False,
        line_number=1,
    )


def _make_parsed_file(path: str, language: str = "python", imports=None,
                      functions=None, is_test: bool = False):
    from repograph.core.models import ParsedFile
    fr = _make_file_record(path, language, is_test)
    pf = ParsedFile(file_record=fr)
    pf.imports = list(imports or [])
    pf.functions = list(functions or [])
    return pf


def _mock_store() -> MagicMock:
    store = MagicMock()
    store.update_function_layer_role.return_value = None
    store.update_file_layer.return_value = None
    return store


# ---------------------------------------------------------------------------
# Import-based layer detection
# ---------------------------------------------------------------------------


def test_sqlalchemy_import_assigns_persistence_layer():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn = _make_fn("fn::model_fn", "save", "app/models/user.py")
    imp = _make_import_node("app/models/user.py", "sqlalchemy")
    pf = _make_parsed_file("app/models/user.py", imports=[imp], functions=[fn])

    store = _mock_store()
    run([pf], store)

    store.update_function_layer_role.assert_called_once_with("fn::model_fn", "persistence", "model")


def test_flask_import_assigns_api_layer():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn = _make_fn("fn::view", "index", "app/routes/main.py")
    imp = _make_import_node("app/routes/main.py", "flask")
    pf = _make_parsed_file("app/routes/main.py", imports=[imp], functions=[fn])

    store = _mock_store()
    run([pf], store)

    store.update_function_layer_role.assert_called_once_with("fn::view", "api", "handler")


def test_react_import_assigns_ui_layer():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn = _make_fn("fn::comp", "UserCard", "src/components/UserCard.tsx")
    imp = _make_import_node("src/components/UserCard.tsx", "react")
    pf = _make_parsed_file("src/components/UserCard.tsx", language="typescript",
                           imports=[imp], functions=[fn])

    store = _mock_store()
    run([pf], store)

    store.update_function_layer_role.assert_called_once_with("fn::comp", "ui", "component")


# ---------------------------------------------------------------------------
# File-path heuristics
# ---------------------------------------------------------------------------


def test_path_heuristic_persistence_entities():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn = _make_fn("fn::entity", "get_all", "app/entities/order.py")
    pf = _make_parsed_file("app/entities/order.py", functions=[fn])

    store = _mock_store()
    run([pf], store)

    store.update_function_layer_role.assert_called_once_with("fn::entity", "persistence", "model")


def test_path_heuristic_api_controllers():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn = _make_fn("fn::ctrl", "create_user", "app/controllers/user.py")
    pf = _make_parsed_file("app/controllers/user.py", functions=[fn])

    store = _mock_store()
    run([pf], store)

    store.update_function_layer_role.assert_called_once_with("fn::ctrl", "api", "controller")


def test_path_heuristic_business_logic_services():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn = _make_fn("fn::svc", "process_payment", "app/services/payment.py")
    pf = _make_parsed_file("app/services/payment.py", functions=[fn])

    store = _mock_store()
    run([pf], store)

    store.update_function_layer_role.assert_called_once_with("fn::svc", "business_logic", "service")


def test_path_heuristic_util():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn = _make_fn("fn::util", "format_date", "app/utils/formatting.py")
    pf = _make_parsed_file("app/utils/formatting.py", functions=[fn])

    store = _mock_store()
    run([pf], store)

    store.update_function_layer_role.assert_called_once_with("fn::util", "util", "util")


# ---------------------------------------------------------------------------
# Unknown / default
# ---------------------------------------------------------------------------


def test_unknown_functions_get_unknown_layer():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn = _make_fn("fn::misc", "do_something", "app/misc.py")
    pf = _make_parsed_file("app/misc.py", functions=[fn])

    store = _mock_store()
    run([pf], store)

    # layer and role should be "unknown" — not empty string
    args = store.update_function_layer_role.call_args
    assert args is not None
    layer = args[0][1]
    role = args[0][2]
    assert layer == "unknown"
    assert role == "unknown"


# ---------------------------------------------------------------------------
# Test helper override
# ---------------------------------------------------------------------------


def test_test_file_functions_get_test_helper_role():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn = _make_fn("fn::helper", "assert_valid", "tests/conftest.py")
    pf = _make_parsed_file("tests/conftest.py", functions=[fn], is_test=True)

    store = _mock_store()
    run([pf], store)

    args = store.update_function_layer_role.call_args
    assert args is not None
    role = args[0][2]
    assert role == "test_helper"


# ---------------------------------------------------------------------------
# Import priority over path
# ---------------------------------------------------------------------------


def test_import_layer_beats_path_layer():
    """Import-based detection wins when both import and path signals are present."""
    from repograph.pipeline.phases.p06b_layer_classify import run

    # File is in /services/ (→ business_logic) but imports sqlalchemy (→ persistence)
    fn = _make_fn("fn::repo", "find_by_id", "app/services/user_repo.py")
    imp = _make_import_node("app/services/user_repo.py", "sqlalchemy")
    pf = _make_parsed_file("app/services/user_repo.py", imports=[imp], functions=[fn])

    store = _mock_store()
    run([pf], store)

    args = store.update_function_layer_role.call_args
    layer = args[0][1]
    # sqlalchemy import → persistence wins over /services/ path → business_logic
    assert layer == "persistence"


# ---------------------------------------------------------------------------
# File node update
# ---------------------------------------------------------------------------


def test_file_node_layer_updated():
    from repograph.pipeline.phases.p06b_layer_classify import run

    pf = _make_parsed_file("app/models/product.py")
    store = _mock_store()
    run([pf], store)

    store.update_file_layer.assert_called_once_with("file::app/models/product.py", "persistence")


# ---------------------------------------------------------------------------
# Return value
# ---------------------------------------------------------------------------


def test_run_returns_update_count():
    from repograph.pipeline.phases.p06b_layer_classify import run

    fn1 = _make_fn("fn::a", "func_a", "app/services/a.py")
    fn2 = _make_fn("fn::b", "func_b", "app/services/b.py")
    pf1 = _make_parsed_file("app/services/a.py", functions=[fn1])
    pf2 = _make_parsed_file("app/services/b.py", functions=[fn2])

    store = _mock_store()
    count = run([pf1, pf2], store)

    assert count == 2


# ---------------------------------------------------------------------------
# Module-level rule tests
# ---------------------------------------------------------------------------


def test_layer_rules_constants_are_non_empty():
    from repograph.plugins.layer_rules import (
        IMPORT_LAYER_RULES, PATH_LAYER_RULES, PATH_ROLE_RULES,
        VALID_LAYERS, VALID_ROLES,
    )
    assert len(IMPORT_LAYER_RULES) >= 3
    assert len(PATH_LAYER_RULES) >= 5
    assert len(PATH_ROLE_RULES) >= 3
    assert "persistence" in VALID_LAYERS
    assert "api" in VALID_LAYERS
    assert "unknown" in VALID_LAYERS
    assert "repository" in VALID_ROLES
    assert "unknown" in VALID_ROLES


def test_classify_layer_from_imports_submodule():
    """Dotted submodules like django.db.models should match the django.db rule."""
    from repograph.pipeline.phases.p06b_layer_classify import _classify_layer_from_imports
    from repograph.core.models import ParsedFile

    imp = _make_import_node("foo.py", "django.db.models")
    fr = _make_file_record("foo.py")
    pf = ParsedFile(file_record=fr)
    pf.imports = [imp]

    result = _classify_layer_from_imports(pf)
    assert result == "persistence"
