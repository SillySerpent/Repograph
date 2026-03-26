"""HTML script-tag scanner.

Scans HTML files for ``<script src="...">`` tags and returns the list of
local JavaScript file paths they reference.  This information is used by
Phase 4 (import resolution) to create synthetic ``IMPORTS`` edges between
the HTML file and each JS file it loads.  Phase 11 (dead code) then uses
those edges to determine which JS files are loaded in a script-tag (global)
context, where module-scope functions are implicitly accessible from all
co-loaded files.

Design decisions
----------------
- Uses a lightweight regex approach rather than a full HTML parser.  The
  goal is to extract ``src`` values from ``<script>`` tags, not to fully
  validate HTML.  This is robust enough for real-world codebases.
- CDN URLs (``http://``, ``https://``, ``//``) are excluded because we
  cannot analyse them statically.
- ``type="module"`` scripts are excluded because ES modules use explicit
  ``import`` statements, not implicit global scope, so they are already
  handled by the regular JS import resolution path.
- Only paths ending in ``.js``, ``.jsx``, ``.ts``, or ``.tsx`` are returned.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

# Matches a <script ...> opening tag, capturing all its attributes as a blob.
_SCRIPT_TAG_RE = re.compile(
    r"<script\b([^>]*)>",
    re.IGNORECASE | re.DOTALL,
)

# Extracts the src="..." or src='...' value from an attribute blob.
_SRC_ATTR_RE = re.compile(
    r"""\bsrc\s*=\s*(?P<q>['"])(?P<val>[^'"]+)(?P=q)""",
    re.IGNORECASE,
)

# Detects type="module" — these scripts use ES import syntax, not globals.
_TYPE_MODULE_RE = re.compile(
    r"""\btype\s*=\s*(?:['"])module(?:['"])""",
    re.IGNORECASE,
)

_JS_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx"})


def scan_script_tags(html_content: bytes, html_file_path: str) -> list[str]:
    """Return relative paths of local JS files loaded via ``<script src>``.

    Parameters
    ----------
    html_content:
        Raw bytes of the HTML file.
    html_file_path:
        The file's path relative to the repo root (used to resolve relative
        ``src`` values to repo-relative paths).

    Returns
    -------
    list[str]
        Repo-relative paths of referenced JS files, deduplicated and sorted.
        Only local paths (not CDN URLs) with recognised JS extensions are
        included.
    """
    try:
        text = html_content.decode("utf-8", errors="replace")
    except Exception:
        return []

    html_dir = str(PurePosixPath(html_file_path).parent)
    if html_dir == ".":
        html_dir = ""

    found: list[str] = []
    seen: set[str] = set()

    for match in _SCRIPT_TAG_RE.finditer(text):
        attrs = match.group(1)

        # Skip ES module scripts — they use import statements, not globals.
        if _TYPE_MODULE_RE.search(attrs):
            continue

        src_match = _SRC_ATTR_RE.search(attrs)
        if not src_match:
            continue

        src = src_match.group("val").strip()

        # Skip CDN / absolute URLs.
        if src.startswith(("http://", "https://", "//", "data:")):
            continue

        # Strip query strings / hash fragments BEFORE path resolution
        # so that "utils.js?v=21" is treated as "utils.js".
        src = src.split("?")[0].split("#")[0]
        if not src:
            continue

        # Resolve relative path against the HTML file's directory.
        resolved = _resolve_src(src, html_dir)
        if resolved is None:
            continue

        # Only include files with recognised JS extensions.
        ext = PurePosixPath(resolved).suffix.lower()
        if ext not in _JS_EXTENSIONS:
            continue

        if resolved not in seen:
            seen.add(resolved)
            found.append(resolved)

    return sorted(found)


def _resolve_src(src: str, html_dir: str) -> str | None:
    """Resolve a ``src`` attribute value to a repo-relative path.

    Handles:
    - Absolute-from-root paths: ``/static/js/utils.js`` → ``static/js/utils.js``
    - Relative paths: ``./utils.js``, ``../js/utils.js``
    - Bare relative paths: ``utils.js``

    Returns ``None`` for paths we cannot safely resolve (e.g. those with
    ``..`` escaping the repo root).
    """
    if src.startswith("/"):
        # Absolute from repo/server root — strip the leading slash.
        return src.lstrip("/")

    # Relative path — resolve against the HTML file's directory.
    if html_dir:
        base = PurePosixPath(html_dir) / src
    else:
        base = PurePosixPath(src)

    # Normalise (resolve . and ..) without touching the filesystem.
    try:
        parts = base.parts
        resolved_parts: list[str] = []
        for part in parts:
            if part == "..":
                if resolved_parts:
                    resolved_parts.pop()
                else:
                    # Escaping repo root — reject.
                    return None
            elif part != ".":
                resolved_parts.append(part)
        return "/".join(resolved_parts) if resolved_parts else None
    except Exception:
        return None
