"""Main entry — only calls alive_function."""
from service import alive_function


def run(value: int) -> int:
    return alive_function(value)
