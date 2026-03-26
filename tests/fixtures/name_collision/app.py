"""Typed-local method call must not bind to same-named import."""
from worker import flush


class Widget:
    def flush(self) -> None:
        """Instance method — must receive CALLS from run(), not worker.flush."""
        pass


def run() -> None:
    w = Widget()
    w.flush()
    flush()
