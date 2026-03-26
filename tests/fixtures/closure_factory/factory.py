"""Fixture for closure-returned function detection."""


def make_handler(name: str):
    """Returns a closure. The inner _handle should NOT be dead code."""
    def _handle(event: dict) -> str:
        return f"{name}: {event}"
    return _handle


def make_stop(service):
    """Async stop closure — mirrors the bootstrap._make_stop pattern."""
    async def _stop() -> None:
        service.stop()
    return _stop


def truly_dead_helper(x: int) -> int:
    """This is assigned but never returned — genuinely dead."""
    return x * 2


def caller():
    """Assigns but never returns the nested fn — nested_fn should be dead."""
    def nested_fn():
        pass
    result = nested_fn()  # called, not returned — this is reachable via direct call
    return result
