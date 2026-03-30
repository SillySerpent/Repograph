from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


class _ContextRepoGraph:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def full_report(
        self,
        max_pathways: int = 10,
        max_dead: int = 20,
        entry_point_limit: int = 20,
        max_config_keys: int = 30,
        max_communities: int = 20,
    ) -> dict:
        return self._payload

    def modules(self) -> list[dict]:
        return list(self._payload.get("modules", []))

    def pathways(self, min_confidence: float = 0.0, include_tests: bool = False) -> list[dict]:
        return list(self._payload.get("pathways", []))

    def pathway_steps(self, name: str) -> list[dict]:
        return list(self._payload.get("pathway_steps", {}).get(name, []))


def _sample_report_payload(repo_path: str) -> dict:
    return {
        "meta": {
            "repo_path": repo_path,
            "repograph_dir": os.path.join(repo_path, ".repograph"),
            "initialized": True,
        },
        "purpose": "Example RepoGraph fixture.",
        "stats": {
            "files": 3,
            "functions": 7,
            "classes": 1,
            "variables": 5,
            "pathways": 1,
            "communities": 1,
        },
        "health": {
            "status": "ok",
            "sync_mode": "full",
            "generated_at": "2026-04-02T00:00:00Z",
            "call_edges_total": 12,
            "dynamic_analysis": {
                "requested": True,
                "executed": True,
                "trace_file_count": 1,
                "detected_live_target_count": 0,
                "scenario_actions": {},
            },
        },
        "runtime_observations": {},
        "modules": [
            {
                "display": "repograph/surfaces/cli",
                "category": "production",
                "summary": "CLI command entry surfaces.",
                "prod_file_count": 3,
                "test_file_count": 1,
                "file_count": 3,
                "function_count": 7,
                "class_count": 0,
                "test_function_count": 2,
                "dead_code_count": 0,
                "duplicate_count": 0,
                "key_classes": [],
            }
        ],
        "entry_points": [
            {
                "qualified_name": "repograph.surfaces.cli.commands.summary_cmd.summary",
                "file_path": "repograph/surfaces/cli/commands/summary_cmd.py",
                "entry_score": 8.5,
                "entry_caller_count": 0,
                "entry_callee_count": 4,
                "entry_score_base": 2.5,
                "entry_score_multipliers": '[["cli_surface", 1.4]]',
            }
        ],
        "pathways": [
            {
                "name": "summary_flow",
                "display_name": "Summary Flow",
                "description": "Build and print the compact repo summary.",
                "confidence": 0.91,
                "step_count": 3,
                "entry_function": "summary",
                "source": "auto_detected",
                "importance_score": 42.0,
                "context_doc": "",
            }
        ],
        "pathway_steps": {
            "summary_flow": [
                {
                    "qualified_name": "summary",
                    "function_name": "summary",
                    "file_path": "repograph/surfaces/cli/commands/summary_cmd.py",
                },
                {
                    "qualified_name": "build_summary_payload",
                    "function_name": "build_summary_payload",
                    "file_path": "repograph/surfaces/cli/summary_helpers.py",
                },
            ]
        },
        "pathways_summary": {"total": 1, "shown": 1, "limit": 10},
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
        "communities": [
            {
                "id": "community:1",
                "label": "community:1",
                "member_count": 3,
                "members": ["repograph/surfaces/cli/commands/summary_cmd.py"],
            }
        ],
        "communities_summary": {"total": 1, "shown": 1, "limit": 10},
        "report_warnings": [],
    }


def test_summary_direct_entry_surface_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from repograph.surfaces.cli.commands import summary_cmd

    repo_root = "/tmp/example-repo"
    payload = _sample_report_payload(repo_root)

    monkeypatch.setattr(
        summary_cmd,
        "_get_service",
        lambda path: (repo_root, _ContextRepoGraph(payload)),
    )

    summary_cmd.summary(path=repo_root, as_json=True, verbose=False)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["repo"] == os.path.basename(repo_root)
    assert data["dynamic_analysis"]["requested"] is True


def test_modules_direct_entry_surface_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from repograph.surfaces.cli.commands import modules_cmd

    repo_root = "/tmp/example-repo"
    payload = _sample_report_payload(repo_root)

    monkeypatch.setattr(
        modules_cmd,
        "_get_service",
        lambda path: (repo_root, _ContextRepoGraph(payload)),
    )

    modules_cmd.modules(path=repo_root, min_files=1, issues_only=False, as_json=True)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data[0]["display"] == "repograph/surfaces/cli"


