"""Tests for plugin lifecycle thread-safety and singleton guarantees (Block B4/A8)."""
from __future__ import annotations

import threading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset():
    """Reset lifecycle state before each test."""
    from repograph.plugins import lifecycle
    lifecycle.reset_hook_scheduler()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_hook_scheduler_singleton():
    """get_hook_scheduler() returns the same object on repeated calls."""
    _reset()
    from repograph.plugins.lifecycle import get_hook_scheduler
    s1 = get_hook_scheduler()
    s2 = get_hook_scheduler()
    assert s1 is s2


def test_reset_hook_scheduler_produces_new_instance():
    """After reset, get_hook_scheduler() returns a fresh object."""
    _reset()
    from repograph.plugins.lifecycle import get_hook_scheduler, reset_hook_scheduler
    s1 = get_hook_scheduler()
    reset_hook_scheduler()
    s2 = get_hook_scheduler()
    assert s1 is not s2


def test_ensure_all_plugins_registered_idempotent():
    """Calling ensure_all_plugins_registered() twice must not double-register."""
    _reset()
    from repograph.plugins.lifecycle import (
        ensure_all_plugins_registered,
        get_hook_scheduler,
    )
    ensure_all_plugins_registered()
    # Get the parser count after first registration
    sched = get_hook_scheduler()
    parsers_before = list(sched.list_for_hook("on_file_parsed"))

    ensure_all_plugins_registered()
    parsers_after = list(sched.list_for_hook("on_file_parsed"))
    assert len(parsers_before) == len(parsers_after), (
        "Double registration detected: plugin count changed after second ensure call"
    )


def test_hook_scheduler_concurrent_init():
    """Concurrent calls to get_hook_scheduler() must produce exactly one scheduler."""
    _reset()
    from repograph.plugins.lifecycle import get_hook_scheduler

    results: list = []
    errors: list = []
    n_threads = 6

    def worker():
        try:
            results.append(get_hook_scheduler())
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Threads raised exceptions: {errors}"
    assert len(results) == n_threads
    # All threads must have gotten the same object
    assert all(r is results[0] for r in results), (
        "Multiple different scheduler instances created"
    )


def test_ensure_all_plugins_registered_concurrent():
    """Concurrent calls to ensure_all_plugins_registered() must not cause errors."""
    _reset()
    from repograph.plugins.lifecycle import ensure_all_plugins_registered

    errors: list = []
    n_threads = 6

    def worker():
        try:
            ensure_all_plugins_registered()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Threads raised exceptions: {errors}"


def test_get_hook_scheduler_returns_fully_bootstrapped_scheduler():
    """The scheduler returned by get_hook_scheduler() must have parsers registered."""
    _reset()
    from repograph.plugins.lifecycle import get_hook_scheduler

    sched = get_hook_scheduler()
    # Parsers register for on_file_parsed; check at least one is present
    parsers = sched.list_for_hook("on_file_parsed", kind="parser")
    assert len(parsers) > 0, "No parsers registered after get_hook_scheduler()"
