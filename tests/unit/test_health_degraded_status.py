from __future__ import annotations

from repograph.pipeline.health import build_health_report


class _Store:
    def query(self, _cypher: str):
        return [[0]]


def test_health_degraded_when_hook_failures_present(tmp_path) -> None:
    report = build_health_report(
        _Store(),  # type: ignore[arg-type]
        {"files": 1},
        repo_root=str(tmp_path),
        repograph_dir=str(tmp_path / ".repograph"),
        sync_mode="incremental",
        hook_summary={
            "failed_count": 2,
            "warnings_count": 2,
            "failed": [{"hook": "on_export", "plugin_id": "x", "error": "boom"}],
        },
    )
    assert report["status"] == "degraded"
    assert report["partial_completion"] is True
    assert report["hook_summary"]["failed_count"] == 2


def test_health_readiness_does_not_claim_coverage_overlay_without_coverage_input(tmp_path) -> None:
    rg_dir = tmp_path / ".repograph"
    rg_dir.mkdir()
    (rg_dir / "meta").mkdir()

    report = build_health_report(
        _Store(),  # type: ignore[arg-type]
        {"files": 1},
        repo_root=str(tmp_path),
        repograph_dir=str(rg_dir),
        sync_mode="incremental",
        hook_summary={
            "dynamic_stage": {
                "plugins": {
                    "dynamic_analyzer.coverage_overlay": {"executed": True},
                }
            }
        },
    )

    readiness = report["analysis_readiness"]
    assert readiness["coverage_json_present"] is False
    assert readiness["coverage_overlay_applied"] is False
