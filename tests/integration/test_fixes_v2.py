"""
Integration tests for all RepoGraph fixes and improvements.

Each test class maps to a specific fix or improvement:

  Fix1  — Closure-returned functions not flagged dead
  Fix2  — Typed local variable method resolution
  Fix3  — Module-level call tracking
  Imp1  — JS script-tag global scope exemption
  Imp2  — Dead code confidence tier filtering
  Imp3  — Duplicate symbol detection
  Imp4  — Doc-vs-code symbol cross-check
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

FIXTURES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures"))

SIMPLE = os.path.join(FIXTURES, "python_simple")
FLASK  = os.path.join(FIXTURES, "python_flask")


def _copy(src: str, dst: str) -> None:
    shutil.copytree(src, dst)


def _full_run(repo: str, rg_dir: str, *, include_git: bool = False):
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    return run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=include_git, include_embeddings=False, full=True,
    ))


def _store(rg_dir: str):
    from repograph.graph_store.store import GraphStore
    s = GraphStore(os.path.join(rg_dir, "graph.db"))
    s.initialize_schema()
    return s


# ===========================================================================
# Fix 1 — Closure-returned functions not flagged dead
# ===========================================================================

class TestFix1ClosureExemption:
    """Functions that are the return value of their parent must not be dead."""

    def test_closure_exempted_in_pipeline(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "closure_factory"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead = {r["qualified_name"] for r in s.get_dead_functions()}
        s.close()

        assert "make_handler._handle" not in dead
        assert "make_stop._stop" not in dead

    def test_schema_fields_present(self, tmp_path):
        """is_closure_returned must be stored and queryable."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "closure_factory"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        rows = s.query(
            "MATCH (f:Function {is_closure_returned: true}) "
            "RETURN f.qualified_name"
        )
        s.close()
        names = {r[0] for r in rows}
        assert len(names) >= 1, "No is_closure_returned=true functions found"


# ===========================================================================
# Fix 2 — Typed local variable method resolution
# ===========================================================================

