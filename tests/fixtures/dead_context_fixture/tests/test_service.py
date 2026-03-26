"""Test file — calls dead_in_production, marking it as test-only caller."""
from service import dead_in_production


def test_dead_in_production_function():
    result = dead_in_production(42)
    assert result == 42.0
