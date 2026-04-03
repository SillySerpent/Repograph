"""Tests for F1 — framework adapter standard output schema (Block F1)."""
from __future__ import annotations

from pathlib import Path


def _make_file_record(path: str, language: str = "python"):
    from repograph.core.models import FileRecord
    return FileRecord(
        path=path,
        abs_path=path,
        name=Path(path).name,
        extension=Path(path).suffix,
        language=language,
        size_bytes=0,
        line_count=10,
        source_hash="test",
        is_test=False,
        is_config=False,
        mtime=0.0,
    )


def _make_fn(qualified_name: str, decorators: list[str],
             route_path: str = "", http_method: str = ""):
    from repograph.core.models import FunctionNode
    return FunctionNode(
        id=f"fn_{qualified_name}",
        name=qualified_name,
        qualified_name=qualified_name,
        file_path="app.py",
        line_start=1,
        line_end=5,
        signature=f"def {qualified_name}()",
        docstring=None,
        is_method=False,
        is_async=False,
        is_exported=True,
        decorators=decorators,
        param_names=[],
        return_type=None,
        source_hash="abc",
        route_path=route_path,
        http_method=http_method,
    )


def _make_parsed_file(path: str, functions, imports=None, language: str = "python"):
    from repograph.core.models import ParsedFile
    pf = ParsedFile(file_record=_make_file_record(path, language=language))
    pf.functions = list(functions)
    if imports:
        pf.imports = imports
    return pf


def _run_framework_parse(repo_root: Path):
    from repograph.graph_store.store import GraphStore
    from repograph.parsing.symbol_table import SymbolTable
    from repograph.pipeline.phases import p01_walk, p03_parse, p03b_framework_tags

    rg_dir = repo_root / ".repograph"
    rg_dir.mkdir(exist_ok=True)
    store = GraphStore(str(rg_dir / "graph.db"))
    store.initialize_schema()
    files = p01_walk.run(str(repo_root))
    parsed = p03_parse.run(files, store, SymbolTable())
    p03b_framework_tags.run(parsed, store)
    return parsed, store


# ---------------------------------------------------------------------------
# Flask adapter standard schema
# ---------------------------------------------------------------------------


def test_flask_adapter_returns_standard_schema_keys():
    """Flask adapter must return route_functions as list[dict] with standard keys."""
    from repograph.plugins.framework_adapters.flask.plugin import FlaskFrameworkAdapterPlugin

    adapter = FlaskFrameworkAdapterPlugin()
    fr = _make_file_record("views.py")
    fn = _make_fn("list_users", decorators=["app.route"], route_path="/users")
    pf = _make_parsed_file("views.py", [fn])
    # Inject a flask import so detection triggers
    from repograph.core.models import ImportNode
    pf.imports = [ImportNode(id="i1", file_path="views.py", raw_statement="import flask",
                             module_path="flask", resolved_path=None, imported_names=[],
                             is_wildcard=False, line_number=1)]

    result = adapter.inspect(file_record=fr, parsed_file=pf)

    assert "route_functions" in result
    assert "page_components" in result
    assert "server_actions" in result
    assert isinstance(result["route_functions"], list)
    for entry in result["route_functions"]:
        assert isinstance(entry, dict)
        assert "qualified_name" in entry
        assert "http_method" in entry
        assert "route_path" in entry


def test_flask_adapter_route_function_carries_route_path():
    """Flask adapter route_functions must include route_path from FunctionNode."""
    from repograph.plugins.framework_adapters.flask.plugin import FlaskFrameworkAdapterPlugin
    from repograph.core.models import ImportNode

    adapter = FlaskFrameworkAdapterPlugin()
    fr = _make_file_record("routes.py")
    fn = _make_fn("create_user", decorators=["app.route"], route_path="/users", http_method="")
    pf = _make_parsed_file("routes.py", [fn])
    pf.imports = [ImportNode(id="i1", file_path="routes.py", raw_statement="import flask",
                             module_path="flask", resolved_path=None, imported_names=[],
                             is_wildcard=False, line_number=1)]

    result = adapter.inspect(file_record=fr, parsed_file=pf)
    rf = result["route_functions"]
    assert len(rf) == 1
    assert rf[0]["qualified_name"] == "create_user"
    assert rf[0]["route_path"] == "/users"


# ---------------------------------------------------------------------------
# FastAPI adapter standard schema
# ---------------------------------------------------------------------------


def test_fastapi_adapter_returns_standard_schema_keys():
    """FastAPI adapter must return route_functions as list[dict] with standard keys."""
    from repograph.plugins.framework_adapters.fastapi.plugin import FastAPIFrameworkAdapterPlugin
    from repograph.core.models import ImportNode

    adapter = FastAPIFrameworkAdapterPlugin()
    fr = _make_file_record("endpoints.py")
    fn = _make_fn("list_users", decorators=["router.get"], http_method="GET", route_path="/users")
    pf = _make_parsed_file("endpoints.py", [fn])
    pf.imports = [ImportNode(id="i1", file_path="endpoints.py", raw_statement="import fastapi",
                             module_path="fastapi", resolved_path=None, imported_names=[],
                             is_wildcard=False, line_number=1)]

    result = adapter.inspect(file_record=fr, parsed_file=pf)
    assert "route_functions" in result
    assert "page_components" in result
    assert "server_actions" in result
    for entry in result["route_functions"]:
        assert isinstance(entry, dict)
        assert "qualified_name" in entry
        assert "http_method" in entry
        assert "route_path" in entry


