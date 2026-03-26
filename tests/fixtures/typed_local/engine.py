"""Fixture: a class with a method only called via typed local variable."""


class DataEngine:
    """Processes data."""

    def process(self, items: list) -> dict:
        """This method is called from main.py via typed local resolution."""
        return {i: True for i in items}

    def validate(self, items: list) -> bool:
        """Also called via typed local."""
        return len(items) > 0
