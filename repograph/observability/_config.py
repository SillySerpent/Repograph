"""ObservabilityConfig — settings for the structured logging system."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ObservabilityConfig:
    """Configuration for RepoGraph's structured observability layer.

    All structured JSONL logs are written to ``log_dir``, organised under a
    per-run sub-directory identified by ``run_id``.  A ``latest`` symlink is
    updated after every run.

    The Rich/console output in ``repograph.utils.logging`` is completely
    independent and is not affected by this configuration.
    """

    log_dir: Path
    """Root directory for structured logs, e.g. ``Path(".repograph/logs")``."""

    run_id: str
    """Short stable identifier for this pipeline run/session (8-char hex UUID)."""

    enabled: bool = True
    """Set to False to disable file-based structured logging (e.g. in tests)."""

    min_level: str = "DEBUG"
    """Minimum log level forwarded to the JSONL sinks (DEBUG/INFO/WARNING/ERROR)."""

    subsystem_files: bool = True
    """Whether to write per-subsystem log files alongside ``all.jsonl``."""

    @property
    def run_dir(self) -> Path:
        """Directory for this specific run's log files."""
        return self.log_dir / self.run_id

    @property
    def all_log(self) -> Path:
        return self.run_dir / "all.jsonl"

    @property
    def errors_log(self) -> Path:
        return self.run_dir / "errors.jsonl"