def test_fastapi_adapter_http_method_populated():
    """FastAPI adapter must populate http_method from decorator suffix OR FunctionNode."""
    from repograph.plugins.framework_adapters.fastapi.plugin import FastAPIFrameworkAdapterPlugin
    from repograph.core.models import ImportNode

    adapter = FastAPIFrameworkAdapterPlugin()
    fr = _make_file_record("api.py")
    fn = _make_fn("create_item", decorators=["router.post"], http_method="POST", route_path="/items")
    pf = _make_parsed_file("api.py", [fn])
    pf.imports = [ImportNode(id="i1", file_path="api.py", raw_statement="import fastapi",
                             module_path="fastapi", resolved_path=None, imported_names=[],
                             is_wildcard=False, line_number=1)]

    result = adapter.inspect(file_record=fr, parsed_file=pf)
    assert result["route_functions"][0]["http_method"] == "POST"


# ---------------------------------------------------------------------------
# Next.js adapter standard schema
# ---------------------------------------------------------------------------


def test_nextjs_adapter_returns_standard_schema_keys():
    """Next.js adapter must return route_functions list[dict] with standard keys."""
    from repograph.plugins.framework_adapters.nextjs.plugin import NextJsFrameworkAdapterPlugin

    adapter = NextJsFrameworkAdapterPlugin()
    fr = _make_file_record("app/users/route.ts", language="typescript")
    pf = _make_parsed_file("app/users/route.ts", [], language="typescript")

    result = adapter.inspect(
        file_record=fr,
        parsed_file=pf,
        text="export async function GET(request) { return Response.json({}); }",
    )

    assert "route_functions" in result
    assert "page_components" in result
    assert "server_actions" in result
    for entry in result["route_functions"]:
        assert isinstance(entry, dict)
        assert "qualified_name" in entry
        assert "http_method" in entry
        assert "route_path" in entry


def test_nextjs_adapter_route_path_inferred_from_file_path():
    """Next.js adapter must infer route_path from the app router file path."""
    from repograph.plugins.framework_adapters.nextjs.plugin import NextJsFrameworkAdapterPlugin

    adapter = NextJsFrameworkAdapterPlugin()
    fr = _make_file_record("app/users/route.ts", language="typescript")
    pf = _make_parsed_file("app/users/route.ts", [], language="typescript")

    result = adapter.inspect(
        file_record=fr,
        parsed_file=pf,
        text="export async function POST(request) { }",
    )

    assert result["route_functions"][0]["route_path"] == "/users"
    assert result["route_functions"][0]["http_method"] == "POST"


def test_nextjs_adapter_non_route_file_returns_empty():
    """Next.js adapter must return {} for non-Next.js files."""
    from repograph.plugins.framework_adapters.nextjs.plugin import NextJsFrameworkAdapterPlugin

    adapter = NextJsFrameworkAdapterPlugin()
    fr = _make_file_record("utils/helper.ts", language="typescript")
    pf = _make_parsed_file("utils/helper.ts", [], language="typescript")

    result = adapter.inspect(
        file_record=fr,
        parsed_file=pf,
        text="function helper(x) { return x; }",
    )

    assert result == {}


def test_nextjs_route_live_parse_populates_route_metadata(tmp_path):
    repo = tmp_path / "repo"
    route_dir = repo / "app" / "users"
    route_dir.mkdir(parents=True)
    (route_dir / "route.ts").write_text(
        "export async function POST(request: Request) {\n"
        "  return Response.json({ ok: true });\n"
        "}\n",
        encoding="utf-8",
    )

    parsed, store = _run_framework_parse(repo)
    try:
        pf = next(p for p in parsed if p.file_record.path == "app/users/route.ts")
        artifact = pf.plugin_artifacts["framework.nextjs"]
        assert artifact["route_functions"][0]["http_method"] == "POST"
        assert artifact["route_functions"][0]["route_path"] == "/users"

        rows = store.query(
            "MATCH (f:Function {qualified_name: $qn, file_path: $fp}) "
            "RETURN f.layer, f.role, f.http_method, f.route_path",
            {"qn": "POST", "fp": "app/users/route.ts"},
        )
        assert rows
        assert rows[0][0] == "api"
        assert rows[0][1] == "handler"
        assert rows[0][2] == "POST"
        assert rows[0][3] == "/users"
    finally:
        store.close()


def test_react_and_nextjs_live_parse_populates_component_hints_and_ui_layer(tmp_path):
    repo = tmp_path / "repo"
    page_dir = repo / "app"
    page_dir.mkdir(parents=True)
    (page_dir / "page.tsx").write_text(
        '"use client";\n'
        'import { useState } from "react";\n'
        "export default function HomePage() {\n"
        "  const [count, setCount] = useState(0);\n"
        "  return <button onClick={() => setCount(count + 1)}>{count}</button>;\n"
        "}\n"
        "function useCounterThing() {\n"
        "  return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    parsed, store = _run_framework_parse(repo)
    try:
        pf = next(p for p in parsed if p.file_record.path == "app/page.tsx")
        react_artifact = pf.plugin_artifacts["framework.react"]
        next_artifact = pf.plugin_artifacts["framework.nextjs"]

        assert "HomePage" in react_artifact["component_names"]
        assert "useCounterThing" in react_artifact["hook_names"]
        assert react_artifact["client_component"] is True
        assert next_artifact["page_components"] == ["app/page.tsx"]

        rows = store.query(
            "MATCH (f:File {path: $path}) RETURN f.layer",
            {"path": "app/page.tsx"},
        )
        assert rows and rows[0][0] == "ui"
    finally:
        store.close()
