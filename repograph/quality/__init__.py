"""Post-sync graph quality checks (structural invariants).

Use :func:`run_sync_invariants` after a full or incremental sync to validate
referential integrity and stats consistency (checks Q1–Q6).
"""
from __future__ import annotations

from repograph.quality.integrity import run_sync_invariants
from repograph.quality.types import InvariantResult, Violation

__all__ = [
    "InvariantResult",
    "Violation",
    "run_sync_invariants",
]
