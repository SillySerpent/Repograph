"""Tests for F3+F4 — HTTP call detection and MAKES_HTTP_CALL edge creation (p05c)."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# normalize_route_path and routes_match
# ---------------------------------------------------------------------------


def test_normalize_route_path_strips_scheme():
    from repograph.pipeline.phases.p05c_http_calls import normalize_route_path
    assert normalize_route_path("http://localhost:8000/api/users") == "/api/users"
    assert normalize_route_path("https://api.example.com/v1/items") == "/v1/items"


def test_normalize_route_path_strips_trailing_slash():
    from repograph.pipeline.phases.p05c_http_calls import normalize_route_path
    assert normalize_route_path("/api/users/") == "/api/users"


def test_normalize_route_path_keeps_root_slash():
    from repograph.pipeline.phases.p05c_http_calls import normalize_route_path
    assert normalize_route_path("/") == "/"


def test_normalize_route_path_normalizes_params():
    from repograph.pipeline.phases.p05c_http_calls import normalize_route_path
    assert normalize_route_path("/api/users/:id") == "/api/users/{*}"
    assert normalize_route_path("/api/users/{user_id}") == "/api/users/{*}"
    assert normalize_route_path("/api/users/<int:user_id>") == "/api/users/{*}"


def test_routes_match_exact():
    from repograph.pipeline.phases.p05c_http_calls import routes_match
    assert routes_match("/api/users", "/api/users") is True


def test_routes_match_param_normalization():
    from repograph.pipeline.phases.p05c_http_calls import routes_match
    # Caller passes /api/users/123, handler defines /api/users/:id
    assert routes_match("/api/users/123", "/api/users/:id") is False
    # Same pattern — both normalise to same form
    assert routes_match("/api/users/:id", "/api/users/{user_id}") is True


def test_routes_match_trailing_slash_insensitive():
    from repograph.pipeline.phases.p05c_http_calls import routes_match
    assert routes_match("/api/users/", "/api/users") is True


def test_routes_no_match_different_paths():
    from repograph.pipeline.phases.p05c_http_calls import routes_match
    assert routes_match("/api/users", "/api/posts") is False


def test_routes_match_empty_returns_false():
    from repograph.pipeline.phases.p05c_http_calls import routes_match
    assert routes_match("", "/api/users") is False
    assert routes_match("/api/users", "") is False


# ---------------------------------------------------------------------------
# _build_call_index — in-memory scan of parsed call sites
# ---------------------------------------------------------------------------


def _make_file_record(path: str = "caller.py"):
    from repograph.core.models import FileRecord
    from pathlib import Path
    return FileRecord(
        path=path, abs_path=path, name=Path(path).name,
        extension=Path(path).suffix, language="python",
        size_bytes=0, line_count=10, source_hash="x",
        is_test=False, is_config=False, mtime=0.0,
    )


def _make_parsed_file_with_callsite(
    caller_fn_id: str,
    callee_text: str,
    *,
    argument_exprs=None,
    keyword_args=None,
    line: int = 5,
):
    from repograph.core.models import ParsedFile, CallSite
    pf = ParsedFile(file_record=_make_file_record())
    pf.call_sites = [
        CallSite(
            caller_function_id=caller_fn_id,
            callee_text=callee_text,
            call_site_line=line,
            argument_exprs=list(argument_exprs or []),
            keyword_args=dict(keyword_args or {}),
            file_path="caller.py",
        )
    ]
    return pf


def test_build_call_index_detects_requests_post():
    from repograph.pipeline.phases.p05c_http_calls import _build_call_index
    pf = _make_parsed_file_with_callsite(
        "fn::caller",
        "requests.post",
        argument_exprs=['"/api/users"'],
    )
    idx = _build_call_index([pf])
    assert ("POST", "/api/users") in idx
    assert idx[("POST", "/api/users")][0][0] == "fn::caller"


def test_build_call_index_detects_requests_get():
    from repograph.pipeline.phases.p05c_http_calls import _build_call_index
    pf = _make_parsed_file_with_callsite(
        "fn::caller",
        "requests.get",
        argument_exprs=['"/health"'],
    )
    idx = _build_call_index([pf])
    assert ("GET", "/health") in idx


def test_build_call_index_detects_keyword_url_argument():
    from repograph.pipeline.phases.p05c_http_calls import _build_call_index
    pf = _make_parsed_file_with_callsite(
        "fn::caller",
        "httpx.post",
        keyword_args={"url": '"/api/orders"'},
    )
    idx = _build_call_index([pf])
    assert ("POST", "/api/orders") in idx


def test_build_call_index_ignores_non_http_callee():
    from repograph.pipeline.phases.p05c_http_calls import _build_call_index
    pf = _make_parsed_file_with_callsite("fn::caller", 'some_function("/path")')
    idx = _build_call_index([pf])
    assert len(idx) == 0


def test_build_call_index_no_url_string_skipped():
    from repograph.pipeline.phases.p05c_http_calls import _build_call_index
    # callee has no string literal — skip this call site
    pf = _make_parsed_file_with_callsite("fn::caller", "requests.get")
    idx = _build_call_index([pf])
    assert len(idx) == 0


# ---------------------------------------------------------------------------
# Integration: run() produces MAKES_HTTP_CALL edges
# ---------------------------------------------------------------------------


def test_run_creates_makes_http_call_edge(tmp_path):
    """Real parser output must produce a MAKES_HTTP_CALL edge when caller URL matches handler route."""
    from repograph.graph_store.store import GraphStore
    from repograph.parsing.symbol_table import SymbolTable
    from repograph.pipeline.phases import p05c_http_calls
    from repograph.pipeline.phases import p01_walk, p03_parse, p03b_framework_tags

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "api.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.post('/api/users')\n"
        "def create_user():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (repo / "client.py").write_text(
        "import requests\n\n"
        "def do_create():\n"
        "    return requests.post('/api/users')\n",
        encoding="utf-8",
    )

    rg_dir = repo / ".repograph"
    rg_dir.mkdir()
    db = str(rg_dir / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    try:
        files = p01_walk.run(str(repo))
        parsed = p03_parse.run(files, store, SymbolTable())
        p03b_framework_tags.run(parsed, store)

        count = p05c_http_calls.run(parsed, store)
        assert count == 1

        rows = store.query(
            "MATCH (a:Function {qualified_name: 'do_create'})-[r:MAKES_HTTP_CALL]->"
            "(b:Function {qualified_name: 'create_user'}) "
            "RETURN r.http_method, r.url_pattern"
        )
        assert rows and rows[0][0] == "POST"
        assert rows[0][1] == "/api/users"
    finally:
        store.close()


def test_run_no_edges_when_no_route_handlers(tmp_path):
    """p05c.run() must create zero edges when no route handlers exist in the graph."""
    from repograph.graph_store.store import GraphStore
    from repograph.core.models import ParsedFile, CallSite
    from repograph.pipeline.phases import p05c_http_calls

    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()

    pf = ParsedFile(file_record=None)  # type: ignore[arg-type]
    pf.call_sites = [
        CallSite(
            caller_function_id="fn::caller",
            callee_text='requests.post("/api/users")',
            call_site_line=5,
            argument_exprs=[], keyword_args={},
            file_path="client.py",
        )
    ]

    count = p05c_http_calls.run([pf], store)
    assert count == 0
    store.close()
