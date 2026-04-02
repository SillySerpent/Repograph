"""Tests for the 'repograph summary' CLI command."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import pytest

FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
)


@pytest.fixture(scope="module")
def synced_repo(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("summary")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / "repo" / ".repograph")
    shutil.copytree(FLASK_FIXTURE, repo)
    # Add a README so purpose extraction works
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# Flask Auth App\n\nA minimal Flask auth service with JWT tokens.\n")
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, full=True,
    ))
    return repo


def _run_summary(repo: str, extra_args=None):
    cmd = [sys.executable, "-m", "repograph", "summary", repo]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


class TestSummaryCommandBasic:
    def test_summary_exits_zero(self, synced_repo):
        result = _run_summary(synced_repo)
        assert result.returncode == 0, (
            f"summary exited {result.returncode}\nstderr: {result.stderr[:500]}"
        )

    def test_summary_contains_repo_name(self, synced_repo):
        result = _run_summary(synced_repo)
        assert "repo" in result.stdout.lower() or "flask" in result.stdout.lower()

    def test_summary_shows_entry_points_section(self, synced_repo):
        result = _run_summary(synced_repo)
        assert "Entry Point" in result.stdout

    def test_summary_shows_pathways_section(self, synced_repo):
        result = _run_summary(synced_repo)
        assert "Pathway" in result.stdout

    def test_summary_shows_issues_section(self, synced_repo):
        result = _run_summary(synced_repo)
        assert "Risk" in result.stdout or "dead code" in result.stdout.lower()

    def test_summary_shows_structural_hotspots_section(self, synced_repo):
        result = _run_summary(synced_repo)
        assert "Structural Hotspots" in result.stdout

    def test_summary_shows_trust_section(self, synced_repo):
        result = _run_summary(synced_repo)
        assert "Trust" in result.stdout

    def test_summary_shows_purpose_from_readme(self, synced_repo):
        result = _run_summary(synced_repo)
        assert "Flask" in result.stdout or "auth" in result.stdout.lower()


class TestSummaryJSONOutput:
    def test_json_flag_produces_valid_json(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        assert result.returncode == 0
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"--json output is not valid JSON: {e}\nOutput: {result.stdout[:500]}")

    def test_json_has_required_keys(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        data = json.loads(result.stdout)
        for key in (
            "repo",
            "stats",
            "health",
            "dynamic_analysis",
            "trust",
            "top_entry_points",
            "top_pathways",
            "major_risks",
            "structural_hotspots",
            "dead_code_count",
            "high_severity_duplicates",
        ):
            assert key in data, f"Missing key '{key}' in JSON output"

    def test_json_top_entry_points_structure(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        data = json.loads(result.stdout)
        eps = data["top_entry_points"]
        assert isinstance(eps, list)
        for ep in eps:
            assert "name" in ep
            assert "file" in ep
            assert "score" in ep
            assert "callers" in ep
            assert "callees" in ep

    def test_json_top_pathways_structure(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        data = json.loads(result.stdout)
        ps = data["top_pathways"]
        assert isinstance(ps, list)
        for p in ps:
            assert "name" in p
            assert "entry" in p
            assert "steps" in p
            assert "importance" in p
            assert "confidence" in p
            assert "source" in p

    def test_json_trust_structure(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        data = json.loads(result.stdout)
        trust = data["trust"]
        assert "status" in trust
        assert "sync_status" in trust
        assert "sync_mode" in trust
        assert "warnings" in trust
        assert "analysis_readiness" in trust

    def test_json_major_risks_structure(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        data = json.loads(result.stdout)
        risks = data["major_risks"]
        assert isinstance(risks, list)
        for risk in risks:
            assert "kind" in risk
            assert "severity" in risk
            assert "count" in risk
            assert "summary" in risk

    def test_json_structural_hotspots_structure(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        data = json.loads(result.stdout)
        hotspots = data["structural_hotspots"]
        assert isinstance(hotspots, list)
        for hotspot in hotspots:
            assert "module" in hotspot
            assert "summary" in hotspot
            assert "function_count" in hotspot
            assert "class_count" in hotspot

    def test_json_pathways_sorted_by_importance(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        data = json.loads(result.stdout)
        scores = [p["importance"] for p in data["top_pathways"]]
        assert scores == sorted(scores, reverse=True), \
            f"JSON top_pathways not sorted by importance: {scores}"

    def test_json_dead_code_count_is_int(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        data = json.loads(result.stdout)
        assert isinstance(data["dead_code_count"], int)

    def test_json_purpose_from_readme(self, synced_repo):
        result = _run_summary(synced_repo, ["--json"])
        data = json.loads(result.stdout)
        purpose = data.get("purpose", "")
        assert "Flask" in purpose or "auth" in purpose.lower(), \
            f"Expected README content in purpose, got: '{purpose}'"


class TestSummaryEdgeCases:
    def test_summary_fails_gracefully_when_not_initialized(self, tmp_path):
        """summary on an unindexed dir must exit nonzero with clear message."""
        repo = str(tmp_path / "empty_repo")
        os.makedirs(repo)
        result = subprocess.run(
            [sys.executable, "-m", "repograph", "summary", repo],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "init" in combined.lower() or "sync" in combined.lower(), (
            f"Expected helpful 'init/sync' message, got: {combined[:300]}"
        )
