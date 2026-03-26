"""Tests for vendored library detection — is_likely_vendored() and pipeline integration."""
from __future__ import annotations

import os
import shutil
import pytest

from repograph.utils.fs import is_likely_vendored, _KNOWN_OSS_PACKAGES

VENDORED_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "vendored_project")
)


# ---------------------------------------------------------------------------
# is_likely_vendored() unit tests
# ---------------------------------------------------------------------------

class TestIsLikelyVendored:
    def test_known_package_with_init_and_marker_is_vendored(self, tmp_path):
        """aiosqlite dir with __init__.py + pyproject.toml → vendored."""
        pkg = tmp_path / "aiosqlite"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "pyproject.toml").write_text("[project]\nname='aiosqlite'\n")
        assert is_likely_vendored(str(pkg)) is True

    def test_known_package_without_marker_not_vendored(self, tmp_path):
        """aiosqlite dir with only __init__.py (no pyproject/setup) → not vendored."""
        pkg = tmp_path / "aiosqlite"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        assert is_likely_vendored(str(pkg)) is False

    def test_unknown_package_not_vendored(self, tmp_path):
        """Custom package named 'myapp' is never flagged as vendored."""
        pkg = tmp_path / "myapp"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "pyproject.toml").write_text("[project]\nname='myapp'\n")
        assert is_likely_vendored(str(pkg)) is False

    def test_known_package_no_init_not_vendored(self, tmp_path):
        """aiosqlite dir without __init__.py → not a Python package → not vendored."""
        pkg = tmp_path / "aiosqlite"
        pkg.mkdir()
        (pkg / "pyproject.toml").write_text("")
        assert is_likely_vendored(str(pkg)) is False

    def test_all_known_packages_in_frozenset(self):
        """Spot-check: critical packages are in _KNOWN_OSS_PACKAGES."""
        for expected in ("aiosqlite", "requests", "flask", "kuzu"):
            assert expected in _KNOWN_OSS_PACKAGES, f"'{expected}' missing from known packages"

    def test_pkg_info_marker_triggers_detection(self, tmp_path):
        """PKG-INFO (pip-installed marker) also counts as a vendor marker."""
        pkg = tmp_path / "requests"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "PKG-INFO").write_text("Metadata-Version: 2.1\nName: requests\n")
        assert is_likely_vendored(str(pkg)) is True

    def test_hyphenated_name_normalised(self, tmp_path):
        """Directory named 'charset-normalizer' → normalised to 'charset_normalizer'."""
        pkg = tmp_path / "charset-normalizer"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "METADATA").write_text("Name: charset-normalizer\n")
        assert is_likely_vendored(str(pkg)) is True


# ---------------------------------------------------------------------------
# Pipeline: walk_repo tags vendored files
# ---------------------------------------------------------------------------

class TestWalkRepoVendoredTagging:
    def test_files_in_vendored_dir_are_tagged(self, tmp_path):
        """walk_repo must set is_vendored=True on files inside vendored dirs."""
        shutil.copytree(VENDORED_FIXTURE, tmp_path / "repo")
        repo = str(tmp_path / "repo")
        from repograph.utils.fs import walk_repo
        records = walk_repo(repo)
        by_path = {r.path: r for r in records}
        # aiosqlite/__init__.py must be tagged vendored
        vendored_recs = [r for r in records if r.is_vendored]
        app_recs = [r for r in records if not r.is_vendored]
        assert vendored_recs, "No vendored files detected in fixture"
        assert app_recs, "All files were flagged vendored — app files must not be"
        for r in vendored_recs:
            assert "aiosqlite" in r.path, f"Unexpected vendored path: {r.path}"
        for r in app_recs:
            assert "aiosqlite" not in r.path

    def test_non_vendored_files_not_tagged(self, tmp_path):
        shutil.copytree(VENDORED_FIXTURE, tmp_path / "repo")
        from repograph.utils.fs import walk_repo
        records = walk_repo(str(tmp_path / "repo"))
        for r in records:
            if "src/app" in r.path:
                assert r.is_vendored is False, \
                    f"App file incorrectly tagged as vendored: {r.path}"


