"""Filesystem path helpers for RepoGraph settings and index state."""
from __future__ import annotations

import os

from ._constants import DB_FILENAME, REPOGRAPH_DIR


def repograph_dir(repo_root: str) -> str:
    """Return the absolute path to the ``.repograph/`` index directory."""
    return os.path.join(repo_root, REPOGRAPH_DIR)


def db_path(repo_root: str) -> str:
    """Return the absolute path to the KuzuDB database file."""
    return os.path.join(repograph_dir(repo_root), DB_FILENAME)


def get_repo_root(path: str | None = None) -> str:
    """Walk up from *path* (default: cwd) to find the repo root."""
    from repograph.exceptions import RepographNotFoundError

    start = os.path.realpath(os.path.abspath(path or os.getcwd()))
    current = start
    seen: set[str] = set()
    while True:
        if current in seen:
            break
        seen.add(current)
        if os.path.isdir(os.path.join(current, REPOGRAPH_DIR)):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise RepographNotFoundError(start)


def is_initialized(repo_root: str) -> bool:
    """Return True when ``.repograph/graph.db`` exists."""
    return os.path.isdir(repograph_dir(repo_root)) and os.path.exists(db_path(repo_root))
