"""Fixture: calls DataEngine methods via a typed local variable."""
from engine import DataEngine


def run_pipeline(raw: list) -> dict:
    eng = DataEngine()
    if not eng.validate(raw):
        return {}
    return eng.process(raw)
