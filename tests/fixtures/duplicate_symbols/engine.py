"""Fixture: duplicate symbol — live copy in the engine."""
import uuid as _uuid


def new_decision_id() -> str:
    """Live version of new_decision_id — used by the engine."""
    return f"dec_{_uuid.uuid4().hex[:8]}"


def compute(data: dict) -> dict:
    """Unique to this file — not a duplicate."""
    return {k: v * 2 for k, v in data.items()}
