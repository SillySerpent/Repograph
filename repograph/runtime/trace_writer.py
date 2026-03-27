"""Bounded JSONL writer with optional file rotation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repograph.runtime.trace_format import TRACE_FILE_SUFFIX
from repograph.runtime.trace_policy import TracePolicy
from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="runtime")


@dataclass
class TraceWriteStats:
    written_records: int = 0
    dropped_records: int = 0
    dropped_by_reason: dict[str, int] = field(default_factory=dict)
    bytes_written: int = 0
    rotated_files: int = 0

    def drop(self, reason: str) -> None:
        self.dropped_records += 1
        self.dropped_by_reason[reason] = self.dropped_by_reason.get(reason, 0) + 1


class TraceWriter:
    """Writes JSONL trace records with policy-aware limits."""

    def __init__(self, out_dir: Path, session_name: str, policy: TracePolicy) -> None:
        self._out_dir = out_dir
        self._session_name = session_name
        self._policy = policy
        self._stats = TraceWriteStats()
        self._file = None
        self._path: Path | None = None
        self._idx = 0

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def stats(self) -> TraceWriteStats:
        return self._stats

    def __enter__(self) -> "TraceWriter":
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        if self._file is not None:
            _logger.warning(
                "TraceWriter garbage collected with open file handle — call close() explicitly",
                path=str(self._path),
            )
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    def open(self) -> None:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._next_path()
        try:
            self._file = open(self._path, "w", encoding="utf-8", buffering=1)
        except Exception:
            self._file = None
            raise
        _logger.debug("trace file opened", path=str(self._path))

    def close(self) -> None:
        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None
            _logger.debug("trace file closed", path=str(self._path))

    def write(self, record: dict[str, Any]) -> bool:
        if self._file is None:
            return False
        if self._policy.max_records and self._stats.written_records >= self._policy.max_records:
            self._stats.drop("max_records")
            return False
        raw = json.dumps(record, separators=(",", ":")) + "\n"
        if self._policy.max_file_bytes and self._stats.bytes_written + len(raw.encode("utf-8")) > self._policy.max_file_bytes:
            if not self._rotate():
                self._stats.drop("max_file_bytes")
                return False
        self._file.write(raw)
        self._stats.written_records += 1
        self._stats.bytes_written += len(raw.encode("utf-8"))
        return True

    def _next_path(self) -> Path:
        import time
        ts = int(time.time())
        suffix = "" if self._idx == 0 else f"_{self._idx}"
        return self._out_dir / f"{self._session_name}_{ts}{suffix}{TRACE_FILE_SUFFIX}"

    def _rotate(self) -> bool:
        if self._policy.rotate_files <= 0 or self._idx >= self._policy.rotate_files:
            return False
        self.close()
        self._idx += 1
        self._path = self._next_path()
        try:
            self._file = open(self._path, "w", encoding="utf-8", buffering=1)
        except Exception:
            self._file = None
            raise
        self._stats.rotated_files += 1
        self._stats.bytes_written = 0
        _logger.debug("trace file rotated", path=str(self._path), rotation_index=self._idx)
        return True
