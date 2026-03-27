"""Tests for Block G2 — class role analyzer plugin."""
from __future__ import annotations

from unittest.mock import MagicMock, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_store(
    classes: list[dict],
    method_names_by_class: dict[str, list[str]] | None = None,
) -> MagicMock:
    """Build a minimal GraphStore mock for class role analysis."""
    method_names_by_class = method_names_by_class or {}

    store = MagicMock()
    store.get_all_classes.return_value = classes

    def query_side_effect(cypher: str, params: dict | None = None):
        params = params or {}
        class_id = params.get("id", "")
        if "HAS_METHOD" in cypher and "f.name" in cypher:
            return [[n] for n in method_names_by_class.get(class_id, [])]
        if "HAS_METHOD" in cypher and "f.id" in cypher:
            return [[f"fn::{n}"] for n in method_names_by_class.get(class_id, [])]
        return []

    store.query.side_effect = query_side_effect
    store.update_function_layer_role.return_value = None
    return store


def _cls(class_id: str, name: str, file_path: str, base_names: list[str] | None = None):
    return {
        "id": class_id,
        "name": name,
        "qualified_name": name,
        "file_path": file_path,
        "line_start": 1,
        "line_end": 10,
        "base_names": base_names or [],
    }


# ---------------------------------------------------------------------------
# Inheritance-based role detection
# ---------------------------------------------------------------------------


def test_sqlalchemy_base_assigns_repository_role():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store([_cls("cls::u", "UserModel", "app/models/user.py", ["Base"])])
    findings = run_class_role_analysis(store)

    assert len(findings) == 1
    assert findings[0]["role"] == "repository"


def test_declarativebase_assigns_repository_role():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store([
        _cls("cls::u", "Product", "app/models/product.py", ["DeclarativeBase"])
    ])
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "repository"


def test_pattern_repository_suffix_base():
    """Base name matching '.*repository$' pattern → role=repository."""
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store([
        _cls("cls::u", "UserRepo", "app/data/user_repo.py", ["AbstractRepository"])
    ])
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "repository"


def test_pattern_service_suffix_base():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store([
        _cls("cls::s", "PaymentSvc", "app/core/payment.py", ["BaseService"])
    ])
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "service"


def test_pattern_controller_base():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store([
        _cls("cls::c", "UserController", "app/web/user.py", ["BaseController"])
    ])
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "controller"


# ---------------------------------------------------------------------------
# Method-name heuristics
# ---------------------------------------------------------------------------


def test_get_by_id_method_assigns_repository_role():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store(
        [_cls("cls::u", "UserStore", "app/data/user_store.py")],
        method_names_by_class={"cls::u": ["get_by_id", "save", "delete"]},
    )
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "repository"


def test_process_method_assigns_service_role():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store(
        [_cls("cls::p", "PaymentProcessor", "core/processors/payment.py")],
        method_names_by_class={"cls::p": ["process", "validate"]},
    )
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "service"


# ---------------------------------------------------------------------------
# File-path fallback
# ---------------------------------------------------------------------------


def test_file_path_models_assigns_model_role():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store([_cls("cls::m", "Order", "app/models/order.py")])
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "model"


def test_file_path_components_assigns_component_role():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store([
        _cls("cls::c", "UserCard", "src/components/UserCard.ts")
    ])
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "component"


def test_file_path_util_assigns_util_role():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store([_cls("cls::u", "Formatter", "app/utils/formatter.py")])
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "util"


# ---------------------------------------------------------------------------
# Unknown default
# ---------------------------------------------------------------------------


def test_plain_class_unknown_role():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store([_cls("cls::x", "Config", "app/config.py")])
    findings = run_class_role_analysis(store)
    assert findings[0]["role"] == "unknown"


# ---------------------------------------------------------------------------
# Method updates are triggered
# ---------------------------------------------------------------------------


def test_methods_are_updated_with_role():
    from repograph.plugins.static_analyzers.class_role.plugin import run_class_role_analysis

    store = _mock_store(
        [_cls("cls::u", "UserModel", "app/models/user.py", ["Base"])],
        method_names_by_class={"cls::u": ["save", "delete"]},
    )
    run_class_role_analysis(store)

    # Each method should receive update_function_layer_role call
    calls = store.update_function_layer_role.call_args_list
    fn_ids = [c[0][0] for c in calls]
    assert "fn::save" in fn_ids
    assert "fn::delete" in fn_ids
    # All calls should have role="repository"
    for c in calls:
        assert c[0][2] == "repository"


# ---------------------------------------------------------------------------
# Plugin manifest
# ---------------------------------------------------------------------------


def test_plugin_manifest_hooks_on_graph_built():
    from repograph.plugins.static_analyzers.class_role.plugin import ClassRoleAnalyzerPlugin

    assert "on_graph_built" in ClassRoleAnalyzerPlugin.manifest.hooks


def test_plugin_analyze_calls_store():
    from repograph.plugins.static_analyzers.class_role.plugin import ClassRoleAnalyzerPlugin

    store = _mock_store([_cls("cls::a", "Foo", "app/models/foo.py", ["Base"])])
    plugin = ClassRoleAnalyzerPlugin()
    results = plugin.analyze(store=store)

    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["role"] == "repository"
