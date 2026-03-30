"""CLI ``report --json`` must emit parseable JSON (no Rich corruption)."""
from __future__ import annotations

import json
import os
import shutil

import pytest
from typer.testing import CliRunner

from repograph.cli import app

FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_simple")
)


@pytest.fixture(scope="module")
def indexed_simple_repo(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cli_report_json")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / "repo" / ".repograph")
    shutil.copytree(FIXTURE, repo)
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    run_full_pipeline(
        RunConfig(
            repo_root=repo,
            repograph_dir=rg_dir,
            include_git=False,
            full=True,
        )
    )
    return repo


def test_report_full_json_writes_repograph_file(indexed_simple_repo):
    """``--full --json`` persists the full report under .repograph/report.json."""
    from repograph.config import get_repo_root, repograph_dir

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["report", "--full", "--json", indexed_simple_repo],
    )
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    root = get_repo_root(indexed_simple_repo)
    out = os.path.join(repograph_dir(root), "report.json")
    assert os.path.isfile(out)
    with open(out, encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("meta", {}).get("initialized") is not False
    assert "health" in data and isinstance(data["health"], dict)
    assert "Wrote" in (result.stdout or "") and "report.json" in (result.stdout or "")


def test_report_json_stdout_parses(indexed_simple_repo):
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["report", "--json", indexed_simple_repo],
    )
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    data = json.loads(result.stdout)
    assert data.get("meta", {}).get("initialized") is not False
    assert "coverage_definition" in data
    assert "health" in data and isinstance(data["health"], dict)
    assert data["health"].get("status") == "ok"
    assert "stats" in data and isinstance(data["stats"], dict)
    assert "files" in data["stats"]
    assert "pathways_summary" in data and isinstance(data["pathways_summary"], dict)
    assert data["pathways_summary"].get("shown") == len(data.get("pathways", []))
    assert data["pathways_summary"].get("total", 0) >= data["pathways_summary"].get("shown", 0)
    assert "communities_summary" in data and isinstance(data["communities_summary"], dict)
    assert data["communities_summary"].get("shown") == len(data.get("communities", []))
    assert "config_registry_diagnostics" in data and isinstance(data["config_registry_diagnostics"], dict)
    assert "report_warnings" in data and isinstance(data["report_warnings"], list)
    if data["pathways_summary"].get("total", 0) > data["pathways_summary"].get("shown", 0):
        assert any("Pathways are capped" in w for w in data["report_warnings"])
    if data["communities_summary"].get("total", 0) > data["communities_summary"].get("shown", 0):
        assert any("Communities are capped" in w for w in data["report_warnings"])
    assert "test_coverage" in data and isinstance(data["test_coverage"], list)
    assert "test_coverage_any_call" in data and isinstance(
        data["test_coverage_any_call"], list
    )
    assert "coverage_definition_any_call" in data and isinstance(
        data["coverage_definition_any_call"], str
    )


def test_report_requires_initialized_repo(tmp_path):
    """CLI report exits when the repo has never been indexed (stable failure path)."""
    repo = str(tmp_path / "uninitialized")
    os.makedirs(repo)
    runner = CliRunner()
    result = runner.invoke(app, ["report", "--json", repo])
    assert result.exit_code == 1
    combined = (result.stdout or "") + (result.stderr or "")
    assert "sync" in combined.lower()


def test_full_report_uninitialized_repo_contract(tmp_path):
    """API ``full_report()`` on a repo with no index returns a minimal meta dict."""
    from repograph.api import RepoGraph
    from repograph.config import repograph_dir

    repo = str(tmp_path / "no_db")
    os.makedirs(repo)
    with RepoGraph(repo, repograph_dir=repograph_dir(repo)) as rg:
        data = rg.full_report()
    assert data["meta"].get("initialized") is False
    assert data["meta"].get("repo_path") == repo


def test_intelligence_snapshot_contract(indexed_simple_repo):
    """``intelligence_snapshot`` exposes stable top-level groups for downstream tools."""
    from repograph.api import RepoGraph
    from repograph.config import repograph_dir

    with RepoGraph(indexed_simple_repo, repograph_dir=repograph_dir(indexed_simple_repo)) as rg:
        snap = rg.intelligence_snapshot()
    assert set(snap.keys()) >= {
        "pathways",
        "dead_code",
        "evidence",
        "config_flow",
        "architecture_conformance",
        "report_surfaces",
        "observed_runtime_findings",
    }
    assert isinstance(snap["evidence"], dict)
    assert "runtime_overlay" in snap["evidence"]


def test_json_dumps_preserves_embedded_newlines():
    payload = {"purpose": "line1\nline2\n", "nested": {"x": "a\nb"}}
    s = json.dumps(payload, indent=2, ensure_ascii=False)
    assert json.loads(s) == payload
