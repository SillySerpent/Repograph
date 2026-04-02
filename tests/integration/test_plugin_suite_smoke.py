"""End-to-end smoke: every built-in plugin runs without raising on a synced fixture graph.

Catches import errors, manifest/dispatch mismatches, and analyze/export crashes when
code changes. Uses **one** module-scoped full sync for demand/export/static/evidence
tests to keep the overall suite fast.
"""
from __future__ import annotations

import hashlib
import os
import shutil

import pytest

from repograph.core.models import FileRecord
from repograph.plugins.discovery import (
    DEMAND_ANALYZER_ORDER,
    EVIDENCE_PRODUCER_ORDER,
    EXPORTER_ORDER,
    FRAMEWORK_ADAPTER_ORDER,
    STATIC_ANALYZER_ORDER,
)
from repograph.plugins.lifecycle import ensure_all_plugins_registered, get_hook_scheduler
from repograph.plugins.features import run_evidence_producer, run_static_analyzer

pytestmark = [pytest.mark.integration, pytest.mark.plugin]

_ROOT = os.path.dirname(os.path.dirname(__file__))
_PYTHON_SIMPLE = os.path.abspath(os.path.join(_ROOT, "fixtures", "python_simple"))
_PYTHON_FLASK = os.path.abspath(os.path.join(_ROOT, "fixtures", "python_flask"))
_JS_EXPRESS = os.path.abspath(os.path.join(_ROOT, "fixtures", "js_express"))


@pytest.fixture(scope="module")
def plugin_smoke_python_simple(tmp_path_factory):
    """Single indexed copy of ``python_simple`` shared by plugin smoke tests."""
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    tmp = tmp_path_factory.mktemp("plugin_smoke_py")
    repo = str(tmp / "repo")
    shutil.copytree(_PYTHON_SIMPLE, repo)
    rg_dir = str(tmp / ".repograph")
    run_full_pipeline(
        RunConfig(
            repo_root=repo,
            repograph_dir=rg_dir,
            include_git=False,
            include_embeddings=False,
            full=True,
        )
    )
    db = os.path.join(rg_dir, "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    return repo, rg_dir, store


def _file_record_from_path(abs_path: str, language: str) -> FileRecord:
    with open(abs_path, "rb") as f:
        content = f.read()
    h = hashlib.sha256(content).hexdigest()
    rel = os.path.basename(abs_path)
    return FileRecord(
        path=rel,
        abs_path=abs_path,
        name=rel,
        extension=os.path.splitext(rel)[1],
        language=language,
        size_bytes=len(content),
        line_count=content.count(b"\n") + 1,
        source_hash=h,
        is_test=False,
        is_config=False,
        mtime=os.path.getmtime(abs_path),
    )


def test_all_demand_analyzers_run(plugin_smoke_python_simple) -> None:
    """``demand_analyzer.<name>`` — each must return a list (findings)."""
    repo, rg_dir, _store = plugin_smoke_python_simple
    from repograph.surfaces.api import RepoGraph

    with RepoGraph(repo, repograph_dir=rg_dir) as rg:
        for name in DEMAND_ANALYZER_ORDER:
            pid = f"demand_analyzer.{name}"
            out = rg.run_analyzer_plugin(pid)
            assert isinstance(out, list), f"{pid} returned {type(out).__name__}"


def test_all_exporters_run(plugin_smoke_python_simple) -> None:
    """``exporter.<name>`` — must complete; typically dict or list fragments."""
    repo, rg_dir, _store = plugin_smoke_python_simple
    from repograph.surfaces.api import RepoGraph

    with RepoGraph(repo, repograph_dir=rg_dir) as rg:
        for name in EXPORTER_ORDER:
            pid = f"exporter.{name}"
            out = rg.run_exporter_plugin(pid)
            assert out is not None, pid


def test_all_static_analyzers_run(plugin_smoke_python_simple) -> None:
    """Re-run static analyzers with a live store (idempotent or safe no-op)."""
    repo, _rg_dir, store = plugin_smoke_python_simple
    for name in STATIC_ANALYZER_ORDER:
        pid = f"static_analyzer.{name}"
        out = run_static_analyzer(pid, store=store, repo_path=repo)
        assert isinstance(out, list), f"{pid} returned {type(out).__name__}"


def test_all_evidence_producers_run(plugin_smoke_python_simple) -> None:
    """``evidence.<name>`` producers."""
    repo, rg_dir, _store = plugin_smoke_python_simple
    from repograph.surfaces.api import RepoGraph

    with RepoGraph(repo, repograph_dir=rg_dir) as rg:
        for name in EVIDENCE_PRODUCER_ORDER:
            pid = f"evidence.{name}"
            out = run_evidence_producer(pid, service=rg)
            assert isinstance(out, dict), f"{pid} returned {type(out).__name__}"


def test_all_parsers_parse_sample_files(tmp_path) -> None:
    """Each language parser accepts a real file from fixtures."""
    ensure_all_plugins_registered()
    sched = get_hook_scheduler()

    ts_snippet = os.path.join(tmp_path, "smoke.ts")
    with open(ts_snippet, "w", encoding="utf-8") as f:
        f.write("export const x: number = 1;\n")

    samples: list[tuple[str, str, str]] = [
        ("python", os.path.join(_PYTHON_SIMPLE, "main.py"), "parser.python"),
        ("javascript", os.path.join(_JS_EXPRESS, "routes/auth.js"), "parser.javascript"),
        ("typescript", ts_snippet, "parser.typescript"),
    ]
    for _lang, path, pid in samples:
        fr = _file_record_from_path(path, "typescript" if path.endswith(".ts") else _lang)
        parsed = sched.run_plugin("parser", pid, file_record=fr)
        assert parsed is not None, pid


def test_framework_adapters_inspect_parsed_flask_route() -> None:
    """Each framework adapter runs ``inspect`` on a parsed Flask route file."""
    ensure_all_plugins_registered()
    sched = get_hook_scheduler()
    path = os.path.join(_PYTHON_FLASK, "routes", "auth.py")
    fr = _file_record_from_path(path, "python")
    parsed = sched.run_plugin("parser", "parser.python", file_record=fr)
    for name in FRAMEWORK_ADAPTER_ORDER:
        pid = f"framework.{name}"
        out = sched.run_plugin("framework_adapter", pid, file_record=fr, parsed_file=parsed)
        assert isinstance(out, dict), pid


def test_tracer_coverage_install_dry_repo(tmp_path) -> None:
    """Tracer install writes config under a throwaway repo root."""
    ensure_all_plugins_registered()
    sched = get_hook_scheduler()
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    trace_dir = tmp_path / ".repograph" / "runtime"
    out = sched.run_plugin(
        "tracer",
        "tracer.coverage",
        repo_root=repo,
        trace_dir=trace_dir,
    )
    assert isinstance(out, dict)
    assert out.get("status") in ("installed", "already_installed")
