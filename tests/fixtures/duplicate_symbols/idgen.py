"""Fixture: duplicate symbol — stale copy in a utility module."""
import uuid as _uuid


def new_decision_id() -> str:
    """Live version of new_decision_id — used by the engine."""
    return f"dec_{_uuid.uuid4().hex[:8]}"


def new_event_id() -> str:
    """Generate an event ID — still live, not duplicated."""
    import uuid
    return f"evt_{uuid.uuid4().hex[:8]}"
