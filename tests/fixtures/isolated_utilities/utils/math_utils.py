"""Math utilities — no calls to anything else."""


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def safe_div(a: float, b: float) -> float:
    return a / b if b != 0 else 0.0


def pct_change(old: float, new: float) -> float:
    return (new - old) / old if old != 0 else 0.0