class TestFix2TypedLocalResolution:
    """Methods called via typed local variables must generate CALLS edges."""

    def test_typed_local_method_not_dead(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "typed_local"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead = {r["qualified_name"] for r in s.get_dead_functions()}
        s.close()

        # DataEngine.process and DataEngine.validate are called via
        # eng = DataEngine(); eng.process(...) / eng.validate(...)
        assert "DataEngine.process" not in dead, \
            "DataEngine.process (typed local callee) wrongly flagged dead"
        assert "DataEngine.validate" not in dead, \
            "DataEngine.validate (typed local callee) wrongly flagged dead"

    def test_typed_local_edge_has_typed_local_reason(self, tmp_path):
        """The CALLS edge for a typed-local resolution must have reason='typed_local'."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "typed_local"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        rows = s.query(
            "MATCH (a:Function)-[e:CALLS {reason: 'typed_local'}]->(b:Function) "
            "RETURN b.qualified_name"
        )
        s.close()
        resolved = {r[0] for r in rows}
        # At least one of the engine methods should be resolved via typed_local
        assert resolved, "No typed_local CALLS edges found"


# ===========================================================================
# Fix 3 — Module-level call tracking
# ===========================================================================

class TestFix3ModuleLevelCalls:
    """Functions called only at module scope must not be flagged dead."""

    def test_module_callee_not_dead(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "module_level_call"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead = {r["qualified_name"] for r in s.get_dead_functions()}
        s.close()

        assert "get_default_config_path" not in dead
        assert "get_repo_root" not in dead

    def test_sentinel_not_in_dead_output(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "module_level_call"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead = s.get_dead_functions()
        s.close()

        assert not any("__module__" in r["qualified_name"] for r in dead)

    def test_is_module_caller_field_queryable(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "module_level_call"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        rows = s.query(
            "MATCH (f:Function {is_module_caller: true}) RETURN f.name"
        )
        s.close()
        assert rows, "No is_module_caller=true functions found in DB"


# ===========================================================================
# Improvement 1 — JS script-tag global scope
# ===========================================================================

class TestImp1ScriptTagGlobals:
    """JS module-scope functions in script-tag files must not be dead."""

    def test_script_globals_not_dead(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "script_tag_globals"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead = {r["qualified_name"] for r in s.get_dead_functions()}
        s.close()

        for name in ("formatPrice", "formatTs", "apiFetch"):
            assert name not in dead, f"{name!r} wrongly flagged dead"

    def test_html_imports_js_edge_created(self, tmp_path):
        """Phase 4 must create IMPORTS edges from index.html to the JS files."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "script_tag_globals"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        rows = s.query(
            "MATCH (h:File {language: 'html'})-[:IMPORTS]->(js:File) "
            "RETURN js.path"
        )
        s.close()
        js_paths = {r[0] for r in rows}
        assert any("utils.js" in p for p in js_paths), \
            f"No IMPORTS edge from HTML to utils.js found: {js_paths}"

    def test_is_script_global_field_stored(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "script_tag_globals"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        rows = s.query(
            "MATCH (f:Function {is_script_global: true}) RETURN f.name"
        )
        s.close()
        names = {r[0] for r in rows}
        assert "formatPrice" in names or "apiFetch" in names, \
            f"Expected script globals in DB, got: {names}"


# ===========================================================================
# Improvement 2 — Dead code confidence tiers
# ===========================================================================

class TestImp2DeadCodeTiers:
    """min_tier filtering must work correctly on the public API."""

    def test_definitely_dead_subset_of_probably_dead(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(SIMPLE, repo)
        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            definite = rg.dead_code(min_tier="definitely_dead")
            probable = rg.dead_code(min_tier="probably_dead")
            possible = rg.dead_code(min_tier="possibly_dead")

        definite_ids = {r["id"] for r in definite}
        probable_ids = {r["id"] for r in probable}
        possible_ids = {r["id"] for r in possible}

        assert definite_ids.issubset(probable_ids), \
            "definitely_dead must be a subset of probably_dead"
        assert probable_ids.issubset(possible_ids), \
            "probably_dead must be a subset of possibly_dead"

    def test_all_results_have_tier_field(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(SIMPLE, repo)
        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            results = rg.dead_code()

        for r in results:
            assert "dead_code_tier" in r, f"Missing dead_code_tier: {r}"
            assert r["dead_code_tier"] in (
                "definitely_dead", "probably_dead", "possibly_dead"
            ), f"Unexpected tier: {r['dead_code_tier']}"

    def test_module_sentinel_never_in_results(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "module_level_call"), repo)
        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            results = rg.dead_code(min_tier="possibly_dead")

        assert not any("__module__" in r["qualified_name"] for r in results), \
            "__module__ sentinel must never appear in dead_code() output"


# ===========================================================================
# Improvement 3 — Duplicate symbol detection
# ===========================================================================

class TestImp3DuplicateDetection:
    """Duplicate symbol groups must be findable via the public API."""

    def test_duplicates_returns_list(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "duplicate_symbols"), repo)
        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            dups = rg.duplicates()

        assert isinstance(dups, list)

    def test_duplicate_found_in_fixture(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "duplicate_symbols"), repo)
        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            dups = rg.duplicates(min_severity="high")

        names = {d["name"] for d in dups}
        assert "new_decision_id" in names

    def test_duplicate_dict_has_required_keys(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "duplicate_symbols"), repo)
        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            dups = rg.duplicates()

        required = {"name", "kind", "occurrence_count", "file_paths",
                    "severity", "reason", "is_superseded"}
        for d in dups:
            missing = required - set(d.keys())
            assert not missing, f"Duplicate group missing keys: {missing}"

    def test_rerun_is_idempotent(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "duplicate_symbols"), repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        count1 = len(s.get_all_duplicate_symbols())

        from repograph.plugins.static_analyzers.duplicates.plugin import run_duplicate_analysis
        run_duplicate_analysis(s)
        count2 = len(s.get_all_duplicate_symbols())
        s.close()

        assert count1 == count2, \
            f"Re-run changed duplicate count: {count1} → {count2}"


# ===========================================================================
# Improvement 4 — Doc symbol cross-check
# ===========================================================================

