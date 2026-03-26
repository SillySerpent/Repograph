"""Split free-text search queries into per-token symbol searches."""
from __future__ import annotations

import re


def tokenize_search_query(query: str, *, min_len: int = 2) -> list[str]:
    """Return identifier-like tokens (order preserved, deduplicated).

    Splits on whitespace and punctuation; keeps tokens that look like
    code symbols (alphanumeric + underscore, min length ``min_len``).
    """
    raw = re.split(r"[^\w]+", query.strip())
    out: list[str] = []
    seen: set[str] = set()
    for t in raw:
        if len(t) < min_len:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out
