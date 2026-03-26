"""Trace filtering/sampling helpers for runtime capture."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from repograph.runtime.trace_policy import TracePolicy


@dataclass
class TraceFilterDecision:
    accepted: bool
    reason: str = ""


class TraceFilter:
    """Evaluates whether a trace record should be written."""

    def __init__(self, policy: TracePolicy) -> None:
        self._policy = policy
        self._rng = random.Random(0xC0D3)
        self._include = _safe_re(policy.include_pattern)
        self._exclude = _safe_re(policy.exclude_pattern)

    def allow(self, *, file_path: str, qualified_name: str) -> TraceFilterDecision:
        target = f"{file_path}::{qualified_name}"
        if self._include and not self._include.search(target):
            return TraceFilterDecision(False, "include_filter")
        if self._exclude and self._exclude.search(target):
            return TraceFilterDecision(False, "exclude_filter")
        if self._policy.sample_rate < 1.0 and self._rng.random() > self._policy.sample_rate:
            return TraceFilterDecision(False, "sampled_out")
        return TraceFilterDecision(True, "")


def _safe_re(pattern: str) -> re.Pattern[str] | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        return None
