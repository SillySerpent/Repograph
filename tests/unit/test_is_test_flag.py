"""Tests that is_test is correctly set on Function nodes."""
from __future__ import annotations

import os
import shutil

import pytest

FIXTURE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "dead_context_fixture")
)


@pytest.fixture(scope="module")
def rg(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("is_test_flag")
    repo = str(tmp / "repo")
    shutil.copytree(FIXTURE_PATH, repo)
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    run_full_pipeline(
        RunConfig(
            repo_root=repo,
            repograph_dir=str(tmp / "rg"),
            include_git=False,
            full=True,
        )
    )
    from repograph.surfaces.api import RepoGraph

    r = RepoGraph(repo, repograph_dir=str(tmp / "rg"))
    yield r
    r.close()


class TestIsTestFlag:
    def test_production_functions_have_is_test_false(self, rg):
        fns = rg._get_store().get_all_functions()
        prod = [f for f in fns if "test" not in (f.get("file_path") or "").lower()]
        assert prod, "No production functions found"
        for fn in prod:
            assert "is_test" in fn, f"is_test missing from function {fn.get('name')}"
            assert fn["is_test"] is False, (
                f"Production function {fn['name']} has is_test=True"
            )

    def test_test_functions_have_is_test_true(self, rg):
        fns = rg._get_store().get_all_functions()
        test_fns = [
            f
            for f in fns
            if "test" in (f.get("file_path") or "").lower()
            and "fixture" not in (f.get("file_path") or "").lower()
        ]
        assert test_fns, "No test functions found"
        for fn in test_fns:
            assert "is_test" in fn, f"is_test missing from function {fn.get('name')}"
            assert fn["is_test"] is True, (
                f"Test function {fn['name']} at {fn['file_path']} has is_test=False"
            )

    def test_get_all_functions_has_is_test_key(self, rg):
        """is_test must be present on every function record, with no Nones."""
        fns = rg._get_store().get_all_functions()
        assert fns
        for fn in fns:
            assert "is_test" in fn, f"is_test key missing from {fn}"
            assert fn["is_test"] is not None, f"is_test is None for {fn.get('name')}"
