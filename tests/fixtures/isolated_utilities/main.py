"""Main entry point — calls into utilities."""
from utils.formatting import format_date, format_price
from utils.math_utils import clamp, safe_div


def run(ts: int, price: float, raw: float) -> str:
    clamped = clamp(raw, 0.0, 1.0)
    divided = safe_div(clamped, price)
    return f"{format_date(ts)} {format_price(divided)}"
