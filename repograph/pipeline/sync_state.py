"""Sync lock file — signals in-progress indexing and detects stale locks."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

LOCK_NAME = "sync.lock"


@dataclass
class SyncLockInfo:
    pid: int
    started_at: str
    mode: str
    repo_root: str
    phase: str = ""


def _lock_path(repograph_dir: str) -> str:
    meta = os.path.join(repograph_dir, "meta")
    return os.path.join(meta, LOCK_NAME)


def write_sync_lock(
    repograph_dir: str,
    *,
    mode: str,
    repo_root: str,
    phase: str = "",
) -> str:
    """Write sync.lock; returns path."""
    meta = os.path.join(repograph_dir, "meta")
    os.makedirs(meta, exist_ok=True)
    path = os.path.join(meta, LOCK_NAME)
    info = {
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "repo_root": os.path.abspath(repo_root),
        "phase": phase,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2)
        fh.write("\n")
    return path


def clear_sync_lock(repograph_dir: str) -> None:
    path = _lock_path(repograph_dir)
    try:
        os.remove(path)
    except OSError:
        pass


def read_sync_lock(repograph_dir: str) -> dict[str, Any] | None:
    path = _lock_path(repograph_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def is_pid_alive(pid: int) -> bool:
    """Best-effort: True if process pid may still be running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def lock_status(repograph_dir: str) -> tuple[str, SyncLockInfo | None]:
    """Return (state, info) where state is 'none'|'stale'|'active'."""
    raw = read_sync_lock(repograph_dir)
    if not raw:
        return "none", None
    try:
        info = SyncLockInfo(
            pid=int(raw["pid"]),
            started_at=str(raw.get("started_at", "")),
            mode=str(raw.get("mode", "")),
            repo_root=str(raw.get("repo_root", "")),
            phase=str(raw.get("phase", "")),
        )
    except (KeyError, TypeError, ValueError):
        return "stale", None
    if is_pid_alive(info.pid):
        return "active", info
    return "stale", info
