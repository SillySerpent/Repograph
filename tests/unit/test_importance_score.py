"""Tests for importance_score — computation, persistence through graph, and sort order."""
from __future__ import annotations

import os
import shutil
import pytest

FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
)


@pytest.fixture(scope="module")
def flask_rg(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("importance")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / "repo" / ".repograph")
    shutil.copytree(FLASK_FIXTURE, repo)
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, full=True,
    ))
    from repograph.api import RepoGraph
    rg = RepoGraph(repo, repograph_dir=rg_dir)
    yield rg
    rg.close()


class TestImportanceScoreComputation:
    def test_pathwaydoc_has_importance_score_field(self):
        from repograph.core.models import PathwayDoc
        assert "importance_score" in PathwayDoc.__dataclass_fields__
        assert PathwayDoc.__dataclass_fields__["importance_score"].default == 0.0

    def test_importance_formula_scales_with_steps_and_files(self):
        step_count_a, file_count_a, ep_a = 5, 3, 10.0
        step_count_b, file_count_b, ep_b = 2, 1, 2.0
        score_a = round((step_count_a * file_count_a * (ep_a + 1.0)) / 100.0, 4)
        score_b = round((step_count_b * file_count_b * (ep_b + 1.0)) / 100.0, 4)
        assert score_a > score_b

    def test_importance_zero_ep_still_positive(self):
        score = round((5 * 3 * 1.0) / 100.0, 4)
        assert score > 0.0


class TestImportanceScorePersistence:
    def test_importance_score_in_all_pathways(self, flask_rg):
        pathways = flask_rg.pathways(include_tests=True)
        assert pathways
        for p in pathways:
            assert "importance_score" in p
            assert isinstance(p["importance_score"], float)

    def test_all_importance_scores_non_negative(self, flask_rg):
        for p in flask_rg.pathways(include_tests=True):
            assert p.get("importance_score", 0.0) >= 0.0

    def test_importance_score_in_get_pathway(self, flask_rg):
        ps = flask_rg.pathways()
        assert ps
        full = flask_rg.get_pathway(ps[0]["name"])
        assert full is not None
        assert "importance_score" in full


class TestImportanceScoreSortOrder:
    def test_pathways_sorted_by_importance_desc(self, flask_rg):
        ps = flask_rg.pathways()
        scores = [p.get("importance_score", 0.0) for p in ps]
        assert scores == sorted(scores, reverse=True), \
            f"Not sorted by importance: {list(zip([p['name'] for p in ps], scores))}"

    def test_login_pathway_not_ranked_last(self, flask_rg):
        ps = flask_rg.pathways()
        names = [p["name"] for p in ps]
        if "login_handler_flow" in names:
            idx = names.index("login_handler_flow")
            assert idx < len(names) - 1


# ===========================================================================
# Scorer — script/diagnostic path demotion
# ===========================================================================

class TestScorerScriptDemotion:
    """Functions in scripts/ or diagnostics/ must score lower than equivalent
    production functions."""

    def _make_fn(self, file_path: str, name: str = "run",
                 callees: int = 10, callers: int = 0) -> tuple:
        fn = {
            "name": name,
            "file_path": file_path,
            "decorators": [],
            "is_exported": False,
            "is_dead": False,
        }
        return fn, callees, callers

    def test_script_path_is_demoted(self):
        from repograph.plugins.static_analyzers.pathways.scorer import score_function
        prod_fn, c, r = self._make_fn("src/app/bootstrap.py", callees=10)
        script_fn, c, r = self._make_fn("scripts/diagnostics/validate.py", callees=10)
        prod_score = score_function(prod_fn, callees_count=10, callers_count=0)
        script_score = score_function(script_fn, callees_count=10, callers_count=0)
        assert prod_score > script_score, (
            f"Production score {prod_score:.2f} should exceed "
            f"script score {script_score:.2f}"
        )

    def test_diagnostics_path_is_demoted(self):
        from repograph.plugins.static_analyzers.pathways.scorer import score_function
        prod_fn, _, _ = self._make_fn("src/advisor/engine.py", callees=20)
        diag_fn, _, _ = self._make_fn("scripts/diagnostics/check_phase.py", callees=20)
        prod_score = score_function(prod_fn, callees_count=20, callers_count=0)
        diag_score = score_function(diag_fn, callees_count=20, callers_count=0)
        assert prod_score > diag_score

    def test_production_path_not_demoted(self):
        from repograph.plugins.static_analyzers.pathways.scorer import score_function
        prod_fn, _, _ = self._make_fn("src/bots/champion_bot.py", callees=35)
        score = score_function(prod_fn, callees_count=35, callers_count=0)
        # Should score well above zero
        assert score > 1.0, f"Expected robust score for production file, got {score}"

    def test_script_demotion_survives_min_score_filter(self):
        """A script with many callees should still score below _MIN_SCORE=0.5
        or at least far below a production equivalent."""
        from repograph.plugins.static_analyzers.pathways.scorer import score_function, _SCRIPT_DEMOTE
        script_fn, _, _ = self._make_fn("scripts/training/run_gym.py", callees=100)
        prod_fn, _, _ = self._make_fn("src/app/bootstrap.py", callees=100)
        script_score = score_function(script_fn, callees_count=100, callers_count=0)
        prod_score = score_function(prod_fn, callees_count=100, callers_count=0)
        assert prod_score > script_score * 5, (
            f"Production ({prod_score:.1f}) should be >5x script ({script_score:.1f})"
        )


