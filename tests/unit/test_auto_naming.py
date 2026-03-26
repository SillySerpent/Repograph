"""Unit tests for _auto_name — improved pathway naming with generic-name detection."""
from __future__ import annotations

import os
import shutil
import pytest

from repograph.plugins.static_analyzers.pathways.assembler import (
    _auto_name,
    _GENERIC_FUNC_NAMES,
)


class TestAutoNameGenericDetection:
    """Generic single-word names must get a file-stem prefix."""

    def test_bare_run_gets_file_stem(self):
        name = _auto_name("run", file_path="repograph/pipeline/phases/p04_imports.py")
        assert "imports" in name, f"Expected 'imports' in '{name}'"
        assert name != "run_flow", "Generic 'run' must not produce bare 'run_flow'"

    def test_bare_main_gets_file_stem(self):
        name = _auto_name("main", file_path="repograph/interactive/main.py")
        # strips the p\d+ prefix — 'main' stem with 'main' func → just 'main_flow'
        assert name.endswith("_flow")
        assert len(name) > len("_flow")

    def test_underscore_function_gets_stem(self):
        name = _auto_name("_", file_path="scripts/diagnostics/validate_phase4.py")
        assert name != "_flow", "Single underscore function must not produce '_flow'"
        assert len(name) > len("_flow"), f"Name too short: '{name}'"

    def test_double_underscore_gets_stem(self):
        name = _auto_name("__", file_path="scripts/util/helpers.py")
        assert name != "__flow"

    def test_phase_prefix_stripped_from_stem(self):
        name = _auto_name("run", file_path="repograph/pipeline/phases/p11b_duplicates.py")
        assert "p11b" not in name, f"Phase prefix leaked into name: '{name}'"
        assert "duplicates" in name, f"Expected 'duplicates' in '{name}'"

    def test_two_different_run_funcs_get_distinct_names(self):
        name1 = _auto_name("run", file_path="pipeline/phases/p04_imports.py")
        name2 = _auto_name("run", file_path="pipeline/phases/p11b_duplicates.py")
        assert name1 != name2, f"Two 'run' functions produced identical name: '{name1}'"

    def test_start_is_generic(self):
        name = _auto_name("start", file_path="src/market/market_data_service.py")
        assert "market_data_service" in name or "market" in name

    def test_init_is_generic(self):
        name = _auto_name("init", file_path="src/storage/db.py")
        assert name != "init_flow"


class TestAutoNameClassPrefix:
    """Class-prefixed qualified names must use the class, not file stem."""

    def test_class_method_uses_class_prefix(self):
        name = _auto_name("submit_order", qualified_name="LiveBroker.submit_order")
        assert name.startswith("live_broker_"), f"Expected 'live_broker_' prefix, got '{name}'"

    def test_class_prefix_prevents_generic_fallback(self):
        # 'run' is generic but has a class prefix — use class prefix
        name = _auto_name("run", qualified_name="PipelineRunner.run",
                           file_path="pipeline/runner.py")
        assert "pipeline_runner" in name, f"Expected class prefix in '{name}'"
        assert "pipeline_runner" in name

    def test_on_tick_keeps_class_distinction(self):
        champ = _auto_name("on_tick", qualified_name="ChampionBot.on_tick")
        challenger = _auto_name("on_tick", qualified_name="ChallengerBot.on_tick")
        assert champ != challenger
        assert "champion_bot" in champ
        assert "challenger_bot" in challenger

    def test_camel_case_class_to_snake(self):
        name = _auto_name("compute", qualified_name="AdvisorEngine.compute")
        assert "advisor_engine" in name


class TestAutoNameNormalCases:
    """Non-generic names must be unchanged (modulo prefix strip)."""

    def test_normal_name_unchanged(self):
        name = _auto_name("detect_patterns")
        assert name == "detect_patterns_flow"

    def test_validate_credentials_unchanged(self):
        name = _auto_name("validate_credentials")
        assert name == "validate_credentials_flow"

    def test_flow_suffix_not_doubled(self):
        name = _auto_name("process_flow")
        assert name.count("_flow") == 1, f"Double '_flow' in '{name}'"

    def test_handle_prefix_stripped(self):
        name = _auto_name("handle_login")
        assert name == "login_flow"

    def test_on_prefix_stripped(self):
        name = _auto_name("on_bar_close")
        assert name == "bar_close_flow"

    def test_empty_base_uses_file_stem(self):
        # After stripping 'run_' from 'run', base is empty — use stem
        name = _auto_name("run_", file_path="src/app/worker.py")
        assert name.endswith("_flow")
        assert name != "_flow"


class TestAutoNamePipelineIntegration:
    """Full pipeline run: verify no pathway has a hash-suffix name for common functions."""

    FLASK_FIXTURE = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
    )

    @pytest.fixture(scope="class")
    def flask_pathways(self, tmp_path_factory):
        tmp = tmp_path_factory.mktemp("naming")
        repo = str(tmp / "repo")
        rg_dir = str(tmp / "repo" / ".repograph")
        shutil.copytree(self.FLASK_FIXTURE, repo)
        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        from repograph.graph_store.store import GraphStore
        run_full_pipeline(RunConfig(
            repo_root=repo, repograph_dir=rg_dir,
            include_git=False, full=True,
        ))
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        ps = store.get_all_pathways()
        store.close()
        return ps

    def test_no_pathway_named_bare_flow(self, flask_pathways):
        names = [p["name"] for p in flask_pathways]
        assert "_flow" not in names, "Bare '_flow' pathway present"
        assert "__flow" not in names, "Bare '__flow' pathway present"

    def test_no_hash_suffixed_names_for_flask_fixture(self, flask_pathways):
        """Flask fixture has no collisions — no name should end in a 10-char hex suffix."""
        import re
        hex_suffix = re.compile(r"_[0-9a-f]{10}$")
        for p in flask_pathways:
            assert not hex_suffix.search(p["name"]), (
                f"Hash-suffixed name found: '{p['name']}' — "
                "file-stem prefix should have prevented the collision"
            )

    def test_all_pathway_names_are_meaningful(self, flask_pathways):
        """Every pathway name must contain at least one meaningful word (>3 chars)."""
        for p in flask_pathways:
            words = [w for w in p["name"].replace("_flow", "").split("_") if len(w) > 3]
            assert words, f"Pathway name '{p['name']}' has no meaningful words"
