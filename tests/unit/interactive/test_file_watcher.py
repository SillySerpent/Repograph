"""Tests for Block I2 — file watcher daemon (debounce logic)."""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, cast
from unittest.mock import MagicMock, patch, call
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers — stub out watchdog so tests run without the package
# ---------------------------------------------------------------------------


class _FakeEventHandler:
    pass


class _FakeObserver:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.joined = False
        self._handlers = []

    def schedule(self, handler, path, recursive=False):
        self._handlers.append(handler)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def join(self):
        self.joined = True


def _patch_watchdog():
    """Context: make watchdog importable with fake classes."""
    import types

    watchdog_pkg = types.ModuleType("watchdog")
    watchdog_obs = types.ModuleType("watchdog.observers")
    watchdog_evt = types.ModuleType("watchdog.events")

    setattr(watchdog_obs, "Observer", _FakeObserver)
    setattr(watchdog_evt, "FileSystemEventHandler", _FakeEventHandler)

    sys.modules.setdefault("watchdog", watchdog_pkg)
    sys.modules["watchdog.observers"] = watchdog_obs
    sys.modules["watchdog.events"] = watchdog_evt

    return watchdog_pkg, watchdog_obs, watchdog_evt


# ---------------------------------------------------------------------------
# I2.1 debounce: rapid events coalesce into one sync
# ---------------------------------------------------------------------------


def test_debounce_multiple_events_triggers_one_sync(tmp_path):
    """Multiple file events within 200 ms must trigger exactly one sync."""
    _patch_watchdog()

    from repograph.interactive.watch import FileWatcherDaemon, _DEBOUNCE_SECS

    from repograph.pipeline.runner import RunConfig
    config = RunConfig(repo_root=str(tmp_path), repograph_dir=str(tmp_path / ".repograph"), include_git=False)
    sync_calls: list[float] = []

    daemon = FileWatcherDaemon(config, repo_root=str(tmp_path))

    def _fake_sync():
        sync_calls.append(time.monotonic())

    daemon._run_sync = _fake_sync

    # Fire 5 schedule() calls in rapid succession
    for _ in range(5):
        daemon._schedule()
        time.sleep(0.01)  # 10 ms apart — all within debounce window

    # Wait for debounce to expire
    time.sleep(_DEBOUNCE_SECS + 0.1)

    assert len(sync_calls) == 1, (
        f"Expected 1 sync call after burst of 5 events, got {len(sync_calls)}"
    )


def test_debounce_two_separate_bursts_trigger_two_syncs(tmp_path):
    """Two bursts separated by > 200 ms must each trigger one sync."""
    _patch_watchdog()

    from repograph.interactive.watch import FileWatcherDaemon, _DEBOUNCE_SECS

    from repograph.pipeline.runner import RunConfig
    config = RunConfig(repo_root=str(tmp_path), repograph_dir=str(tmp_path / ".repograph"), include_git=False)
    sync_calls: list[float] = []

    daemon = FileWatcherDaemon(config, repo_root=str(tmp_path))
    daemon._run_sync = lambda: sync_calls.append(time.monotonic())

    # First burst
    daemon._schedule()
    daemon._schedule()
    time.sleep(_DEBOUNCE_SECS + 0.15)  # let first sync fire

    # Second burst
    daemon._schedule()
    daemon._schedule()
    time.sleep(_DEBOUNCE_SECS + 0.15)  # let second sync fire

    assert len(sync_calls) == 2, (
        f"Expected 2 sync calls for 2 bursts, got {len(sync_calls)}"
    )


# ---------------------------------------------------------------------------
# I2.2 start / stop lifecycle
# ---------------------------------------------------------------------------


def test_daemon_start_starts_observer(tmp_path):
    """FileWatcherDaemon.start() must call Observer.start()."""
    _patch_watchdog()

    from repograph.interactive.watch import FileWatcherDaemon

    from repograph.pipeline.runner import RunConfig
    config = RunConfig(repo_root=str(tmp_path), repograph_dir=str(tmp_path / ".repograph"), include_git=False)
    daemon = FileWatcherDaemon(config, repo_root=str(tmp_path))
    daemon.start()

    observer = cast(Any, daemon._observer)
    assert observer is not None
    assert observer.started, "Observer.start() must be called by daemon.start()"
    daemon.stop()


def test_daemon_stop_stops_and_joins_observer(tmp_path):
    """FileWatcherDaemon.stop() must call Observer.stop() and join()."""
    _patch_watchdog()

    from repograph.interactive.watch import FileWatcherDaemon

    from repograph.pipeline.runner import RunConfig
    config = RunConfig(repo_root=str(tmp_path), repograph_dir=str(tmp_path / ".repograph"), include_git=False)
    daemon = FileWatcherDaemon(config, repo_root=str(tmp_path))
    daemon.start()
    daemon.stop()

    assert daemon._observer is None, "Observer reference must be cleared after stop()"