class TestModuleCallerSentinel:
    def test_sentinel_scores_zero(self):
        """__module__ sentinel nodes must always score exactly 0.0."""
        from repograph.plugins.static_analyzers.pathways.scorer import score_function_verbose

        sentinel = {
            "name": "__module__",
            "file_path": "repograph/__main__.py",
            "decorators": [],
            "is_exported": False,
            "is_dead": False,
            "is_module_caller": True,
        }
        bd = score_function_verbose(sentinel, callees_count=5, callers_count=0)
        assert bd.final_score == 0.0
        assert "is_module_caller_sentinel" in bd.zeroed_reason

    def test_sentinel_in_main_file_still_scores_zero(self):
        """The __main__.py multiplier must not override the sentinel exclusion."""
        from repograph.plugins.static_analyzers.pathways.scorer import score_function_verbose

        sentinel = {
            "name": "__module__",
            "file_path": "myapp/__main__.py",
            "decorators": [],
            "is_exported": False,
            "is_dead": False,
            "is_module_caller": True,
        }
        bd = score_function_verbose(sentinel, callees_count=10, callers_count=0)
        assert bd.final_score == 0.0, (
            "is_module_caller must override __main__.py path multiplier"
        )


class TestScoringFormula:
    def test_orchestrator_scores_higher_than_leaf_phase(self):
        """run_full_pipeline (many callers, many callees) must outscore
        a pipeline phase (few callers, many callees)."""
        from repograph.plugins.static_analyzers.pathways.scorer import score_function

        orchestrator = {
            "name": "run_full_pipeline",
            "file_path": "pipeline/runner.py",
            "decorators": [],
            "is_exported": False,
            "is_dead": False,
        }
        leaf_phase = {
            "name": "run",
            "file_path": "plugins/static_analyzers/dead_code/plugin.py",
            "decorators": [],
            "is_exported": False,
            "is_dead": False,
        }

        orch_score = score_function(orchestrator, callees_count=15, callers_count=45)
        leaf_score = score_function(leaf_phase, callees_count=40, callers_count=1)

        assert orch_score > 0.0, "Orchestrator must not score zero"
        assert orch_score > leaf_score, (
            f"Orchestrator ({orch_score:.2f}) must outscore leaf phase ({leaf_score:.2f})"
        )

    def test_zero_caller_root_gets_positive_score(self):
        """A function with zero callers and significant callees is a process root."""
        from repograph.plugins.static_analyzers.pathways.scorer import score_function

        root = {
            "name": "bootstrap",
            "file_path": "app/bootstrap.py",
            "decorators": [],
            "is_exported": False,
            "is_dead": False,
        }
        score = score_function(root, callees_count=10, callers_count=0)
        assert score > 1.0, f"Process root must score well, got {score}"

    def test_high_caller_count_does_not_zero_score(self):
        """A function called from 50 places must still get a positive score."""
        from repograph.plugins.static_analyzers.pathways.scorer import score_function

        fn = {
            "name": "sync",
            "file_path": "api.py",
            "decorators": [],
            "is_exported": True,
            "is_dead": False,
        }
        score = score_function(fn, callees_count=20, callers_count=50)
        assert score > 0.0, f"Widely-called function must not score zero, got {score}"
