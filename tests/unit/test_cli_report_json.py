"""CLI ``report --json`` must emit parseable JSON (no Rich corruption)."""
from __future__ import annotations

import json
import os
import shutil

import pytest
from typer.testing import CliRunner

from repograph.surfaces.cli import app

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
    from repograph.settings import get_repo_root, repograph_dir

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


def test_report_human_output_handles_duplicate_paths(monkeypatch, tmp_path):
    from repograph.surfaces import api as api_module
    from repograph.surfaces.cli.commands import report as report_module

    repo = str(tmp_path / "repo")
    os.makedirs(repo)

    class _DummyStore:
        def close(self) -> None:
            return None

    class _FakeRepoGraph:
        def __init__(self, repo_path, repograph_dir=None, include_git=None):
            self.repo_path = repo_path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def pathway_steps(self, name):
            if name != "full_pipeline_flow":
                return []
            return [
                {
                    "qualified_name": "run_full_pipeline",
                    "function_name": "run_full_pipeline",
                    "file_path": "repograph/pipeline/runner.py",
                },
                {
                    "qualified_name": "p01_walk.run",
                    "function_name": "run",
                    "file_path": "repograph/pipeline/phases/p01_walk.py",
                },
                {
                    "qualified_name": "p04_imports.run",
                    "function_name": "run",
                    "file_path": "repograph/pipeline/phases/p04_imports.py",
                },
                {
                    "qualified_name": "ReportSurfacesExporterPlugin.export",
                    "function_name": "export",
                    "file_path": "repograph/plugins/exporters/report_surfaces/plugin.py",
                },
            ]

        def full_report(
            self,
            max_pathways=10,
            max_dead=20,
            entry_point_limit=20,
            max_config_keys=30,
            max_communities=20,
        ):
            return {
                "meta": {
                    "repo_path": self.repo_path,
                    "repograph_dir": os.path.join(self.repo_path, ".repograph"),
                    "initialized": True,
                },
                "health": {
                    "status": "ok",
                    "sync_mode": "full",
                    "generated_at": "2026-04-01T04:58:49Z",
                    "dynamic_analysis": {
                        "requested": True,
                        "executed": False,
                        "mode": "none",
                        "resolution": "live_target_detected",
                        "skipped_reason": "live_python_target_not_trace_capable",
                        "attach_outcome": "unavailable",
                        "attach_reason": "live_python_target_not_trace_capable",
                        "attach_mode": "attach_live_python",
                        "attach_candidate_count": 1,
                        "attach_target": {
                            "pid": 321,
                            "runtime": "python",
                            "kind": "uvicorn",
                            "command": "uvicorn main:app",
                            "association": "command_path",
                            "port": 8000,
                        },
                        "detected_live_target_count": 1,
                        "detected_live_targets": [
                            {
                                "pid": 321,
                                "runtime": "python",
                                "kind": "uvicorn",
                                "command": "uvicorn main:app",
                                "association": "command_path",
                                "port": 8000,
                            }
                        ],
                        "fallback_reason": "live_python_target_not_trace_capable",
                        "scenario_actions": {
                            "planned_count": 2,
                            "executed_count": 2,
                            "successful_count": 1,
                            "failed_count": 1,
                        },
                    },
                },
                "stats": {
                    "files": 2,
                    "functions": 2,
                    "classes": 0,
                    "variables": 0,
                    "pathways": 0,
                    "communities": 0,
                },
                "runtime_observations": {},
                "purpose": "",
                "modules": [
                    {
                        "display": "repograph/core/",
                        "summary": "Core plugin and registry primitives for the graph build lifecycle.",
                        "prod_file_count": 5,
                        "test_file_count": 1,
                        "file_count": 5,
                        "function_count": 42,
                        "class_count": 8,
                        "test_function_count": 6,
                        "dead_code_count": 1,
                        "duplicate_count": 2,
                        "category": "production",
                        "key_classes": ["PluginRegistry", "PluginHookScheduler"],
                    }
                ],
                "entry_points": [],
                "pathways": [
                    {
                        "name": "full_pipeline_flow",
                        "display_name": "Full Pipeline Flow",
                        "description": (
                            "Builds the graph by running the sync pipeline from file discovery "
                            "through export steps."
                        ),
                        "confidence": 0.85,
                        "step_count": 4,
                        "entry_function": "run_full_pipeline",
                        "source": "auto_detected",
                        "importance_score": 287.9,
                        "context_doc": (
                            "INTERPRETATION\n"
                            "Steps follow breadth-first search over CALLS edges.\n\n"
                            "PARTICIPATING FILES (BFS discovery order)\n"
                            "  1. repograph/pipeline/runner.py\n"
                            "  2. repograph/pipeline/phases/p01_walk.py\n"
                        ),
                    }
                ],
                "pathways_summary": {"total": 1, "shown": 1, "limit": max_pathways},
                "report_warnings": [],
                "dead_code": {
                    "definitely_dead": [],
                    "probably_dead": [],
                    "definitely_dead_tooling": [],
                    "probably_dead_tooling": [],
                },
                "duplicates": [
                    {
                        "name": "new_decision_id",
                        "severity": "high",
                        "canonical_path": "src/core/idgen.py",
                        "superseded_paths": [
                            "src/legacy/idgen.py",
                            "src/archive/idgen_old.py",
                        ],
                    }
                ],
                "invariants": [],
                "config_registry": {},
                "config_registry_diagnostics": {},
                "test_coverage": [],
                "coverage_definition": "",
                "test_coverage_any_call": [],
                "coverage_definition_any_call": "",
                "doc_warnings": [],
                "communities": [],
                "communities_summary": {"total": 0, "shown": 0, "limit": max_communities},
            }

    monkeypatch.setattr(report_module, "_get_root_and_store", lambda path: (repo, _DummyStore()))
    monkeypatch.setattr(api_module, "RepoGraph", _FakeRepoGraph)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["report", repo],
        color=False,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, combined
    assert "Dynamic mode:" in combined
    assert "no runtime execution" in combined
    assert "Selection:" in combined
    assert "live runtime targets were detected" in combined
    assert "Dynamic analysis skipped:" in combined
    assert "Attach:" in combined
    assert "unavailable" in combined
    assert "Attach target:" in combined
    assert "Live target detail:" in combined
    assert "python uvicorn pid=321 port=8000" in combined
    assert "Duplicate Symbols" in combined
    assert "new_decision_id" in combined
    assert "legacy/idgen.py" in combined
    assert "Directory-level structural map" in combined
    assert "Full Pipeline Flow" in combined
    assert "Flow:" in combined
    assert "runner.py" in combined
    assert "Live targets:" in combined
    assert "Scenarios:" in combined
    assert "INTERPRETATION" not in combined
    assert "Traceback" not in combined


