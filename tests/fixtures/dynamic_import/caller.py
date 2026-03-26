"""Caller — inline import of ``imported_fn``."""


def run_inline() -> None:
    from callee import imported_fn

    imported_fn()