def test_pathway_direct_entry_surfaces(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from repograph.surfaces.cli.commands import pathway_cmd

    repo_root = "/tmp/example-repo"
    payload = _sample_report_payload(repo_root)

    class _DummyStore:
        def get_pathway(self, name: str) -> dict | None:
            if name != "summary_flow":
                return None
            return {
                "id": "pathway:summary_flow",
                "display_name": "Summary Flow",
                "context_doc": "Full context for summary flow.",
                "step_count": 3,
                "confidence": 0.91,
            }

        def upsert_pathway(self, doc) -> None:
            return None

        def insert_step_in_pathway(self, function_id, pathway_id, order, role) -> None:
            return None

    monkeypatch.setattr(
        pathway_cmd,
        "_get_service",
        lambda path: (repo_root, _ContextRepoGraph(payload)),
    )
    monkeypatch.setattr(
        pathway_cmd,
        "_get_root_and_store",
        lambda path: (repo_root, _DummyStore()),
    )

    pathway_cmd.pathway_list(path=repo_root, include_tests=False)
    first = capsys.readouterr()
    assert "summary_flow" in first.out

    pathway_cmd.pathway_show(name="summary_flow", path=repo_root)
    second = capsys.readouterr()
    assert "Full context for summary flow." in second.out


def test_report_direct_entry_surface_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    from repograph.surfaces import api as api_module
    from repograph.surfaces.cli.commands import report as report_module

    repo_root = str(tmp_path / "repo")
    os.makedirs(repo_root)
    payload = _sample_report_payload(repo_root)

    class _DummyStore:
        def close(self) -> None:
            return None

    class _FakeRepoGraph(_ContextRepoGraph):
        def __init__(self, repo_path: str, repograph_dir: str | None = None, include_git: bool | None = None) -> None:
            super().__init__(payload)

    monkeypatch.setattr(report_module, "_get_root_and_store", lambda path: (repo_root, _DummyStore()))
    monkeypatch.setattr(api_module, "RepoGraph", _FakeRepoGraph)

    report_module.report(path=repo_root, as_json=True, full=False, max_pathways=10, max_dead=20)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["meta"]["repo_path"] == repo_root
    assert data["health"]["status"] == "ok"


def test_config_describe_direct_entry_surface_json(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    from repograph.surfaces.cli.commands import config as config_module

    config_module.config_describe(key="include_git", path=str(tmp_path), as_json=True)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["key"] == "include_git"
    assert data["type"] == "bool"


def test_export_direct_entry_surface_writes_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from repograph.surfaces.cli.commands import export as export_module

    class _DummyStore:
        def get_stats(self) -> dict:
            return {"files": 1, "functions": 2}

        def get_all_functions(self) -> list[dict]:
            return [{"id": "fn:1", "qualified_name": "app.main"}]

        def get_all_call_edges(self) -> list[dict]:
            return [{"caller": "fn:1", "callee": "fn:2"}]

        def get_all_pathways(self) -> list[dict]:
            return [{"name": "main_flow"}]

        def get_entry_points(self) -> list[dict]:
            return [{"qualified_name": "app.main"}]

        def get_dead_functions(self) -> list[dict]:
            return []

    monkeypatch.setattr(
        export_module,
        "_get_root_and_store",
        lambda path: ("/tmp/example-repo", _DummyStore()),
    )

    output = tmp_path / "export.json"
    export_module.export(output=str(output), path="/tmp/example-repo")

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["stats"]["files"] == 1
    assert data["entry_points"][0]["qualified_name"] == "app.main"


def test_analysis_events_direct_entry_surface_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from repograph.surfaces import api as api_module
    from repograph.surfaces.cli.commands import analysis as analysis_module

    class _DummyStore:
        def close(self) -> None:
            return None

    class _FakeRepoGraph:
        def __init__(self, repo_path: str, repograph_dir: str | None = None) -> None:
            self.repo_path = repo_path

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def _is_initialized(self) -> bool:
            return True

        def event_topology(self) -> list[dict]:
            return [{"event_type": "publish", "role": "producer", "file_path": "app.py", "line": 7}]

    monkeypatch.setattr(
        analysis_module,
        "_get_root_and_store",
        lambda path: ("/tmp/example-repo", _DummyStore()),
    )
    monkeypatch.setattr(api_module, "RepoGraph", _FakeRepoGraph)

    analysis_module.events_cmd(path="/tmp/example-repo", as_json=True)

    data = json.loads(capsys.readouterr().out)
    assert data[0]["event_type"] == "publish"


def test_admin_config_registry_direct_entry_surface_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from repograph.surfaces import api as api_module
    from repograph.surfaces.cli.commands import admin as admin_module

    class _DummyStore:
        def close(self) -> None:
            return None

    class _FakeRepoGraph:
        def __init__(self, repo_path: str, repograph_dir: str | None = None) -> None:
            self.repo_path = repo_path

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def config_registry(self, key: str | None = None) -> dict:
            payload = {
                "APP_MODE": {
                    "usage_count": 2,
                    "pathways": ["bootstrap_flow"],
                    "files": ["app/config.py"],
                }
            }
            if key is None:
                return payload
            return {key: payload[key]} if key in payload else {}

    monkeypatch.setattr(
        admin_module,
        "_get_root_and_store",
        lambda path: ("/tmp/example-repo", _DummyStore()),
    )
    monkeypatch.setattr(api_module, "RepoGraph", _FakeRepoGraph)

    admin_module.config_registry_cmd(
        path="/tmp/example-repo",
        key="APP_MODE",
        top=10,
        as_json=True,
        include_tests=False,
    )

    data = json.loads(capsys.readouterr().out)
    assert data["APP_MODE"]["usage_count"] == 2


def test_trace_collect_direct_entry_surface_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from repograph.runtime import trace_format
    from repograph.settings import repograph_dir as real_repograph_dir
    from repograph.surfaces.cli.commands import trace as trace_module
    import repograph.settings as settings_module

    repo_root = str(tmp_path / "repo")
    rg_dir = real_repograph_dir(repo_root)
    runtime_dir = Path(rg_dir) / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    trace_file = runtime_dir / "trace.jsonl"
    trace_file.write_text('{"event":"call"}\n{"event":"call"}\n', encoding="utf-8")

    monkeypatch.setattr(settings_module, "get_repo_root", lambda path=None: repo_root)
    monkeypatch.setattr(settings_module, "repograph_dir", lambda root: rg_dir)
    monkeypatch.setattr(trace_format, "collect_trace_files", lambda _rg_dir: [trace_file])

    trace_module.trace_collect(path=repo_root, as_json=True)

    data = json.loads(capsys.readouterr().out)
    assert data["trace_file_count"] == 1
    assert data["total_records"] == 2


def test_mcp_direct_entry_surface_starts_server(monkeypatch: pytest.MonkeyPatch) -> None:
    import repograph.surfaces.mcp.server as mcp_server_module

    from repograph.surfaces.cli.commands import mcp_cmd

    calls: list[tuple[str, str | None]] = []

    class _FakeServer:
        def run(self, transport: str | None = None) -> None:
            calls.append(("run", transport))

    class _FakeRepoGraph:
        def __init__(self) -> None:
            self._service = object()

    monkeypatch.setattr(
        mcp_cmd,
        "_get_service",
        lambda path: ("/tmp/example-repo", _FakeRepoGraph()),
    )
    monkeypatch.setattr(mcp_server_module, "create_server", lambda service, port=None: _FakeServer())

    mcp_cmd.mcp(path="/tmp/example-repo", port=8123)

    assert calls == [("run", "streamable-http")]


def test_query_direct_entry_surface(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from repograph.search import hybrid as hybrid_module
    from repograph.surfaces.cli.commands import query as query_module

    class _DummyStore:
        pass

    class _FakeHybridSearch:
        def __init__(self, store) -> None:
            self.store = store

        def search(self, text: str, limit: int = 10) -> list[dict]:
            return [
                {
                    "score": 0.91,
                    "type": "function",
                    "name": "app.search",
                    "file_path": "app/search.py",
                }
            ]

    monkeypatch.setattr(
        query_module,
        "_get_root_and_store",
        lambda path: ("/tmp/example-repo", _DummyStore()),
    )
    monkeypatch.setattr(hybrid_module, "HybridSearch", _FakeHybridSearch)

    query_module.query(text="search", limit=5, path="/tmp/example-repo")

    assert "app.search" in capsys.readouterr().out


def test_impact_direct_entry_surface(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from repograph.surfaces.cli.commands import query as query_module

    class _DummyStore:
        def get_function_by_id(self, function_id: str) -> dict:
            if function_id == "fn:target":
                return {
                    "id": function_id,
                    "qualified_name": "app.target",
                    "file_path": "app/core.py",
                }
            return {
                "id": function_id,
                "qualified_name": "app.caller",
                "file_path": "app/caller.py",
            }

        def get_callers(self, function_id: str) -> list[dict]:
            if function_id == "fn:target":
                return [
                    {
                        "id": "fn:caller",
                        "qualified_name": "app.caller",
                        "file_path": "app/caller.py",
                    }
                ]
            return []

    monkeypatch.setattr(
        query_module,
        "_get_root_and_store",
        lambda path: ("/tmp/example-repo", _DummyStore()),
    )
    monkeypatch.setattr(
        query_module,
        "resolve_identifier",
        lambda store, symbol, limit=5: {
            "kind": "function",
            "strategy": "exact_qualified_name",
            "match": {"id": "fn:target", "qualified_name": "app.target"},
        },
    )

    query_module.impact(symbol="app.target", depth=2, path="/tmp/example-repo")

    output = capsys.readouterr().out
    assert "app.caller" in output


def test_console_entry_main_dispatches_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    import repograph.entry as entry_module
    import repograph.surfaces.cli as cli_package

    original_argv = sys.argv[:]

    class _FakeApp:
        def __init__(self) -> None:
            self.called = False

        def __call__(self) -> int:
            self.called = True
            return 0

    fake_app = _FakeApp()
    monkeypatch.setattr(cli_package, "app", fake_app)
    monkeypatch.setattr(sys, "argv", ["repograph", "cli", "status"])

    with pytest.raises(SystemExit) as exc:
        entry_module.main()

    assert exc.value.code == 0
    assert fake_app.called is True
    assert sys.argv == ["repograph", "status"]
    sys.argv = original_argv
