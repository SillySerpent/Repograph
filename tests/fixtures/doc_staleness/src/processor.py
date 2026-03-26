"""Fixture: processor module with live symbols referenced in docs."""


def process_data(items: list) -> dict:
    """Process a list of items into a result dict."""
    return {i: True for i in items}


def validate_input(data: dict) -> bool:
    """Validate input data."""
    return isinstance(data, dict) and len(data) > 0


class DataProcessor:
    """Main processor class."""

    def run(self, items: list) -> dict:
        return process_data(items)
