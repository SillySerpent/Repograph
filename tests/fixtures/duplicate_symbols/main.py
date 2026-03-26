"""Fixture: main uses only the engine version of new_decision_id."""
from engine import new_decision_id, compute
from idgen import new_event_id


def run():
    decision = new_decision_id()
    event = new_event_id()
    result = compute({"x": 1, "y": 2})
    return decision, event, result
