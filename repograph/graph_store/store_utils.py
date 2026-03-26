"""Small helpers shared by GraphStore modules (JSON, time, hashing, DB teardown)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone


def _j(val: list | dict | None) -> str:
    """Serialize a list/dict to JSON string for storage."""
    if val is None:
        return "[]"
    return json.dumps(val)


def _ts(dt: datetime | None = None) -> str:
    """ISO timestamp string."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.isoformat()


def _hash_content(text: str) -> str:
    """Stable SHA-256 hash of a text string (process-restart safe).
    Replaces Python built-in hash() which is randomised per-process."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _delete_db_dir(db_path: str) -> None:
    """Delete an existing KuzuDB database and ALL associated sidecar files.

    KuzuDB persists state across up to three artifacts:

      - db_path           — the main database file or directory
      - db_path + ".wal"  — the write-ahead log (may hold ALL live data when
                            KuzuDB is in WAL mode and has not yet checkpointed)
      - db_path + ".shm"  — shared-memory coordination file used in WAL mode

    All three MUST be removed for a clean rebuild.  Removing only the main file
    while leaving the WAL behind causes KuzuDB to replay the WAL on next open,
    resurrecting every node and edge from the previous run — including nodes for
    files that have since been deleted from the repo.

    Callers must release all open KuzuDB handles (or rely on gc.collect() to do
    so) BEFORE calling this function.  This function calls gc.collect() itself
    as a defensive measure, but explicit handle closure is more reliable.

    Retries up to 3 times with a short pause to handle platform-level
    file-handle release latency (e.g. Windows file locks, slow GC on CPython).
    """
    import gc
    import time

    gc.collect()

    candidates = [
        db_path,
        db_path + ".wal",
        db_path + ".shm",
    ]

    if not any(os.path.exists(c) for c in candidates):
        return

    for attempt in range(3):
        try:
            for target in candidates:
                if not os.path.exists(target):
                    continue
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.remove(target)
            return
        except OSError:
            if attempt < 2:
                time.sleep(0.1)
                gc.collect()
            else:
                raise
