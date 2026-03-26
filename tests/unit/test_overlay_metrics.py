from __future__ import annotations

import json

from repograph.runtime.overlay import overlay_traces
from repograph.runtime.trace_format import make_call_record, make_session_record


class _Store:
    def get_all_call_edges(self):
        return []

    def get_all_functions(self):
        return [
            {
                "id": "f1",
                "name": "run",
                "qualified_name": "main.run",
                "file_path": "main.py",
                "is_dead": False,
            }
        ]


def test_overlay_tracks_resolved_and_unresolved_counts(tmp_path) -> None:
    rg = tmp_path / ".repograph"
    runtime = rg / "runtime"
    runtime.mkdir(parents=True)

    s = make_session_record(str(tmp_path))
    resolved = {**make_call_record("main.run", "main.py", 1)}
    unresolved = {**make_call_record("unknown.mod.fn", "x.py", 2)}
    (runtime / "t.jsonl").write_text(
        json.dumps(s) + "\n" + json.dumps(resolved) + "\n" + json.dumps(unresolved) + "\n",
        encoding="utf-8",
    )

    report = overlay_traces(runtime, _Store(), repo_root=str(tmp_path))
    assert report["trace_call_records"] == 2
    assert report["resolved_trace_calls"] == 1
    assert report["unresolved_trace_calls"] == 1
    assert "unknown.mod.fn" in (report.get("unresolved_examples") or [])
