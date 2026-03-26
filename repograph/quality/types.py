"""Structured results for post-sync graph invariant checks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Violation:
    """Single failed invariant."""

    code: str
    message: str
    severity: str = "error"
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class InvariantResult:
    """Aggregate result of ``run_sync_invariants``."""

    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0