class TestImp4DocWarnings:
    """Doc warnings must be findable and have correct structure."""

    def test_doc_warnings_api_returns_list(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "doc_staleness"), repo)

        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            warnings = rg.doc_warnings()

        assert isinstance(warnings, list)

    def test_doc_warnings_have_required_keys(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "doc_staleness"), repo)

        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            warnings = rg.doc_warnings()

        required = {"doc_path", "line_number", "symbol_text",
                    "warning_type", "severity", "context_snippet"}
        for w in warnings:
            assert not (required - set(w.keys())), \
                f"Warning missing keys: {required - set(w.keys())}"

    def test_rerun_doc_warnings_idempotent(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(os.path.join(FIXTURES, "doc_staleness"), repo)

        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        count1 = len(s.get_all_doc_warnings())
        from repograph.plugins.exporters.doc_warnings.plugin import run as run_doc_warnings
        run_doc_warnings(s)
        count2 = len(s.get_all_doc_warnings())
        s.close()

        assert count1 == count2


# ===========================================================================
# Regression — existing tests still pass after all changes
# ===========================================================================

class TestRegression:
    """Confirm the python_simple and python_flask fixtures still index correctly."""

    def test_simple_fixture_indexes(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(SIMPLE, repo)
        stats = _full_run(repo, rg_dir)
        assert stats["files"] > 0
        assert stats["functions"] > 0

    def test_flask_fixture_indexes(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(FLASK, repo)
        stats = _full_run(repo, rg_dir)
        assert stats["files"] > 0
        assert stats["functions"] > 0

    def test_dead_code_returns_list(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(SIMPLE, repo)
        _full_run(repo, rg_dir)
        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            assert isinstance(rg.dead_code(), list)

    def test_entry_points_returns_list(self, tmp_path):
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(SIMPLE, repo)
        _full_run(repo, rg_dir)
        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            assert isinstance(rg.entry_points(), list)


# ===========================================================================
# Fix — Aliased import resolution ("from M import X as Y")
# ===========================================================================

class TestAliasImportResolution:
    """Functions imported under an alias must not be flagged dead.

    Reproduces the bug where:
        from scorer import score_function as _score_fn
        score = _score_fn(item)
    caused score_function to appear dead because the call resolver only
    checked for the alias name "_score_fn" in imported_names, not the
    original "score_function".
    """

    FIXTURE = os.path.join(FIXTURES, "alias_import")

    def test_aliased_function_not_dead(self, tmp_path):
        """score_function must NOT be dead — it is called via _score_fn."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(self.FIXTURE, repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead = {r["qualified_name"] for r in s.get_dead_functions()}
        s.close()

        assert "score_function" not in dead, (
            "score_function should be alive — it is called via the alias _score_fn"
        )

    def test_truly_unused_function_still_dead(self, tmp_path):
        """unused_helper has no callers and must remain dead."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(self.FIXTURE, repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead = {r["qualified_name"] for r in s.get_dead_functions()}
        s.close()

        assert "unused_helper" in dead, (
            "unused_helper has no callers and should be dead"
        )

    def test_calls_edge_created_through_alias(self, tmp_path):
        """A CALLS edge must exist from compute_scores to score_function."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(self.FIXTURE, repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        rows = s.query(
            "MATCH (caller:Function)-[:CALLS]->(callee:Function) "
            "WHERE callee.qualified_name = 'score_function' "
            "RETURN caller.qualified_name"
        )
        s.close()

        callers = {r[0] for r in rows}
        assert "compute_scores" in callers, (
            f"Expected compute_scores → score_function CALLS edge, got callers: {callers}"
        )

    def test_alias_map_captured_by_parser(self, tmp_path):
        """The parser must populate the aliases dict on the ImportNode."""
        import sys, os as _os
        from repograph.plugins.parsers.python.python_parser import PythonParser
        from repograph.core.models import FileRecord

        src = self.FIXTURE + "/caller.py"
        fr = FileRecord(
            path="caller.py", abs_path=src, name="caller.py",
            extension=".py", language="python", size_bytes=0,
            line_count=0, source_hash="", is_test=False,
            is_config=False, mtime=0.0,
        )
        with open(src, "rb") as fh:
            source_bytes = fh.read()

        parser = PythonParser()
        parsed = parser.parse(source_bytes, fr)

        alias_maps = {}
        for imp in parsed.imports:
            alias_maps.update(imp.aliases)

        assert "_score_fn" in alias_maps, (
            f"Expected alias '_score_fn' in import aliases, got: {alias_maps}"
        )
        assert alias_maps["_score_fn"] == "score_function", (
            f"Expected '_score_fn' -> 'score_function', got: {alias_maps}"
        )


# ===========================================================================
# Fix — Community detection: isolated singletons grouped into named buckets
# ===========================================================================

class TestCommunityIsolatedSingletons:
    """Isolated functions (no cross-community edges) must not stay as size-1
    communities — they should be grouped by package label into named buckets.
    """

    ISOLATE_FIXTURE = os.path.join(FIXTURES, "isolated_utilities")

    def test_same_label_singletons_are_grouped(self, tmp_path):
        """Functions in the same package directory but with no cross-edges
        must be grouped into a single named community, not left as individual
        size-1 nodes."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(self.ISOLATE_FIXTURE, repo)
        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            comms = rg.communities()

        total = len(comms)
        singletons = sum(1 for c in comms if c.get("member_count", 0) == 1)

        # pct_change, format_pct (not called from main) should be grouped
        # into their utils bucket, not left as 2 individual singletons.
        # Even if they can't be merged into a larger community, they should
        # be grouped with each other rather than staying size-1.
        # With 4 files, expect at most 1 singleton (tolerant for edge cases).
        assert singletons <= 1, (
            f"Expected ≤1 singleton community, got {singletons}/{total}. "
            f"Isolated functions in the same package should be grouped."
        )

    def test_meaningful_communities_labelled(self, tmp_path):
        """Communities must have non-empty labels after the merge pass."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(FLASK, repo)
        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            comms = rg.communities()

        for c in comms:
            assert c.get("label"), f"Community has no label: {c}"


# ===========================================================================
# Fix — Dead code context: dead_everywhere vs dead_in_production
# ===========================================================================

class TestDeadCodeContext:
    """Functions with is_dead=True must carry a dead_context field
    distinguishing functions never called anywhere from functions only
    called from tests or scripts.
    """

    FIXTURE = os.path.join(FIXTURES, "dead_context_fixture")

    def test_dead_everywhere_has_correct_context(self, tmp_path):
        """A function with zero callers anywhere must be dead_everywhere."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(self.FIXTURE, repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead = {r["qualified_name"]: r for r in s.get_dead_functions()}
        s.close()

        assert "dead_everywhere" in dead, (
            f"dead_everywhere not found in dead functions: {list(dead.keys())}"
        )
        ctx = dead["dead_everywhere"].get("dead_context", "")
        assert ctx == "dead_everywhere", (
            f"Expected dead_context='dead_everywhere', got {ctx!r}"
        )

    def test_dead_in_production_has_correct_context(self, tmp_path):
        """A function only called from tests must be dead_in_production."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(self.FIXTURE, repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead = {r["qualified_name"]: r for r in s.get_dead_functions()}
        s.close()

        assert "dead_in_production" in dead, (
            f"dead_in_production not found in dead: {list(dead.keys())}"
        )
        ctx = dead["dead_in_production"].get("dead_context", "")
        assert ctx == "dead_in_production", (
            f"Expected dead_context='dead_in_production', got {ctx!r}"
        )

    def test_alive_function_not_dead(self, tmp_path):
        """alive_function is called from main.py and must not be flagged dead."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(self.FIXTURE, repo)
        _full_run(repo, rg_dir)

        s = _store(rg_dir)
        dead_names = {r["qualified_name"] for r in s.get_dead_functions()}
        s.close()

        assert "alive_function" not in dead_names, (
            "alive_function is called from main.py and must not be dead"
        )

    def test_dead_context_field_in_api_response(self, tmp_path):
        """The dead_context key must appear in every item from rg.dead_code()."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        _copy(self.FIXTURE, repo)
        _full_run(repo, rg_dir)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            dead = rg.dead_code()

        for item in dead:
            assert "dead_context" in item, (
                f"dead_context key missing from dead_code() item: {item}"
            )