def test_report_full_terminal_stays_capped_and_points_to_export(monkeypatch, tmp_path):
    from repograph.surfaces import api as api_module
    from repograph.surfaces.cli.commands import report as report_module

    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    captured: dict[str, object] = {}

    class _DummyStore:
        def close(self) -> None:
            return None

    class _FakeRepoGraph:
        def __init__(self, repo_path, repograph_dir=None, include_git=None):
            self.repo_path = repo_path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def pathway_steps(self, name):
            return []

        def full_report(
            self,
            max_pathways=10,
            max_dead=20,
            entry_point_limit=20,
            max_config_keys=30,
            max_communities=20,
        ):
            captured["max_pathways"] = max_pathways
            captured["max_dead"] = max_dead
            captured["entry_point_limit"] = entry_point_limit
            captured["max_config_keys"] = max_config_keys
            captured["max_communities"] = max_communities
            return {
                "meta": {
                    "repo_path": self.repo_path,
                    "repograph_dir": os.path.join(self.repo_path, ".repograph"),
                    "initialized": True,
                },
                "health": {
                    "status": "ok",
                    "sync_mode": "full",
                    "generated_at": "2026-04-01T04:58:49Z",
                    "call_edges_total": 12,
                },
                "stats": {
                    "files": 9,
                    "functions": 40,
                    "classes": 3,
                    "variables": 5,
                    "pathways": 0,
                    "communities": 9,
                },
                "runtime_observations": {},
                "purpose": "",
                "modules": [],
                "entry_points": [
                    {
                        "qualified_name": f"fn_{i}",
                        "file_path": f"src/file_{i}.py",
                        "entry_score": float(i),
                        "entry_caller_count": i,
                        "entry_callee_count": i + 1,
                    }
                    for i in range(16)
                ],
                "pathways": [],
                "pathways_summary": {"total": 0, "shown": 0, "limit": max_pathways},
                "report_warnings": [],
                "dead_code": {
                    "definitely_dead": [
                        {
                            "qualified_name": f"dead_{i}",
                            "file_path": f"src/dead_{i}.py",
                            "dead_code_reason": "zero_callers",
                        }
                        for i in range(16)
                    ],
                    "probably_dead": [],
                    "definitely_dead_tooling": [],
                    "probably_dead_tooling": [],
                },
                "duplicates": [
                    {
                        "name": f"dup_{i}",
                        "severity": "medium",
                        "canonical_path": f"src/canonical_{i}.py",
                        "superseded_paths": [f"src/stale_{i}.py"],
                    }
                    for i in range(13)
                ],
                "invariants": [
                    {
                        "invariant_type": "constraint",
                        "symbol_name": f"sym_{i}",
                        "invariant_text": f"rule_{i}",
                    }
                    for i in range(21)
                ],
                "config_registry": {
                    f"CFG_{i}": {"usage_count": i + 1, "pathways": [], "files": [f"src/cfg_{i}.py"]}
                    for i in range(25)
                },
                "config_registry_diagnostics": {},
                "test_coverage": [],
                "coverage_definition": "",
                "test_coverage_any_call": [],
                "coverage_definition_any_call": "",
                "doc_warnings": [
                    {
                        "doc_path": f"doc_{i}.md",
                        "line_number": i,
                        "symbol_text": f"docsym_{i}",
                    }
                    for i in range(11)
                ],
                "communities": [
                    {
                        "id": f"community:{i}",
                        "label": f"community:{i}",
                        "member_count": i + 1,
                    }
                    for i in range(9)
                ],
                "communities_summary": {"total": 9, "shown": 9, "limit": max_communities},
            }

    monkeypatch.setattr(report_module, "_get_root_and_store", lambda path: (repo, _DummyStore()))
    monkeypatch.setattr(api_module, "RepoGraph", _FakeRepoGraph)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["report", "--full", repo],
        color=False,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, combined
    assert captured["max_pathways"] == 10
    assert captured["max_dead"] == 20
    assert captured["entry_point_limit"] == 20
    assert captured["max_config_keys"] == 30
    assert captured["max_communities"] == 20
    assert "fn_15" not in combined
    assert "dead_15" not in combined
    assert "dup_12" not in combined
    assert "sym_20" not in combined
    assert "CFG_24" not in combined
    assert "doc_10.md" not in combined
    assert "community:8" not in combined
    assert "Terminal output is capped for readability" in combined
    assert "repograph report --json --full" in combined


