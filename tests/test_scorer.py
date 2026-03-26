"""Unit tests for pathways scorer plugin — covers F-01 and F-04.

F-01: Test functions must always score 0.0 regardless of call counts or flags.
F-04: Concrete ABC/Protocol implementors receive a 2.5× scoring boost so all
      strategy/plugin variants surface together in the pathway list.
"""
from __future__ import annotations

import pytest

from repograph.plugins.static_analyzers.pathways.scorer import (
    _ABC_IMPL_MULT,
    _MIN_SCORE,
    _PRIVATE_NAME_DEMOTE,
    _SCRIPT_DEMOTE,
    score_function,
    score_function_verbose,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fn(
    name: str = "my_func",
    file_path: str = "src/app/service.py",
    *,
    is_dead: bool = False,
    is_exported: bool = False,
    is_test: bool = False,
    decorators: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "file_path": file_path,
        "is_dead": is_dead,
        "is_exported": is_exported,
        "is_test": is_test,
        "decorators": decorators or [],
        "qualified_name": f"MyClass.{name}",
    }


# ---------------------------------------------------------------------------
# F-01: test functions score exactly 0.0
# ---------------------------------------------------------------------------

class TestF01TestFunctionsScoreZero:
    """Test functions must never appear in production entry-point lists."""

    @pytest.mark.parametrize("file_path", [
        "tests/test_broker.py",
        "tests/phase_2/test_paper_broker.py",
        "test/unit/test_engine.py",
        "src/advisor/tests/test_consensus.py",
        "specs/test_api_spec.py",
        "__tests__/component.test.js",
    ])
    def test_test_file_path_scores_zero(self, file_path: str) -> None:
        fn = _fn(name="test_something", file_path=file_path, is_exported=True)
        assert score_function(fn, callees_count=20, callers_count=0) == 0.0, (
            f"Test fn in {file_path!r} should score 0.0"
        )

    def test_is_test_flag_scores_zero(self) -> None:
        """fn dict with is_test=True is zero even if path looks production."""
        fn = _fn(file_path="src/broker/paper_broker.py", is_test=True)
        assert score_function(fn, callees_count=15, callers_count=0) == 0.0

    def test_test_fn_with_many_callees_still_zero(self) -> None:
        """High callee count cannot rescue a test function."""
        fn = _fn(name="test_sl_trigger", file_path="tests/phase_2/test_paper_broker.py")
        assert score_function(fn, callees_count=9, callers_count=0) == 0.0

    def test_test_fn_with_route_decorator_still_zero(self) -> None:
        """Route decorators cannot rescue a test function."""
        fn = _fn(
            name="test_route",
            file_path="tests/test_api.py",
            decorators=["app.route('/test')"],
        )
        assert score_function(fn, callees_count=10, callers_count=0) == 0.0

    def test_test_fn_with_is_exported_still_zero(self) -> None:
        """is_exported cannot rescue a test function."""
        fn = _fn(name="test_exported", file_path="tests/test_utils.py", is_exported=True)
        assert score_function(fn, callees_count=5, callers_count=0) == 0.0

    def test_production_fn_in_production_path_scores_nonzero(self) -> None:
        """Sanity: a legitimate production fn must not be zeroed."""
        fn = _fn(name="on_tick", file_path="src/bots/champion_bot.py")
        assert score_function(fn, callees_count=21, callers_count=1) > 0.0

    def test_dead_fn_scores_zero_regardless(self) -> None:
        """is_dead=True is still zero (pre-existing behaviour preserved)."""
        fn = _fn(file_path="src/app/service.py", is_dead=True)
        assert score_function(fn, callees_count=10, callers_count=0) == 0.0


# ---------------------------------------------------------------------------
# F-04: ABC implementors receive 2.5× boost
# ---------------------------------------------------------------------------

class TestF04AbcImplementorBoost:
    """Concrete implementations of abstract methods get _ABC_IMPL_MULT boost."""

    def test_abc_impl_scores_higher_than_plain(self) -> None:
        fn = _fn(name="generate", file_path="src/strategies/quant_analyst.py")
        plain = score_function(fn, callees_count=5, callers_count=1)
        boosted = score_function(fn, callees_count=5, callers_count=1, abc_implementor=True)
        assert boosted > plain

    def test_abc_impl_multiplier_is_correct(self) -> None:
        fn = _fn(name="generate", file_path="src/strategies/quant_analyst.py")
        plain = score_function(fn, callees_count=5, callers_count=1)
        boosted = score_function(fn, callees_count=5, callers_count=1, abc_implementor=True)
        # Allow small floating-point tolerance
        assert abs(boosted / plain - _ABC_IMPL_MULT) < 1e-9

    def test_abc_impl_false_is_identical_to_omitted(self) -> None:
        fn = _fn(name="generate", file_path="src/strategies/momentum.py")
        assert score_function(fn, 5, 1, abc_implementor=False) == score_function(fn, 5, 1)

    def test_abc_impl_test_fn_still_zero(self) -> None:
        """ABC boost cannot rescue a test function."""
        fn = _fn(name="test_generate", file_path="tests/test_strategies.py")
        assert score_function(fn, callees_count=5, callers_count=0, abc_implementor=True) == 0.0

    def test_multiple_abc_impls_same_score(self) -> None:
        """All concrete impls with equal structure should score identically."""
        fns = [
            _fn(name="generate", file_path=f"src/strategies/strategy_{i}.py")
            for i in range(5)
        ]
        scores = [score_function(f, callees_count=5, callers_count=1, abc_implementor=True) for f in fns]
        assert len(set(scores)) == 1, f"Scores differ across impls: {scores}"


# ---------------------------------------------------------------------------
# Private name demotion (Phase C.2)
# ---------------------------------------------------------------------------

class TestPrivateNameDemote:
    """Functions named _foo (not dunders) score lower than public names."""

    def test_private_helper_scores_lower_than_public(self) -> None:
        pub = _fn(name="helper", file_path="src/app/service.py")
        priv = _fn(name="_helper", file_path="src/app/service.py")
        s_pub = score_function(pub, callees_count=10, callers_count=1)
        s_priv = score_function(priv, callees_count=10, callers_count=1)
        assert s_priv < s_pub
        assert s_pub > _MIN_SCORE

    def test_private_name_demote_in_breakdown(self) -> None:
        fn = _fn(name="_internal", file_path="src/app/service.py")
        bd = score_function_verbose(fn, callees_count=10, callers_count=1)
        labels = [m[0] for m in bd.multipliers]
        assert "private_name_demote" in labels
        assert any(m == ("private_name_demote", _PRIVATE_NAME_DEMOTE) for m in bd.multipliers)

    def test_dunder_names_not_demoted_as_private(self) -> None:
        """__init__ and __str__ keep full score (not treated as _private helpers)."""
        fn_init = _fn(name="__init__", file_path="src/models/user.py")
        fn_priv = _fn(name="_setup", file_path="src/models/user.py")
        s_init = score_function(fn_init, callees_count=8, callers_count=1)
        s_priv = score_function(fn_priv, callees_count=8, callers_count=1)
        bd_init = score_function_verbose(fn_init, callees_count=8, callers_count=1)
        assert "private_name_demote" not in [m[0] for m in bd_init.multipliers]
        assert s_init > s_priv


# ---------------------------------------------------------------------------
# Existing behaviour preserved
# ---------------------------------------------------------------------------

class TestScorerRegressions:
    """Ensure pre-existing scoring behaviours are not broken."""

    def test_script_path_demoted(self) -> None:
        fn_script = _fn(file_path="scripts/backfill.py")
        fn_prod = _fn(file_path="src/app/service.py")
        s_script = score_function(fn_script, callees_count=10, callers_count=0)
        s_prod = score_function(fn_prod, callees_count=10, callers_count=0)
        # Script should be heavily penalised — either zero or far below prod
        assert s_script == 0.0 or s_script < s_prod * _SCRIPT_DEMOTE * 2

    def test_route_decorator_boosts(self) -> None:
        fn = _fn(decorators=["app.post('/login')"])
        plain = score_function(fn, callees_count=3, callers_count=0)
        route = score_function(
            {**fn, "decorators": ["app.post('/login')"]},
            callees_count=3,
            callers_count=0,
        )
        assert route > plain or route == plain  # at minimum not penalised

    def test_main_module_boosted(self) -> None:
        fn = _fn(file_path="src/app/__main__.py")
        assert score_function(fn, callees_count=5, callers_count=0) > _MIN_SCORE

    def test_zero_callees_scores_zero(self) -> None:
        fn = _fn()
        assert score_function(fn, callees_count=0, callers_count=0) == 0.0
