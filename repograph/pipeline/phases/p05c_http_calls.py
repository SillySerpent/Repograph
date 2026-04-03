"""Phase 5c — HTTP Call Detection: create MAKES_HTTP_CALL edges between Python
HTTP client call sites and their matching server-side route handlers.

This phase runs after p05 (CALLS edges) because it depends on:
  - Route metadata written by p03b_framework_tags (layer/role/http_method/route_path)
  - FunctionNode.http_method / route_path populated by F2 (python_parser)

Algorithm (sub-quadratic hash join):
1. Build a ``route_index`` from the store: (http_method, normalised_route_path) → function_id
   (single DB query — all functions where http_method != '')
2. Build a ``call_index`` during parsing: scan every parsed file's call sites for
   HTTP client patterns; extract (http_method, url_pattern) → [(caller_fn_id, line)]
   (no DB queries — purely in-memory from parsed data)
3. Hash-join the two indexes; for each match, insert a MAKES_HTTP_CALL edge.
"""
from __future__ import annotations

import re
from collections import defaultdict

from repograph.core.models import ParsedFile
from repograph.graph_store.store import GraphStore
from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="pipeline")

# ---------------------------------------------------------------------------
# HTTP client call patterns (single source of truth)
# ---------------------------------------------------------------------------

# Maps callee_text prefix (as it appears in call sites) to HTTP method.
# Keys are matched with startswith / exact match against the callee_text.
_HTTP_CLIENT_PATTERNS: list[tuple[str, str]] = [
    ("requests.get", "GET"),
    ("requests.post", "POST"),
    ("requests.put", "PUT"),
    ("requests.patch", "PATCH"),
    ("requests.delete", "DELETE"),
    ("requests.request", ""),    # method in first arg — skip for now
    ("httpx.get", "GET"),
    ("httpx.post", "POST"),
    ("httpx.put", "PUT"),
    ("httpx.patch", "PATCH"),
    ("httpx.delete", "DELETE"),
    ("aiohttp.get", "GET"),      # aiohttp.ClientSession().get (simplified)
    ("aiohttp.post", "POST"),
    ("session.get", "GET"),
    ("session.post", "POST"),
    ("session.put", "PUT"),
    ("session.patch", "PATCH"),
    ("session.delete", "DELETE"),
    ("client.get", "GET"),
    ("client.post", "POST"),
    ("client.put", "PUT"),
    ("client.patch", "PATCH"),
    ("client.delete", "DELETE"),
    ("urllib.request.urlopen", "GET"),
]