def test_report_human_output_labels_reused_dynamic_inputs_honestly(monkeypatch, tmp_path):
    from repograph.surfaces import api as api_module
    from repograph.surfaces.cli.commands import report as report_module

    repo = str(tmp_path / "repo")
    os.makedirs(repo)

    class _DummyStore:
        def close(self) -> None:
            return None

    class _FakeRepoGraph:
        def __init__(self, repo_path, repograph_dir=None, include_git=None):
            self.repo_path = repo_path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def pathway_steps(self, name):
            return []

        def full_report(
            self,
            max_pathways=10,
            max_dead=20,
            entry_point_limit=20,
            max_config_keys=30,
            max_communities=20,
        ):
            return {
                "meta": {
                    "repo_path": self.repo_path,
                    "repograph_dir": os.path.join(self.repo_path, ".repograph"),
                    "initialized": True,
                },
                "health": {
                    "status": "ok",
                    "sync_mode": "incremental",
                    "generated_at": "2026-04-02T06:33:56Z",
                    "call_edges_total": 12,
                    "dynamic_analysis": {
                        "requested": True,
                        "executed": True,
                        "mode": "existing_inputs",
                        "inputs_present": True,
                        "trace_file_count": 1,
                        "overlay_persisted_functions": 23,
                        "coverage_json_present": False,
                        "runtime_overlay_applied": True,
                        "coverage_overlay_applied": False,
                    },
                },
                "stats": {
                    "files": 9,
                    "functions": 40,
                    "classes": 3,
                    "variables": 5,
                    "pathways": 0,
                    "communities": 0,
                },
                "runtime_observations": {
                    "functions_with_valid_runtime_revision": 23,
                },
                "purpose": "",
                "modules": [],
                "entry_points": [],
                "pathways": [],
                "pathways_summary": {"total": 0, "shown": 0, "limit": max_pathways},
                "report_warnings": [],
                "dead_code": {
                    "definitely_dead": [],
                    "probably_dead": [],
                    "definitely_dead_tooling": [],
                    "probably_dead_tooling": [],
                },
                "duplicates": [],
                "invariants": [],
                "config_registry": {},
                "config_registry_diagnostics": {},
                "test_coverage": [],
                "coverage_definition": "",
                "test_coverage_any_call": [],
                "coverage_definition_any_call": "",
                "doc_warnings": [],
                "communities": [],
                "communities_summary": {"total": 0, "shown": 0, "limit": max_communities},
            }

    monkeypatch.setattr(report_module, "_get_root_and_store", lambda path: (repo, _DummyStore()))
    monkeypatch.setattr(api_module, "RepoGraph", _FakeRepoGraph)

    result = CliRunner().invoke(app, ["report", repo], color=False)

    combined = (result.stdout or "") + (result.stderr or "")
    assert result.exit_code == 0, combined
    assert "Dynamic inputs reused:" in combined
    assert "Dynamic traces:" not in combined


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
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import repograph_dir

    repo = str(tmp_path / "no_db")
    os.makedirs(repo)
    with RepoGraph(repo, repograph_dir=repograph_dir(repo)) as rg:
        data = rg.full_report()
    assert data["meta"].get("initialized") is False
    assert data["meta"].get("repo_path") == repo


def test_intelligence_snapshot_contract(indexed_simple_repo):
    """``intelligence_snapshot`` exposes stable top-level groups for downstream tools."""
    from repograph.surfaces.api import RepoGraph
    from repograph.settings import repograph_dir

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
