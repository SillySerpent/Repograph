"""Cross-language name normalization resolver (F6).

Provides a sub-quadratic fallback for cross-language symbol matching based on
name normalization.  Two functions are considered candidates when their names
normalise to the same form (camelCase ↔ snake_case).

Usage in the pipeline (Phase 5c or a dedicated phase):
    index = build_cross_lang_name_index(parsed_files)
    candidates = index.get("get_user", {})
    for lang, fn_ids in candidates.items():
        ...

This index is used ONLY as a low-confidence fallback (0.3) when:
- F4 (HTTP endpoint matching) found no match, AND
- F5 (explicit import resolution) found no match.

Only exported functions (is_exported=True) with zero existing cross-language
callers are eligible for name-similarity matching.
"""
from __future__ import annotations

import re

from repograph.core.models import ParsedFile

# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def normalize_cross_lang_name(name: str) -> str:
    """Normalize a function/method name for cross-language comparison.

    Converts both camelCase and PascalCase to lower-snake-case so that
    Python ``get_user`` and JavaScript ``getUser`` map to the same bucket.

    Examples:
        >>> normalize_cross_lang_name("getUser")
        'get_user'
        >>> normalize_cross_lang_name("GetUser")
        'get_user'
        >>> normalize_cross_lang_name("get_user")
        'get_user'
        >>> normalize_cross_lang_name("HTTPClient")
        'h_t_t_p_client'
    """
    # Split camelCase / PascalCase
    parts = _CAMEL_SPLIT_RE.sub("_", name)
    # Lower and normalize
    return parts.lower().strip("_")


# ---------------------------------------------------------------------------
# Index builder
# ---------------------------------------------------------------------------

def build_cross_lang_name_index(
    parsed_files: list[ParsedFile],
) -> dict[str, dict[str, list[str]]]:
    """Build a cross-language name similarity index.

    Returns::

        {
            normalised_name: {
                "python": [fn_id, ...],
                "javascript": [fn_id, ...],
                "typescript": [fn_id, ...],
            }
        }

    Only exported functions are included (``is_exported=True``).  The index
    is language-partitioned so callers can filter by source/target language
    without iterating all candidates.
    """
    index: dict[str, dict[str, list[str]]] = {}

    for pf in parsed_files:
        if pf.file_record is None:
            continue
        lang = pf.file_record.language
        if lang not in ("python", "javascript", "typescript"):
            continue

        for fn in pf.functions:
            if not fn.is_exported:
                continue
            norm = normalize_cross_lang_name(fn.name)
            if not norm:
                continue
            lang_bucket = index.setdefault(norm, {})
            lang_bucket.setdefault(lang, []).append(fn.id)

    return index


def get_cross_lang_candidates(
    index: dict[str, dict[str, list[str]]],
    name: str,
    source_lang: str,
) -> dict[str, list[str]]:
    """Look up cross-language candidates for a given name.

    Returns a dict of {target_lang: [fn_id, ...]} excluding source_lang entries.
    Returns an empty dict when no candidates exist.
    """
    norm = normalize_cross_lang_name(name)
    bucket = index.get(norm, {})
    return {lang: ids for lang, ids in bucket.items() if lang != source_lang}
