from __future__ import annotations

from repograph.services.service_full_report import _build_report_warnings


def test_build_report_warnings_includes_caps_and_trace_mode() -> None:
    ws = _build_report_warnings(
        health={"sync_mode": "incremental_traces_only", "status": "degraded"},
        pathways_total=52,
        pathways_shown=10,
        communities_total=69,
        communities_shown=20,
        cfg_top={},
        cfg_diag={"status": "empty_valid"},
    )
    assert any("trace-only incremental refresh" in w for w in ws)
    assert any("degraded health" in w for w in ws)
    assert any("Pathways are capped" in w for w in ws)
    assert any("Communities are capped" in w for w in ws)
    assert any("Config registry empty" in w for w in ws)


def test_build_report_warnings_empty_when_no_issues() -> None:
    ws = _build_report_warnings(
        health={"sync_mode": "full", "status": "ok"},
        pathways_total=10,
        pathways_shown=10,
        communities_total=20,
        communities_shown=20,
        cfg_top={"a": {"usage_count": 1}},
        cfg_diag={},
    )
    assert ws == []


def test_build_report_warnings_includes_dynamic_skip() -> None:
    ws = _build_report_warnings(
        health={
            "sync_mode": "full",
            "status": "ok",
            "dynamic_analysis": {
                "requested": True,
                "executed": False,
                "skipped_reason": "no_pytest_signal",
            },
        },
        pathways_total=1,
        pathways_shown=1,
        communities_total=1,
        communities_shown=1,
        cfg_top={"a": {"usage_count": 1}},
        cfg_diag={},
    )
    assert any("Dynamic analysis was requested" in w for w in ws)


def test_build_report_warnings_includes_existing_input_reuse_note() -> None:
    ws = _build_report_warnings(
        health={
            "sync_mode": "incremental",
            "status": "ok",
            "dynamic_analysis": {
                "mode": "existing_inputs",
                "inputs_present": True,
                "executed": True,
            },
        },
        pathways_total=1,
        pathways_shown=1,
        communities_total=1,
        communities_shown=1,
        cfg_top={"a": {"usage_count": 1}},
        cfg_diag={},
    )
    assert any("reused from existing trace or coverage inputs" in w for w in ws)
