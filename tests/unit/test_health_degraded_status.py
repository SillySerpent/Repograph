from __future__ import annotations

from repograph.pipeline.health import build_health_report


class _Store:
    def query(self, _cypher: str):
        return [[0]]


def test_health_degraded_when_hook_failures_present(tmp_path) -> None:
    report = build_health_report(
        _Store(),
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
