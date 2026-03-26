"""Integration tests for CLI pathway commands — argument parsing."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import pytest

FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
)


@pytest.fixture(scope="module")
def synced_flask_repo(tmp_path_factory):
    """Sync flask fixture repo once, return (repo_path, rg_dir)."""
    tmp = tmp_path_factory.mktemp("cli_pathway")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / "repo" / ".repograph")
    shutil.copytree(FLASK_FIXTURE, repo)
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, full=True,
    ))
    return repo, rg_dir


def _first_pathway_name(rg_dir: str) -> str:
    from repograph.graph_store.store import GraphStore
    store = GraphStore(os.path.join(rg_dir, "graph.db"))
    store.initialize_schema()
    ps = store.get_all_pathways()
    store.close()
    assert ps, "No pathways found in fixture"
    return ps[0]["name"]


class TestPathwayShowCLI:
    def test_show_with_positional_path_succeeds(self, synced_flask_repo):
        """repograph pathway show <name> <path> must not raise 'unexpected extra argument'."""
        repo, rg_dir = synced_flask_repo
        name = _first_pathway_name(rg_dir)
        result = subprocess.run(
            [sys.executable, "-m", "repograph", "pathway", "show", name, repo],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"pathway show exited {result.returncode}.\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )

    def test_show_outputs_pathway_header(self, synced_flask_repo):
        """Output must contain the PATHWAY header line."""
        repo, rg_dir = synced_flask_repo
        name = _first_pathway_name(rg_dir)
        result = subprocess.run(
            [sys.executable, "-m", "repograph", "pathway", "show", name, repo],
            capture_output=True, text=True,
        )
        assert "PATHWAY:" in result.stdout, (
            f"Expected 'PATHWAY:' in output, got:\n{result.stdout[:500]}"
        )

    def test_show_unknown_pathway_exits_nonzero(self, synced_flask_repo):
        """Unknown pathway name must exit 1 with a clear message."""
        repo, _ = synced_flask_repo
        result = subprocess.run(
            [sys.executable, "-m", "repograph", "pathway", "show",
             "this_pathway_does_not_exist_xyz", repo],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()

    def test_list_and_show_path_args_consistent(self, synced_flask_repo):
        """Both 'pathway list <path>' and 'pathway show <name> <path>' accept
        path as a positional arg (not --path flag)."""
        repo, rg_dir = synced_flask_repo
        name = _first_pathway_name(rg_dir)

        list_result = subprocess.run(
            [sys.executable, "-m", "repograph", "pathway", "list", repo],
            capture_output=True, text=True,
        )
        show_result = subprocess.run(
            [sys.executable, "-m", "repograph", "pathway", "show", name, repo],
            capture_output=True, text=True,
        )
        assert list_result.returncode == 0, f"pathway list failed: {list_result.stderr}"
        assert show_result.returncode == 0, f"pathway show failed: {show_result.stderr}"
