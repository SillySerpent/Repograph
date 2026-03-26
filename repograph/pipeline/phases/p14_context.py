"""Skip doc-symbol checks when a token is probably schema/prose, not code."""
from __future__ import annotations


# Generic tokens that often mean SQL columns or prose in audit tables.
_AMBIGUOUS_SCHEMA_TOKENS = frozenset({
    "symbol", "key", "id", "name", "type", "status", "value", "data",
})

# Line heuristics: audit / migration / handoff tables mentioning DB artifacts.
_SCHEMA_PROSE_MARKERS = (
    " column", " columns", " table", "insert ", "insert into",
    " migration", " text ", " integer", " default ", "schema.",
    " rows", "primary key", "foreign key",
)


def should_skip_moved_reference_for_prose(line: str, token: str) -> bool:
    """When True, do not emit *moved_reference* — likely prose/SQL, not code."""
    if token not in _AMBIGUOUS_SCHEMA_TOKENS:
        return False
    ll = line.lower()
    return any(m in ll for m in _SCHEMA_PROSE_MARKERS)
