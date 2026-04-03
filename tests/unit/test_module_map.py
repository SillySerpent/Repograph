"""Phase 16 module index: prod/test file split and test function counts."""
from __future__ import annotations

import os
import shutil

import pytest

FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
)


@pytest.fixture(scope="module")
def flask_modules(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("module_map")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / ".repograph")
    shutil.copytree(FLASK_FIXTURE, repo)
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    run_full_pipeline(
        RunConfig(
            repo_root=repo,
            repograph_dir=rg_dir,
            include_git=False,
            full=True,
        )
    )
    from repograph.surfaces.api import RepoGraph

    with RepoGraph(repo, repograph_dir=rg_dir) as rg:
        mods = rg.modules()
    return mods


class TestModuleMapFields:
    def test_required_keys_and_invariants(self, flask_modules):
        assert flask_modules, "expected non-empty module list"
        for m in flask_modules:
            assert "path" in m and "display" in m
            prod = m["prod_file_count"]
            tst_files = m["test_file_count"]
            total = m["total_file_count"]
            assert total == prod + tst_files
            assert m["file_count"] == prod
            assert isinstance(m.get("test_function_count", 0), int)
            assert m["test_function_count"] >= 0

    def test_flask_tests_module_has_test_functions(self, flask_modules):
        # python_flask/tests/test_routes.py lives under module "tests"
        tests_row = next((m for m in flask_modules if m["path"] == "tests"), None)
        assert tests_row is not None
        assert tests_row["test_file_count"] >= 1
        assert tests_row["test_function_count"] >= 1
