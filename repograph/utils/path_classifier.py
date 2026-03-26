"""Central path classification for repository files.

Single source of truth for production vs test vs scripts vs docs vs vendor
heuristics. Pure functions only — no filesystem I/O.

INVARIANT: Same input always yields the same classification string.
"""
from __future__ import annotations

import re
from typing import Final

# Merged from legacy fs.TEST_PATTERNS and p11 _TEST_PATH_PATTERNS for one behaviour.
_TEST_SUBSTRINGS: Final[tuple[str, ...]] = (
    "test_",
    "_test",
    ".test.",
    ".spec.",
    "tests/",
    "test/",
    "__tests__",
    "/tests/",
    "/test/",
    "/test_",
    "/spec/",
    "/specs/",
)

# Shared utility / helper directories (from fs._UTILITY_PATH_SEGMENTS).
_UTILITY_PATH_SEGMENTS: Final[tuple[str, ...]] = (
    "/utils/",
    "/util/",
    "/utilities/",
    "/helpers/",
    "/helper/",
    "/lib/",
    "/libs/",
    "/common/",
    "/shared/",
    "/contrib/",
    "/support/",
    "utils/",
    "util/",
    "utilities/",
    "helpers/",
    "helper/",
    "lib/",
    "libs/",
    "common/",
    "shared/",
    "contrib/",
    "support/",
)

# Scripts, diagnostics, dev tools — aligned with pathways/scorer._SCRIPT_PATH.
SCRIPT_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(^|/)(scripts?|diagnostics?|tools?|bin|dev|debug|scratch|migrations?|fixtures?)(/|$)",
    re.I,
)

# Known OSS package directory names (subset of fs._KNOWN_OSS_PACKAGES) for path segments.
_VENDOR_DIR_NAMES: Final[frozenset[str]] = frozenset({
    "aiosqlite", "httpx", "requests", "click", "typer", "rich",
    "pydantic", "sqlalchemy", "pytest", "anyio", "starlette",
    "fastapi", "flask", "django", "aiohttp", "websockets",
    "cryptography", "certifi", "charset_normalizer", "urllib3",
    "packaging", "attrs", "six", "toml", "yaml", "dotenv",
    "dateutil", "pytz", "tzdata", "arrow", "pendulum",
    "tqdm", "colorama", "tabulate", "prettytable",
    "boto3", "botocore", "google", "azure",
    "numpy", "pandas", "scipy", "sklearn", "torch", "tensorflow",
    "pil", "cv2", "imageio",
    "leidenalg", "igraph", "kuzu",
})


def classify_path(file_path: str) -> str:
    """Return one of: ``production``, ``test``, ``scripts``, ``vendor``, ``docs``.

    Args:
        file_path: Repository-relative path using forward slashes.

    Returns:
        Category string; first matching rule wins: test, docs, scripts, vendor,
        then production.
    """
    p = file_path.replace("\\", "/")
    lower = p.lower()

    if _is_test_path_raw(lower):
        return "test"
    if _is_docs_path_raw(lower):
        return "docs"
    if SCRIPT_PATH_RE.search(p):
        return "scripts"
    if _has_vendor_segment(lower):
        return "vendor"
    return "production"


def is_test_path(path: str) -> bool:
    """True when the path matches test-file heuristics (tests dirs, test_ prefix, etc.)."""
    return _is_test_path_raw(path.replace("\\", "/").lower())


def is_utility_path(path: str) -> bool:
    """True when the file lives under a shared utility/helper directory segment."""
    p = path.replace("\\", "/").lower()
    return any(seg in p for seg in _UTILITY_PATH_SEGMENTS)


def is_script_path(path: str) -> bool:
    """True for scripts/, tools/, diagnostics/, bin/, dev/, etc. (non-production tooling)."""
    return bool(SCRIPT_PATH_RE.search(path.replace("\\", "/")))


def _is_test_path_raw(lower_path: str) -> bool:
    return any(pat in lower_path for pat in _TEST_SUBSTRINGS)


def _is_docs_path_raw(lower_path: str) -> bool:
    return (
        "/docs/" in lower_path
        or lower_path.startswith("docs/")
        or "/documentation/" in lower_path
        or lower_path.startswith("documentation/")
    )


def _has_vendor_segment(lower_path: str) -> bool:
    for seg in lower_path.split("/"):
        norm = seg.lower().replace("-", "_")
        if norm in _VENDOR_DIR_NAMES:
            return True
    return False