def test_daemon_stop_cancels_pending_debounce(tmp_path):
    """stop() must cancel any in-flight debounce timer."""
    _patch_watchdog()

    from repograph.interactive.watch import FileWatcherDaemon, _DEBOUNCE_SECS

    from repograph.pipeline.runner import RunConfig
    config = RunConfig(repo_root=str(tmp_path), repograph_dir=str(tmp_path / ".repograph"), include_git=False)
    sync_calls: list[int] = []

    daemon = FileWatcherDaemon(config, repo_root=str(tmp_path))
    daemon._run_sync = lambda: sync_calls.append(1)

    daemon.start()
    daemon._schedule()  # start a debounce timer
    daemon.stop()       # should cancel the timer before it fires

    time.sleep(_DEBOUNCE_SECS + 0.1)
    assert len(sync_calls) == 0, "Cancelled debounce must not fire after stop()"


# ---------------------------------------------------------------------------
# I2.3 sync status reported to stderr
# ---------------------------------------------------------------------------


def test_sync_ok_reports_to_stderr(tmp_path, capsys):
    """A successful sync must print 'repograph: sync ok' to stderr."""
    _patch_watchdog()

    from repograph.interactive.watch import FileWatcherDaemon

    from repograph.pipeline.runner import RunConfig
    config = RunConfig(repo_root=str(tmp_path), repograph_dir=str(tmp_path / ".repograph"), include_git=False)
    daemon = FileWatcherDaemon(config, repo_root=str(tmp_path))

    with patch("repograph.pipeline.runner.run_incremental_pipeline") as mock_run:
        mock_run.return_value = None
        # Call the sync function directly
        daemon._run_sync()

    captured = capsys.readouterr()
    assert "repograph: sync ok" in captured.err


def test_sync_error_reports_to_stderr(tmp_path, capsys):
    """A sync failure must print 'repograph: sync error' to stderr."""
    _patch_watchdog()

    from repograph.interactive.watch import FileWatcherDaemon

    from repograph.pipeline.runner import RunConfig
    config = RunConfig(repo_root=str(tmp_path), repograph_dir=str(tmp_path / ".repograph"), include_git=False)
    daemon = FileWatcherDaemon(config, repo_root=str(tmp_path))

    with patch("repograph.pipeline.runner.run_incremental_pipeline") as mock_run:
        mock_run.side_effect = RuntimeError("boom")
        daemon._run_sync()

    captured = capsys.readouterr()
    assert "repograph: sync error" in captured.err


# ---------------------------------------------------------------------------
# I2.4 ImportError when watchdog missing
# ---------------------------------------------------------------------------


def test_watchdog_missing_raises_import_error(tmp_path):
    """FileWatcherDaemon.start() must raise ImportError if watchdog is absent."""
    import types

    # Remove watchdog from sys.modules
    saved = {}
    for key in ["watchdog", "watchdog.observers", "watchdog.events"]:
        if key in sys.modules:
            saved[key] = sys.modules.pop(key)

    # Inject a stub that raises ImportError on access to Observer
    bad_obs = types.ModuleType("watchdog.observers")
    bad_obs.Observer = None  # type: ignore[assignment]

    class _RaisingMod(types.ModuleType):
        def __getattr__(self, name):
            raise ImportError("watchdog not installed")

    sys.modules["watchdog"] = _RaisingMod("watchdog")
    sys.modules["watchdog.observers"] = _RaisingMod("watchdog.observers")
    sys.modules["watchdog.events"] = _RaisingMod("watchdog.events")

    try:
        # Reimport to pick up the raising stub
        if "repograph.interactive.watch" in sys.modules:
            del sys.modules["repograph.interactive.watch"]
        from repograph.interactive.watch import FileWatcherDaemon

        from repograph.pipeline.runner import RunConfig
        config = RunConfig(repo_root=str(tmp_path), repograph_dir=str(tmp_path / ".repograph"), include_git=False)
        daemon = FileWatcherDaemon(config, repo_root=str(tmp_path))

        try:
            daemon.start()
            assert False, "ImportError expected"
        except ImportError:
            pass
    finally:
        # Restore
        for key in ["watchdog", "watchdog.observers", "watchdog.events"]:
            sys.modules.pop(key, None)
        for key, val in saved.items():
            sys.modules[key] = val
        # Reload the watch module with real (fake) stubs
        sys.modules.pop("repograph.interactive.watch", None)
