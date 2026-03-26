"""Runtime trace capture policy and validation helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TracePolicy:
    """Capture limits and filters for runtime tracing."""

    max_records: int = 0
    max_file_bytes: int = 0
    rotate_files: int = 0
    sample_rate: float = 1.0
    include_pattern: str = ""
    exclude_pattern: str = ""

    @classmethod
    def from_kwargs(cls, **kwargs: Any) -> "TracePolicy":
        return cls(
            max_records=max(0, int(kwargs.get("max_records") or 0)),
            max_file_bytes=max(0, int(kwargs.get("max_file_bytes") or 0)),
            rotate_files=max(0, int(kwargs.get("rotate_files") or 0)),
            sample_rate=_norm_sample_rate(kwargs.get("sample_rate", 1.0)),
            include_pattern=str(kwargs.get("include_pattern") or "").strip(),
            exclude_pattern=str(kwargs.get("exclude_pattern") or "").strip(),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_records": self.max_records,
            "max_file_bytes": self.max_file_bytes,
            "rotate_files": self.rotate_files,
            "sample_rate": self.sample_rate,
            "include_pattern": self.include_pattern,
            "exclude_pattern": self.exclude_pattern,
        }


def _norm_sample_rate(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 1.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v
