from __future__ import annotations

from repograph.plugins.dynamic_analyzers.runtime_quality.plugin import (
    RuntimeQualityDynamicPlugin,
)


def test_runtime_quality_plugin_emits_finding_for_low_resolution(monkeypatch, tmp_path) -> None:
    plugin = RuntimeQualityDynamicPlugin()

    def _fake_overlay(_trace_dir, _store, repo_root=""):
        return {
            "trace_call_records": 1000,
            "resolved_trace_calls": 700,
            "unresolved_trace_calls": 300,
            "unresolved_examples": ["x.a", "x.b"],
        }

    from repograph.plugins.dynamic_analyzers.runtime_quality import plugin as mod

    monkeypatch.setattr(mod, "overlay_traces", _fake_overlay)
    out = plugin.analyze_traces(tmp_path, object(), repo_root=".")
    assert out
    assert out[0]["kind"] == "runtime_resolution_low"
    assert out[0]["severity"] == "medium"


def test_runtime_quality_plugin_no_finding_when_resolution_ok(monkeypatch, tmp_path) -> None:
    plugin = RuntimeQualityDynamicPlugin()

    def _fake_overlay(_trace_dir, _store, repo_root=""):
        return {
            "trace_call_records": 1000,
            "resolved_trace_calls": 950,
            "unresolved_trace_calls": 50,
            "unresolved_examples": [],
        }

    from repograph.plugins.dynamic_analyzers.runtime_quality import plugin as mod

    monkeypatch.setattr(mod, "overlay_traces", _fake_overlay)
    out = plugin.analyze_traces(tmp_path, object(), repo_root=".")
    assert out == []
