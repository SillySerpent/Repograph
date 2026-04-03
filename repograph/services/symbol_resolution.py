"""Shared symbol-resolution helpers for service and CLI surfaces."""
from __future__ import annotations

from typing import Any


def _function_rows_to_matches(rows: list[tuple]) -> list[dict[str, Any]]:
    return [
        {
            "id": row[0],
            "name": row[1],
            "qualified_name": row[2],
            "file_path": row[3],
            "signature": row[4],
        }
        for row in rows
    ]


def _query_exact_qualified(store, identifier: str, *, limit: int) -> list[dict[str, Any]]:
    rows = store.query(
        """
        MATCH (f:Function)
        WHERE f.qualified_name = $identifier
        RETURN f.id, f.name, f.qualified_name, f.file_path, f.signature
        ORDER BY f.qualified_name
        LIMIT $limit
        """,
        {"identifier": identifier, "limit": limit},
    )
    return _function_rows_to_matches(rows)


def _query_exact_name(store, identifier: str, *, limit: int) -> list[dict[str, Any]]:
    rows = store.query(
        """
        MATCH (f:Function)
        WHERE f.name = $identifier
        RETURN f.id, f.name, f.qualified_name, f.file_path, f.signature
        ORDER BY f.qualified_name
        LIMIT $limit
        """,
        {"identifier": identifier, "limit": limit},
    )
    return _function_rows_to_matches(rows)


def _normalized_symbol_candidates(identifier: str) -> list[str]:
    base = (identifier or "").strip()
    candidates: list[str] = []
    if not base:
        return candidates

    def _add(candidate: str) -> None:
        cleaned = candidate.strip()
        if cleaned and cleaned != base and cleaned not in candidates:
            candidates.append(cleaned)

    if base.endswith("()"):
        _add(base[:-2])
    if "::" in base:
        _add(base.replace("::", "."))
    if "#" in base:
        _add(base.replace("#", "."))
    if ":" in base and "/" not in base:
        _add(base.replace(":", "."))
    return candidates


def resolve_identifier(store, identifier: str, *, limit: int = 5) -> dict[str, Any]:
    """Resolve a user-facing identifier to a file or function deterministically.

    Resolution order:
      1. exact file path
      2. exact qualified function name
      3. exact simple function name
      4. exact qualified name after light normalization
      5. fuzzy fallback via ``search_functions_by_name``
    """
    lookup = (identifier or "").strip()
    if not lookup:
        return {
            "kind": "not_found",
            "identifier": identifier,
            "strategy": "empty_identifier",
            "matches": [],
        }

    file_data = store.get_file(lookup)
    if file_data:
        return {
            "kind": "file",
            "identifier": identifier,
            "strategy": "exact_file",
            "match": file_data,
            "matches": [file_data],
        }

    exact_qualified = _query_exact_qualified(store, lookup, limit=limit)
    if len(exact_qualified) == 1:
        return {
            "kind": "function",
            "identifier": identifier,
            "strategy": "exact_qualified_name",
            "match": exact_qualified[0],
            "matches": exact_qualified,
        }
    if len(exact_qualified) > 1:
        return {
            "kind": "ambiguous",
            "identifier": identifier,
            "strategy": "exact_qualified_name",
            "matches": exact_qualified,
        }

    exact_name = _query_exact_name(store, lookup, limit=limit)
    if len(exact_name) == 1:
        return {
            "kind": "function",
            "identifier": identifier,
            "strategy": "exact_simple_name",
            "match": exact_name[0],
            "matches": exact_name,
        }
    if len(exact_name) > 1:
        return {
            "kind": "ambiguous",
            "identifier": identifier,
            "strategy": "exact_simple_name",
            "matches": exact_name,
        }

    for candidate in _normalized_symbol_candidates(lookup):
        normalized = _query_exact_qualified(store, candidate, limit=limit)
        if len(normalized) == 1:
            return {
                "kind": "function",
                "identifier": identifier,
                "strategy": "normalized_qualified_name",
                "normalized_from": lookup,
                "normalized_to": candidate,
                "match": normalized[0],
                "matches": normalized,
            }
        if len(normalized) > 1:
            return {
                "kind": "ambiguous",
                "identifier": identifier,
                "strategy": "normalized_qualified_name",
                "normalized_from": lookup,
                "normalized_to": candidate,
                "matches": normalized,
            }

    fuzzy = store.search_functions_by_name(lookup, limit=limit)
    if len(fuzzy) == 1:
        return {
            "kind": "function",
            "identifier": identifier,
            "strategy": "fuzzy_name_search",
            "match": fuzzy[0],
            "matches": fuzzy,
        }
    if len(fuzzy) > 1:
        return {
            "kind": "ambiguous",
            "identifier": identifier,
            "strategy": "fuzzy_name_search",
            "matches": fuzzy,
        }

    return {
        "kind": "not_found",
        "identifier": identifier,
        "strategy": "not_found",
        "matches": [],
    }
