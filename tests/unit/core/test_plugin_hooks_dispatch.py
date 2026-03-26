"""PluginHookScheduler._dispatch and default hook wiring."""
from __future__ import annotations

import hashlib
import json
import os

import pytest

from repograph.core.models import FileRecord
from repograph.plugins.lifecycle import ensure_all_plugins_registered, get_hook_scheduler

pytestmark = pytest.mark.plugin

_PYTHON_SIMPLE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "python_simple"),
)


def _file_record_for_main_py() -> FileRecord:
    main_py = os.path.join(_PYTHON_SIMPLE, "main.py")
    with open(main_py, "rb") as f:
        content = f.read()
    h = hashlib.sha256(content).hexdigest()
    return FileRecord(
        path="main.py",
        abs_path=main_py,
        name="main.py",
        extension=".py",
        language="python",
        size_bytes=len(content),
        line_count=content.count(b"\n") + 1,
        source_hash=h,
        is_test=False,
        is_config=False,
        mtime=os.path.getmtime(main_py),
    )


def test_run_plugin_dispatches_python_parser() -> None:
    ensure_all_plugins_registered()
    sched = get_hook_scheduler()
    fr = _file_record_for_main_py()
    parsed = sched.run_plugin("parser", "parser.python", file_record=fr)
    assert parsed is not None
    assert getattr(parsed, "file_record", None) is fr


def test_fire_on_traces_collected_runs_dynamic_overlay(simple_store, tmp_path) -> None:
    ensure_all_plugins_registered()
    from repograph.runtime.trace_format import make_call_record, make_session_record

    qn = next(
        f["qualified_name"]
        for f in simple_store.get_all_functions()
        if f.get("name") == "run" and str(f.get("file_path", "")).endswith("main.py")
    )
    rg = tmp_path / ".repograph"
    runtime = rg / "runtime"
    runtime.mkdir(parents=True)

    rec_session = make_session_record(str(tmp_path))
    rec_call = {**make_call_record(qn, "main.py", 4), "ts": rec_session["ts"] + 1.0}
    (runtime / "t.jsonl").write_text(
        json.dumps(rec_session) + "\n" + json.dumps(rec_call) + "\n",
        encoding="utf-8",
    )
    sched = get_hook_scheduler()
    executions = sched.fire(
        "on_traces_collected",
        trace_dir=runtime,
        store=simple_store,
        repo_root=str(tmp_path),
    )
    assert executions
    assert all(e.error is None for e in executions), [e.error for e in executions]


def test_dispatch_rejects_mismatched_hook() -> None:
    ensure_all_plugins_registered()
    from repograph.core.plugin_framework.hooks import PluginHookScheduler

    sched = get_hook_scheduler()
    plugin = sched._registries["parser"].get("parser.python")
    assert plugin is not None
    with pytest.raises(TypeError, match="no matching method"):
        PluginHookScheduler._dispatch(plugin, "on_graph_built", {"store": None})
