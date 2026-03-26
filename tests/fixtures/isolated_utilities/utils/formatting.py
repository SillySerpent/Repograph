"""Formatting utilities — no calls to anything else."""


def format_date(ts: int) -> str:
    return str(ts)


def format_price(p: float) -> str:
    return f"{p:.2f}"


def format_pct(v: float) -> str:
    return f"{v:.1%}"
