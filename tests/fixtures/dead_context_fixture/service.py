"""Production module with functions in various dead-code states."""


def alive_function(x: int) -> int:
    """Called from main code — should be alive."""
    return x * 2


def dead_everywhere(x: int) -> str:
    """Never called from anywhere — dead_everywhere."""
    return str(x)


def dead_in_production(x: int) -> float:
    """Only called from the test file — dead_in_production."""
    return float(x)