# Regex to extract the first string-literal argument from legacy call-site text.
# Handles single/double/triple quoted strings.
_FIRST_STRING_ARG_RE = re.compile(
    r"""(?:^[^(]*\()\s*(?:f?['"]{3}(.*?)['"]{3}|f?['"]([^'"]+)['"])""",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Route path normalisation
# ---------------------------------------------------------------------------

# Strip URL scheme, host, and port from a URL; keep the path portion.
_URL_SCHEME_RE = re.compile(r"^(?:https?://[^/]+)?(/.*)?$")
# Replace path parameters (:id, {id}, <int:id>, etc.) with a normalised form.
_PATH_PARAM_RE = re.compile(r"(?:<[^>]+>|:[a-zA-Z_][a-zA-Z0-9_]*|\{[^}]+\})")


def normalize_route_path(path: str) -> str:
    """Normalize a URL or route path for matching.

    Strips scheme/host, normalises path parameters to ``{*}``, and
    removes trailing slashes (except root ``/``).
    """
    if not path:
        return ""
    # Strip scheme + host if present (e.g., http://localhost:8000/api/users)
    m = _URL_SCHEME_RE.match(path)
    if m:
        path = m.group(1) or path
    # Normalise path parameters
    path = _PATH_PARAM_RE.sub("{*}", path)
    # Remove trailing slash (keep root /)
    if len(path) > 1:
        path = path.rstrip("/")
    return path.lower()


def routes_match(caller_path: str, handler_path: str) -> bool:
    """Return True if a call-site URL matches a handler route path."""
    if not caller_path or not handler_path:
        return False
    return normalize_route_path(caller_path) == normalize_route_path(handler_path)


# ---------------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------------

def _build_route_index(store: GraphStore) -> dict[tuple[str, str], list[str]]:
    """Build (http_method, normalised_route) → [fn_id] from the graph store.

    Single DB query: only functions with a non-empty http_method are route handlers.
    """
    rows = store.query(
        "MATCH (f:Function) WHERE f.http_method <> '' "
        "RETURN f.id, f.http_method, f.route_path"
    )
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in rows:
        fn_id, http_method, route_path = r[0], r[1] or "", r[2] or ""
        if fn_id and http_method:
            key = (http_method.upper(), normalize_route_path(route_path))
            index[key].append(fn_id)
    return dict(index)


def _build_call_index(
    parsed_files: list[ParsedFile],
) -> dict[tuple[str, str], list[tuple[str, int]]]:
    """Build (http_method, raw_url) → [(caller_fn_id, line)] from parsed call sites.

    Scans CallSite objects for HTTP client patterns; uses ``argument_exprs`` and
    ``keyword_args`` as the primary source of URL literals, with a legacy
    ``callee_text`` fallback for older synthetic test shapes. No DB queries.
    """
    index: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for pf in parsed_files:
        for cs in pf.call_sites:
            callee = cs.callee_text or ""
            http_method = ""
            for pattern, method in _HTTP_CLIENT_PATTERNS:
                if callee == pattern or callee.startswith(pattern + "(") or callee.startswith(pattern + " "):
                    http_method = method
                    break
            if not http_method:
                continue
            url = _extract_url_from_call_site(cs)
            if not url:
                continue
            # caller_function_id is the resolved function id from the parser.
            caller_id = cs.caller_function_id or _find_fn_by_line(pf, cs.call_site_line)
            if caller_id:
                index[(http_method, url)].append((caller_id, cs.call_site_line))
    return dict(index)


def _extract_url_from_call_site(call_site) -> str:
    """Extract a URL literal from a parsed HTTP client call.

    Real parsers store the callee expression separately from positional and
    keyword arguments. Prefer those argument fields and only fall back to
    ``callee_text`` for older synthetic fixtures.
    """
    for expr in call_site.argument_exprs or []:
        literal = _extract_string_literal(expr)
        if literal:
            return literal

    for key in ("url", "path", "endpoint", "uri"):
        literal = _extract_string_literal((call_site.keyword_args or {}).get(key, ""))
        if literal:
            return literal

    return _extract_first_string_from_callee(call_site.callee_text or "")


def _extract_string_literal(expr: str) -> str:
    expr = (expr or "").strip()
    if not expr:
        return ""

    prefixes = ("rf", "fr", "rb", "br", "ur", "ru", "r", "f", "u", "b")
    lowered = expr.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix) and len(expr) > len(prefix):
            expr = expr[len(prefix):]
            break

    for quote in ('"""', "'''", '"', "'"):
        if expr.startswith(quote) and expr.endswith(quote) and len(expr) >= len(quote) * 2:
            return expr[len(quote):-len(quote)]
    return ""


def _extract_first_string_from_callee(callee_text: str) -> str:
    """Extract the first string literal argument embedded in a callee_text.

    This supports older synthetic call-site fixtures where the full call text was
    embedded in ``callee_text``. Real parser output usually leaves ``callee_text``
    as just the callee expression (for example ``requests.get``).
    """
    m = _FIRST_STRING_ARG_RE.search(callee_text)
    if m:
        return m.group(1) or m.group(2) or ""
    return ""


def _find_fn_by_line(pf: ParsedFile, line: int) -> str | None:
    """Return the id of the function that contains the given line number."""
    for fn in pf.functions:
        if fn.line_start <= line <= fn.line_end:
            return fn.id
    return None


# ---------------------------------------------------------------------------
# Phase entry point
# ---------------------------------------------------------------------------

def run(parsed_files: list[ParsedFile], store: GraphStore) -> int:
    """Detect HTTP call sites and create MAKES_HTTP_CALL edges.

    Returns the number of edges created.
    """
    route_index = _build_route_index(store)
    if not route_index:
        _logger.debug("p05c: no route handlers found in graph — skipping HTTP edge creation")
        return 0

    call_index = _build_call_index(parsed_files)
    if not call_index:
        _logger.debug("p05c: no HTTP call sites detected in parsed files")
        return 0

    edges_created = 0
    for (caller_method, raw_url), callers in call_index.items():
        norm_url = normalize_route_path(raw_url)
        for (handler_method, handler_norm_path), handler_ids in route_index.items():
            if caller_method != handler_method:
                continue
            if norm_url != handler_norm_path:
                continue
            for caller_id, _call_line in callers:
                for handler_id in handler_ids:
                    store.insert_makes_http_call_edge(
                        from_id=caller_id,
                        to_id=handler_id,
                        http_method=caller_method,
                        url_pattern=raw_url,
                        confidence=0.85,
                        reason="http_endpoint_match",
                    )
                    edges_created += 1

    _logger.debug(
        "p05c: created MAKES_HTTP_CALL edges",
        count=edges_created,
        routes=len(route_index),
        call_sites=len(call_index),
    )
    return edges_created
