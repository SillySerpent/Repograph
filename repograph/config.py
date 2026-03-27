"""Repository paths, index layout, and optional YAML tuning.

The on-disk index lives under ``<repo_root>/.repograph/`` (see :data:`REPOGRAPH_DIR`).
The Kuzu database file is ``graph.db`` inside that directory (:func:`db_path`).
Indexing skips are merged from ``.repograph/repograph.index.yaml`` and the legacy
repo-root ``repograph.index.yaml`` (:func:`load_extra_exclude_dirs`).

**Persistence:** graph reads/writes are implemented in :mod:`repograph.graph_store`
(split modules: ``store_writes_upserts``, ``store_writes_rel``, etc.); this module
only defines paths and walk-time config — not SQL/Kuzu calls.
"""
from __future__ import annotations

import os

from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="config")

REPOGRAPH_DIR = ".repograph"
# Optional YAML: extra top-level directory names to skip when indexing.
# Read from ``.repograph/repograph.index.yaml`` first, then legacy repo-root file.
INDEX_CONFIG_FILENAME = "repograph.index.yaml"
DB_FILENAME = "graph.db"
DEFAULT_CONTEXT_TOKENS = 2000
DEFAULT_GIT_DAYS = 180
DEFAULT_ENTRY_POINT_LIMIT = 20
DEFAULT_MIN_COMMUNITY_SIZE = 3
DEFAULT_MODULE_EXPANSION_THRESHOLD = 15
ERROR_TRUNCATION_CHARS = 4000
AGENT_GUIDE_MAX_FILE_READ_BYTES = 3000
PREFETCH_CHUNK_SIZE = 48

LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".sh": "shell",
    ".bash": "shell",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".md": "markdown",
    ".markdown": "markdown",
}


def repograph_dir(repo_root: str) -> str:
    return os.path.join(repo_root, REPOGRAPH_DIR)


def db_path(repo_root: str) -> str:
    return os.path.join(repograph_dir(repo_root), DB_FILENAME)


def get_repo_root(path: str | None = None) -> str:
    """Walk up from *path* (default: cwd) to find the repo root (.repograph dir).

    Raises :exc:`~repograph.exceptions.RepographNotFoundError` when no
    ``.repograph`` directory is found anywhere in the directory tree.  Callers
    that can sensibly operate without an index (e.g. ``repograph clean``) should
    catch this exception explicitly and fall back to ``os.path.abspath(path or
    os.getcwd())``.
    """
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
    return os.path.isdir(repograph_dir(repo_root)) and os.path.exists(
        db_path(repo_root)
    )


def _read_index_yaml(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        import yaml

        with open(path, encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        _logger.warning(
            "could not load index YAML — config file will be ignored",
            path=path,
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )
        return None

    if isinstance(data, dict):
        from repograph.config_schema import validate_index_yaml
        validate_index_yaml(data, path, _logger)

    return data


def _exclude_dirs_from_mapping(data: dict) -> set[str]:
    raw = data.get("exclude_dirs") or []
    out: set[str] = set()
    for item in raw:
        s = str(item).strip().strip("/")
        if s and "/" not in s and ".." not in s:
            out.add(s)
    return out


def _default_embedded_repograph_exclude(repo_root: str) -> set[str]:
    """If a nested copy of RepoGraph lives under ``<root>/repograph/`` with its own
    ``pyproject.toml``, skip that top-level folder by default (no config file needed).

    The upstream RepoGraph repository itself has ``pyproject.toml`` at the repo root
    only, so this does not exclude the package when indexing that project.
    """
    inner = os.path.join(repo_root, "repograph", "pyproject.toml")
    if os.path.isfile(inner):
        return {"repograph"}
    return set()


def load_extra_exclude_dirs(repo_root: str) -> set[str]:
    """Load extra directory names to skip during the file walk (phase 1).

    Merges, in order:

    1. ``.repograph/repograph.index.yaml`` (preferred; stays out of VCS if
       ``.repograph/`` is gitignored)
    2. Legacy ``repograph.index.yaml`` at the repository root
    3. Automatic exclusion of top-level ``repograph/`` when it looks like a
       vendored RepoGraph tree (``repograph/pyproject.toml`` present)

    YAML format::

        exclude_dirs:
          - vendor
        disable_auto_excludes: false   # if true, skip (3) only

    Only simple top-level directory names are supported (no slashes).
    """
    paths = (
        os.path.join(repograph_dir(repo_root), INDEX_CONFIG_FILENAME),
        os.path.join(repo_root, INDEX_CONFIG_FILENAME),
    )
    out: set[str] = set()
    disable_auto = False
    for path in paths:
        data = _read_index_yaml(path)
        if not data:
            continue
        out |= _exclude_dirs_from_mapping(data)
        if data.get("disable_auto_excludes"):
            disable_auto = True
    if not disable_auto:
        out |= _default_embedded_repograph_exclude(repo_root)
    return out


def load_doc_symbol_options(repo_root: str) -> dict:
    """Read optional doc-symbol phase flags from ``repograph.index.yaml``.

    Keys
    ----
    doc_symbols_flag_unknown
        When True, Phase 15 emits ``unknown_reference`` (medium severity) for
        qualified (dotted) backtick tokens that do not appear in the symbol
        index.  Default False.

    Merges YAML from ``.repograph/repograph.index.yaml`` then legacy repo-root
    file; a True value in any file enables the flag.
    """
    paths = (
        os.path.join(repograph_dir(repo_root), INDEX_CONFIG_FILENAME),
        os.path.join(repo_root, INDEX_CONFIG_FILENAME),
    )
    flag_unknown = False
    for path in paths:
        data = _read_index_yaml(path)
        if not data:
            continue
        v = data.get("doc_symbols_flag_unknown")
        if v is True:
            flag_unknown = True
    return {"doc_symbols_flag_unknown": flag_unknown}
