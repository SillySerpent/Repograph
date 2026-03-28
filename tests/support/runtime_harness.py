"""Shared process and artifact helpers for runtime-oriented tests."""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Mapping, Sequence


@dataclass
class ManagedProcess:
    """A spawned process owned by the test harness."""

    process: subprocess.Popen[str]
    command: tuple[str, ...]
    cwd: str
    stdout_path: str
    stderr_path: str
    _stdout_handle: IO[str] | None = field(repr=False, default=None)
    _stderr_handle: IO[str] | None = field(repr=False, default=None)

    @property
    def pid(self) -> int:
        return int(self.process.pid)

    @property
    def returncode(self) -> int | None:
        return self.process.poll()

    def close_streams(self) -> None:
        for handle in (self._stdout_handle, self._stderr_handle):
            if handle is not None and not handle.closed:
                handle.close()

    def read_stdout(self) -> str:
        self.close_streams()
        return Path(self.stdout_path).read_text(encoding="utf-8")

    def read_stderr(self) -> str:
        self.close_streams()
        return Path(self.stderr_path).read_text(encoding="utf-8")


@dataclass
class ArtifactRegistry:
    """Tracks temporary files/directories and removes them safely."""

    paths: list[Path] = field(default_factory=list)

    def register(self, path: str | Path) -> Path:
        registered = Path(path)
        self.paths.append(registered)
        return registered

    def cleanup(self) -> None:
        for path in reversed(self.paths):
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=False)
            else:
                path.unlink()


def allocate_free_port(host: str = "127.0.0.1") -> int:
    """Reserve and release a free local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


def _temp_capture_file(suffix: str) -> tuple[str, IO[str]]:
    fd, path = tempfile.mkstemp(prefix="repograph-runtime-", suffix=suffix)
    return path, os.fdopen(fd, "w+", encoding="utf-8")


def spawn_repo_process(
    command: Sequence[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str] | None = None,
    stdout_path: str | Path | None = None,
    stderr_path: str | Path | None = None,
) -> ManagedProcess:
    """Spawn a process in its own session so test teardown can kill the whole tree."""
    stdout_handle: IO[str] | None = None
    stderr_handle: IO[str] | None = None

    if stdout_path is None:
        stdout_path, stdout_handle = _temp_capture_file(".stdout.log")
    else:
        stdout_handle = Path(stdout_path).open("w+", encoding="utf-8")
    if stderr_path is None:
        stderr_path, stderr_handle = _temp_capture_file(".stderr.log")
    else:
        stderr_handle = Path(stderr_path).open("w+", encoding="utf-8")

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=merged_env,
        stdout=stdout_handle,
        stderr=stderr_handle,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    return ManagedProcess(
        process=process,
        command=tuple(command),
        cwd=str(cwd),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        _stdout_handle=stdout_handle,
        _stderr_handle=stderr_handle,
    )


def wait_for_http_ready(
    url: str,
    *,
    timeout_seconds: float = 10.0,
    interval_seconds: float = 0.1,
) -> None:
    """Wait until an HTTP endpoint responds or raise ``TimeoutError``."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=min(1.0, timeout_seconds)):
                return
        except urllib.error.HTTPError:
            return
        except Exception as exc:  # pragma: no cover - exercised via timeout path
            last_error = exc
            time.sleep(interval_seconds)

    message = f"Timed out waiting for HTTP readiness at {url}"
    if last_error is not None:
        raise TimeoutError(f"{message}: {last_error}") from last_error
    raise TimeoutError(message)


def stop_process_tree(
    managed: ManagedProcess,
    *,
    terminate_timeout_seconds: float = 5.0,
    kill_timeout_seconds: float = 2.0,
) -> int | None:
    """Terminate a managed process and its process group, escalating if needed."""
    process = managed.process
    if process.poll() is not None:
        managed.close_streams()
        return process.returncode

    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:  # pragma: no cover - non-POSIX fallback
            process.terminate()
        process.wait(timeout=terminate_timeout_seconds)
    except subprocess.TimeoutExpired:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:  # pragma: no cover - non-POSIX fallback
            process.kill()
        process.wait(timeout=kill_timeout_seconds)
    finally:
        managed.close_streams()

    return process.returncode


def assert_no_child_processes_left(managed: ManagedProcess) -> None:
    """Assert that a managed process is no longer alive."""
    if managed.process.poll() is None:
        raise AssertionError(
            f"Process {managed.pid} is still running for command {managed.command!r}"
        )
    try:
        os.kill(managed.pid, 0)
    except ProcessLookupError:
        return
    except PermissionError:
        return
    raise AssertionError(
        f"Process {managed.pid} still appears to exist after teardown for command {managed.command!r}"
    )
