"""Caller that imports score_function under a private alias _score_fn.

This mirrors the real pattern in repograph's own p10_processes.py:
  from repograph.plugins.static_analyzers.pathways.scorer import score_function as _score_fn
  ...
  score = _score_fn(fn, callee_count, caller_count)
"""
from scorer import score_function as _score_fn


def compute_scores(items: list) -> list:
    """Compute scores for all items using the aliased import."""
    return [_score_fn(item, weight=2.0) for item in items]