# ---------------------------------------------------------------------------
# Context formatter: vendored steps excluded from pathway docs
# ---------------------------------------------------------------------------

class TestVendoredStepsExcluded:
    def _make_steps(self, paths_and_names):
        return [
            {
                "order": i, "step_order": i,
                "function_name": name,
                "file_path": path,
                "line_start": 1, "line_end": 10,
                "role": "entry" if i == 0 else "service",
                "decorators": [], "confidence": 0.9,
            }
            for i, (path, name) in enumerate(paths_and_names)
        ]

    def _format(self, steps):
        import tempfile
        from repograph.plugins.exporters.pathway_contexts.formatter import format_context_doc
        from repograph.plugins.exporters.pathway_contexts.budget import TokenBudgetManager
        from repograph.graph_store.store import GraphStore
        pathway = {
            "name": "t", "display_name": "T", "source": "auto",
            "confidence": 0.9, "description": "", "variable_threads": "[]",
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = GraphStore(os.path.join(tmp, "t.db"))
            store.initialize_schema()
            return format_context_doc(pathway, steps, store, TokenBudgetManager())

    def test_vendored_steps_absent_from_execution_steps(self):
        """Steps in aiosqlite/ must NOT appear in EXECUTION STEPS."""
        steps = self._make_steps([
            ("src/app/service.py", "DataService.fetch_records"),
            ("aiosqlite/__init__.py", "Connection.execute"),
            ("aiosqlite/__init__.py", "Connection.commit"),
        ])
        doc = self._format(steps)
        assert "DataService.fetch_records" in doc
        assert "Connection.execute" not in doc
        assert "Connection.commit" not in doc

    def test_vendored_footnote_present_when_steps_excluded(self):
        """A footnote mentioning vendored lib must appear when steps are excluded."""
        steps = self._make_steps([
            ("src/app/service.py", "DataService.insert_record"),
            ("aiosqlite/__init__.py", "connect"),
        ])
        doc = self._format(steps)
        assert "vendored" in doc.lower(), \
            f"Expected 'vendored' footnote in doc, got:\n{doc[:500]}"

    def test_no_vendored_steps_no_footnote(self):
        """When there are no vendored steps, no footnote should appear."""
        steps = self._make_steps([
            ("src/app/service.py", "DataService.fetch_records"),
            ("src/storage/db.py", "init_db"),
        ])
        doc = self._format(steps)
        assert "vendored" not in doc.lower()

    def test_all_vendored_pathway_still_renders(self):
        """A pathway with only vendored steps must render without crashing."""
        steps = self._make_steps([
            ("aiosqlite/__init__.py", "connect"),
            ("aiosqlite/__init__.py", "Connection.__init__"),
        ])
        doc = self._format(steps)
        assert "PATHWAY:" in doc   # header still present


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------

class TestVendoredPipelineIntegration:
    def test_vendored_files_indexed_but_not_in_pathway_steps(self, tmp_path):
        """Vendored files are indexed in the graph (for call resolution) but
        their functions must not appear as named steps in pathway context docs."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / "repo" / ".repograph")
        shutil.copytree(VENDORED_FIXTURE, repo)

        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        run_full_pipeline(RunConfig(
            repo_root=repo, repograph_dir=rg_dir,
            include_git=False, full=True,
        ))

        from repograph.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            ps = rg.pathways(include_tests=True)
            for p in ps:
                full = rg.get_pathway(p["name"])
                if not full:
                    continue
                doc = full.get("context_doc", "")
                # Connection.execute and Connection.commit are vendored internals
                assert "Connection.execute" not in doc, \
                    f"Vendored Connection.execute leaked into pathway '{p['name']}'"
                assert "Connection.commit" not in doc, \
                    f"Vendored Connection.commit leaked into pathway '{p['name']}'"
