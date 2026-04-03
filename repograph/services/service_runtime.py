"""Runtime-related RepoGraph service methods."""
from __future__ import annotations

from repograph.services.service_base import RepoGraphServiceProtocol, _observed_service_call


class ServiceRuntimeMixin:
    """Runtime overlay and observed-runtime report surfaces."""

    def runtime_overlay_summary(self: RepoGraphServiceProtocol) -> dict:
        """Return observed/runtime overlay metadata without replacing static evidence."""
        return self.run_exporter_plugin("exporter.runtime_overlay_summary")

    def observed_runtime_findings(self: RepoGraphServiceProtocol) -> dict:
        """Return consumed or normalized observed runtime findings."""
        return self.run_exporter_plugin("exporter.observed_runtime_findings")

    def report_surfaces(self: RepoGraphServiceProtocol) -> dict:
        """Return grouped report/meta surfaces for UI consumers."""
        return self.run_exporter_plugin("exporter.report_surfaces")


class ServiceLogsMixin:
    """Observability log access surfaces."""

    @_observed_service_call("service_list_log_sessions")
    def list_log_sessions(self: RepoGraphServiceProtocol) -> list[dict]:
        """List available log sessions with run_id, timestamp, and record counts."""
        import time as _time

        log_dir = self._log_dir()
        if not log_dir.exists():
            return []

        sessions = []
        for run_dir in sorted(
            log_dir.iterdir(),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ):
            if not run_dir.is_dir():
                continue
            all_json = run_dir / "all.jsonl"
            errors_json = run_dir / "errors.jsonl"
            all_count = sum(1 for line in all_json.open() if line.strip()) if all_json.exists() else 0
            error_count = (
                sum(1 for line in errors_json.open() if line.strip())
                if errors_json.exists()
                else 0
            )
            sessions.append(
                {
                    "run_id": run_dir.name,
                    "timestamp_iso": _time.strftime(
                        "%Y-%m-%dT%H:%M:%S",
                        _time.localtime(run_dir.stat().st_mtime),
                    ),
                    "record_count": all_count,
                    "error_count": error_count,
                }
            )
        return sessions

    @_observed_service_call(
        "service_get_log_session",
        metadata_fn=lambda self, run_id=None, subsystem=None, limit=500: {
            "has_run_id": run_id is not None,
            "subsystem": subsystem or "",
            "limit": int(limit),
        },
    )
    def get_log_session(
        self: RepoGraphServiceProtocol,
        run_id: str | None = None,
        subsystem: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Return parsed log records for a session, optionally filtered by subsystem."""
        import json

        run_dir = self._resolve_run_dir(self._log_dir(), run_id)
        if run_dir is None:
            return []

        filename = f"{subsystem}.jsonl" if subsystem else "all.jsonl"
        log_file = run_dir / filename
        if not log_file.exists():
            return []

        records = []
        for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records[-limit:]

    @_observed_service_call(
        "service_get_recent_errors",
        metadata_fn=lambda self, run_id=None, limit=50: {
            "has_run_id": run_id is not None,
            "limit": int(limit),
        },
    )
    def get_recent_errors(
        self: RepoGraphServiceProtocol,
        run_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return the most recent ERROR and CRITICAL log records."""
        import json

        run_dir = self._resolve_run_dir(self._log_dir(), run_id)
        if run_dir is None:
            return []

        errors_file = run_dir / "errors.jsonl"
        if not errors_file.exists():
            return []

        records = []
        for line in errors_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records[-limit:]
