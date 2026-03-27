"""File walking and gitignore support."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pathspec

from repograph.core.models import FileRecord
from repograph.utils.hashing import hash_file_content
from repograph.utils.path_classifier import is_test_path, is_utility_path


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

EXTENSION_TO_LANGUAGE: dict[str, str] = {
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

# Files/dirs always excluded
ALWAYS_EXCLUDE_DIRS = {
    ".git", ".repograph", "__pycache__", ".pytest_cache",
    "node_modules", ".venv", "venv", "env", ".env",
    "dist", "build", ".tox", ".mypy_cache", ".ruff_cache",
    "*.egg-info",
}

ALWAYS_EXCLUDE_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dylib", ".dll",
    ".exe", ".bin", ".class", ".jar",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".lock", ".sum",
    ".zip", ".tar", ".gz", ".bz2",
    ".pdf", ".doc", ".docx",
    ".db", ".sqlite", ".sqlite3",
    ".min.js", ".min.css",
}

CONFIG_EXTENSIONS = {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".env", ".lock"}
CONFIG_NAMES = {"Makefile", "Dockerfile", ".dockerignore", ".gitignore", ".gitattributes"}


def _is_test_file(path: str) -> bool:
    return is_test_path(path)


def _is_utility_file(path: str) -> bool:
    """Return True when a file lives in a shared utility / helper directory.

    Functions in utility modules are designed to be imported by any caller in
    the current repo *or* by external consumers.  Having zero in-repo callers
    therefore does not mean a function is dead — it may simply be unused right
    now or exported for external use.  The dead-code classifier downgrades these
    from ``definitely_dead`` to ``possibly_dead``.
    """
    return is_utility_path(path)


def _is_config_file(path: str, name: str) -> bool:
    ext = os.path.splitext(name)[1].lower()
    return ext in CONFIG_EXTENSIONS or name in CONFIG_NAMES


# ---------------------------------------------------------------------------
# Vendored library detection
# ---------------------------------------------------------------------------

# Well-known OSS packages that may be vendored (copied in-tree) rather than
# installed.  When a top-level or src/ sub-directory matches one of these
# names it is likely vendored and should be excluded from pathway steps.
_KNOWN_OSS_PACKAGES: frozenset[str] = frozenset({
    "aiosqlite", "httpx", "requests", "click", "typer", "rich",
    "pydantic", "sqlalchemy", "pytest", "anyio", "starlette",
    "fastapi", "flask", "django", "aiohttp", "websockets",
    "cryptography", "certifi", "charset_normalizer", "urllib3",
    "packaging", "attrs", "six", "toml", "yaml", "dotenv",
    "dateutil", "pytz", "tzdata", "arrow", "pendulum",
    "tqdm", "colorama", "tabulate", "prettytable",
    "boto3", "botocore", "google", "azure",
    "numpy", "pandas", "scipy", "sklearn", "torch", "tensorflow",
    "PIL", "cv2", "imageio",
    "leidenalg", "igraph", "kuzu",
})

# Markers that indicate a directory is a self-contained package (vendored)
_VENDOR_MARKERS = frozenset({
    "setup.py", "setup.cfg", "pyproject.toml",
    "PKG-INFO", "METADATA", "WHEEL",
    "package.json",  # vendored JS packages
})


def is_likely_vendored(dir_path: str) -> bool:
    """Return True when a directory looks like a vendored OSS library.

    Heuristic (all conditions must hold):
    1. The directory name (normalised) matches a known OSS package name.
    2. The directory contains an ``__init__.py`` (it is a Python package).
    3. At least one of the vendor marker files exists inside the directory
       (``setup.py``, ``pyproject.toml``, ``PKG-INFO``, etc.).

    Parameters
    ----------
    dir_path:
        Absolute or relative path to the directory to inspect.
    """
    name = os.path.basename(dir_path).lower().replace("-", "_")
    if name not in _KNOWN_OSS_PACKAGES:
        return False
    if not os.path.exists(os.path.join(dir_path, "__init__.py")):
        return False
    return any(
        os.path.exists(os.path.join(dir_path, marker))
        for marker in _VENDOR_MARKERS
    )


def _load_gitignore(repo_root: str) -> pathspec.PathSpec | None:
    gitignore_path = os.path.join(repo_root, ".gitignore")
    if not os.path.exists(gitignore_path):
        return None
    with open(gitignore_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return pathspec.PathSpec.from_lines("gitignore", lines)


def walk_repo(
    repo_root: str,
    extra_exclude_dirs: set[str] | None = None,
) -> list[FileRecord]:
    """
    Walk a repository root and return FileRecord objects for every
    parseable source file. Respects .gitignore and built-in exclusions.
    """
    root = Path(repo_root).resolve()
    gitignore = _load_gitignore(str(root))
    exclude_dirs = ALWAYS_EXCLUDE_DIRS | (extra_exclude_dirs or set())

    records: list[FileRecord] = []
    # Cache vendored-dir checks: abs_dirpath → bool
    _vendored_cache: dict[str, bool] = {}

    def _dir_is_vendored(abs_dirpath: str) -> bool:
        """Check if abs_dirpath or any of its ancestors (up to repo root) is vendored."""
        if abs_dirpath in _vendored_cache:
            return _vendored_cache[abs_dirpath]
        # Walk up from the directory itself to the repo root
        candidate = abs_dirpath
        repo_str = str(root)
        while candidate and candidate.startswith(repo_str) and candidate != repo_str:
            if is_likely_vendored(candidate):
                _vendored_cache[abs_dirpath] = True
                return True
            candidate = os.path.dirname(candidate)
        _vendored_cache[abs_dirpath] = False
        return False

    for dirpath, dirnames, filenames in os.walk(str(root)):
        # Filter excluded directories in-place so os.walk won't recurse
        dirnames[:] = [
            d for d in dirnames
            if d not in exclude_dirs
            and not d.endswith(".egg-info")
        ]

        # Determine vendored status once per directory
        vendored = _dir_is_vendored(dirpath)

        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, str(root)).replace("\\", "/")

            # Check gitignore
            if gitignore and gitignore.match_file(rel_path):
                continue

            name = filename
            ext = os.path.splitext(filename)[1].lower()

            # Skip excluded extensions
            if ext in ALWAYS_EXCLUDE_EXTENSIONS:
                continue
            if filename.endswith(".min.js") or filename.endswith(".min.css"):
                continue

            language = EXTENSION_TO_LANGUAGE.get(ext, "")
            # Only index files we can parse
            if not language:
                continue

            try:
                stat = os.stat(abs_path)
                size_bytes = stat.st_size
                mtime = stat.st_mtime
            except OSError:
                continue

            # Read and hash content
            try:
                with open(abs_path, "rb") as f:
                    content = f.read()
            except (OSError, PermissionError):
                continue

            source_hash = hash_file_content(content)
            line_count = content.count(b"\n") + 1

            records.append(FileRecord(
                path=rel_path,
                abs_path=abs_path,
                name=name,
                extension=ext,
                language=language,
                size_bytes=size_bytes,
                line_count=line_count,
                source_hash=source_hash,
                is_test=_is_test_file(rel_path),
                is_config=_is_config_file(rel_path, name),
                mtime=mtime,
                is_vendored=vendored,
            ))

    records.sort(key=lambda r: r.path)
    return records


def read_file_content(abs_path: str) -> str:
    """Read a source file as UTF-8, replacing bad bytes."""
    with open(abs_path, encoding="utf-8", errors="replace") as f:
        return f.read()


def relative_to(path: str, base: str) -> str:
    return os.path.relpath(path, base).replace("\\", "/")
