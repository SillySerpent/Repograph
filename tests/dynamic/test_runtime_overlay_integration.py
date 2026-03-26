"""Runtime JSONL overlay against a real indexed store."""
from __future__ import annotations

import json

import pytest

from repograph.plugins.dynamic_analyzers.runtime_overlay.plugin import RuntimeOverlayDynamicPlugin
from repograph.runtime.overlay import overlay_traces
from repograph.runtime.trace_format import make_call_record, make_session_record

pytestmark = [pytest.mark.integration, pytest.mark.dynamic]


def _qualified_for_run(simple_store) -> str:
    for fn in simple_store.get_all_functions():
        if fn.get("name") == "run" and str(fn.get("file_path", "")).endswith("main.py"):
            return fn["qualified_name"]
    raise AssertionError("run() in main.py not found in store")


def test_overlay_traces_observes_call(simple_store, tmp_path) -> None:
    qn = _qualified_for_run(simple_store)
    rg = tmp_path / ".repograph"
    runtime = rg / "runtime"
    runtime.mkdir(parents=True)
    rec_session = make_session_record(str(tmp_path), tracer="test", version="1")
    rec_call = {
        **make_call_record(qn, "main.py", 4, caller=""),
        "ts": rec_session["ts"] + 1.0,
    }
    trace_path = runtime / "calls.jsonl"
    trace_path.write_text(
        json.dumps(rec_session) + "\n" + json.dumps(rec_call) + "\n",
        encoding="utf-8",
    )

    report = overlay_traces(runtime, simple_store, repo_root=str(tmp_path))
    assert report["trace_file_count"] >= 1
    assert report["observed_fn_count"] >= 1
    assert qn in (report.get("observed_fns") or [])


def test_runtime_overlay_plugin_returns_findings(simple_store, tmp_path) -> None:
    qn = _qualified_for_run(simple_store)
    rg = tmp_path / ".repograph"
    runtime = rg / "runtime"
    runtime.mkdir(parents=True)
    rec_session = make_session_record(str(tmp_path))
    rec_call = {**make_call_record(qn, "main.py", 4), "ts": rec_session["ts"] + 1.0}
    (runtime / "x.jsonl").write_text(
        json.dumps(rec_session) + "\n" + json.dumps(rec_call) + "\n",
        encoding="utf-8",
    )
    plugin = RuntimeOverlayDynamicPlugin()
    findings = plugin.analyze_traces(runtime, simple_store, repo_root=str(tmp_path))
    assert isinstance(findings, list)
