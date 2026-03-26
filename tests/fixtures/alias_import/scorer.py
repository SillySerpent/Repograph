"""Scoring utilities — imported under an alias in caller.py."""


def score_function(value: float, weight: float = 1.0) -> float:
    """Return weighted score. Used by caller.py as _score_fn."""
    return value * weight


def unused_helper() -> str:
    """Genuinely dead — never called from anywhere."""
    return "dead"
