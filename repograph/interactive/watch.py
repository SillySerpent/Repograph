"""File watcher daemon for real-time incremental sync (Block I2).

The watcher uses ``watchdog`` to monitor the repo for source file changes.
A 200 ms debounce timer consolidates rapid bursts (e.g. a formatter saving
many files at once) into a single incremental sync.  Sync status is reported
to ``stderr`` in a machine-readable format so callers (scripts, CI hooks) can
detect failures without parsing Rich console output.

Usage::

    from repograph.interactive.watch import FileWatcherDaemon

    daemon = FileWatcherDaemon(config, repo_root="/path/to/repo")
    daemon.start()
    # ... block until KeyboardInterrupt ...
    daemon.stop()
"""
from __future__ import annotations

import sys
import threading
import time

_DEBOUNCE_SECS = 0.2  # 200 ms


class FileWatcherDaemon:
    """Debounced file-system watcher that triggers incremental sync on changes.

    Parameters
    ----------
    config:
        A ``RunConfig`` instance for the incremental pipeline.
    repo_root:
        Absolute path to the repository root to watch.
    """

    def __init__(self, config, repo_root: str) -> None:
        self._config = config
        self._repo_root = repo_root
        self._observer = None
        self._debounce_timer: threading.Timer | None = None
        self._debounce_lock = threading.Lock()
        self._run_sync = self._make_sync_fn()

    def _make_sync_fn(self):
        """Return the function called after the debounce delay expires."""

        def _do_sync():
            # Import lazily so unit tests can patch the module attribute.
            from repograph.pipeline.runner import run_incremental_pipeline
            try:
                run_incremental_pipeline(self._config)
                print("repograph: sync ok", file=sys.stderr, flush=True)
            except Exception as exc:
                print(f"repograph: sync error: {exc}", file=sys.stderr, flush=True)

        return _do_sync

    def _schedule(self) -> None:
        """Reset the debounce timer so a burst of events triggers one sync."""
        with self._debounce_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            t = threading.Timer(_DEBOUNCE_SECS, self._run_sync)
            t.daemon = True
            self._debounce_timer = t
            t.start()

    def _make_handler(self):
        """Return a watchdog ``FileSystemEventHandler`` that schedules syncs."""
        try:
            from watchdog.events import FileSystemEventHandler
        except ImportError as exc:
            raise ImportError(
                "watchdog is required for file watching: pip install watchdog"
            ) from exc

        repo_root = self._repo_root
        schedule = self._schedule

        class _Handler(FileSystemEventHandler):
            @staticmethod
            def _is_source_file(path: bytes | str) -> bool:
                from repograph.utils.fs import EXTENSION_TO_LANGUAGE
                import pathlib
                p = path.decode() if isinstance(path, bytes) else path
                if ".repograph" in p:
                    return False
                return pathlib.Path(p).suffix.lower() in EXTENSION_TO_LANGUAGE

            def on_modified(self, event):
                if not event.is_directory and self._is_source_file(event.src_path):
                    schedule()

            def on_created(self, event):
                if not event.is_directory and self._is_source_file(event.src_path):
                    schedule()

            def on_deleted(self, event):
                if not event.is_directory and self._is_source_file(event.src_path):
                    schedule()

            def on_moved(self, event):
                if not event.is_directory:
                    if self._is_source_file(event.src_path) or self._is_source_file(
                        event.dest_path
                    ):
                        schedule()

        return _Handler()

    def start(self) -> None:
        """Start the background observer thread."""
        try:
            from watchdog.observers import Observer
        except ImportError as exc:
            raise ImportError(
                "watchdog is required for file watching: pip install watchdog"
            ) from exc

        handler = self._make_handler()
        self._observer = Observer()
        self._observer.schedule(handler, self._repo_root, recursive=True)
        self._observer.start()

    def stop(self) -> None:
        """Stop the observer and cancel any pending debounce timer."""
        with self._debounce_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def run_until_interrupted(self) -> None:
        """Block the calling thread until ``KeyboardInterrupt``."""
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
