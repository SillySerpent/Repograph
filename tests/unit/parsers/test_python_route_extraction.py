"""Tests for F2 — route path extraction from Python decorators (Block F2)."""
from __future__ import annotations

from pathlib import Path


def _make_file_record(path: str = "app.py", is_test: bool = False):
    from repograph.core.models import FileRecord
    return FileRecord(
        path=path,
        abs_path=path,
        name=Path(path).name,
        extension=".py",
        language="python",
        size_bytes=0,
        line_count=10,
        source_hash="test",
        is_test=is_test,
        is_config=False,
        mtime=0.0,
    )


def _parse_functions(source: str, path: str = "app.py"):
    """Parse source with PythonParser and return list of FunctionNodes."""
    from repograph.plugins.parsers.python.python_parser import PythonParser

    parser = PythonParser()
    fr = _make_file_record(path)
    pf = parser.parse(source.encode(), fr)
    return pf.functions


# ---------------------------------------------------------------------------
# Flask route extraction
# ---------------------------------------------------------------------------


def test_flask_route_path_extracted():
    """Flask @app.route('/users') must set route_path='/users' on FunctionNode."""
    source = """
from flask import Flask
app = Flask(__name__)

@app.route('/users')
def list_users():
    return []
"""
    fns = _parse_functions(source)
    fn = next((f for f in fns if f.name == "list_users"), None)
    assert fn is not None, "list_users function not found"
    assert fn.route_path == "/users"


def test_flask_route_http_method_empty_for_plain_route():
    """Flask @app.route does not have an intrinsic HTTP method — http_method stays empty."""
    source = """
@app.route('/items')
def list_items():
    pass
"""
    fns = _parse_functions(source)
    fn = next((f for f in fns if f.name == "list_items"), None)
    assert fn is not None
    assert fn.http_method == ""


# ---------------------------------------------------------------------------
# FastAPI route extraction
# ---------------------------------------------------------------------------


def test_fastapi_get_route_extracted():
    """FastAPI @router.get('/users') must set route_path='/users', http_method='GET'."""
    source = """
from fastapi import APIRouter
router = APIRouter()

@router.get('/users')
async def list_users():
    return []
"""
    fns = _parse_functions(source)
    fn = next((f for f in fns if f.name == "list_users"), None)
    assert fn is not None, "list_users function not found"
    assert fn.route_path == "/users"
    assert fn.http_method == "GET"


def test_fastapi_post_route_extracted():
    """FastAPI @router.post('/users') must set http_method='POST'."""
    source = """
@router.post('/users')
async def create_user(body: dict):
    pass
"""
    fns = _parse_functions(source)
    fn = next((f for f in fns if f.name == "create_user"), None)
    assert fn is not None
    assert fn.http_method == "POST"
    assert fn.route_path == "/users"


def test_fastapi_delete_route_extracted():
    """@router.delete must set http_method='DELETE'."""
    source = """
@app.delete('/users/{user_id}')
async def delete_user(user_id: int):
    pass
"""
    fns = _parse_functions(source)
    fn = next((f for f in fns if f.name == "delete_user"), None)
    assert fn is not None
    assert fn.http_method == "DELETE"
    assert fn.route_path == "/users/{user_id}"


# ---------------------------------------------------------------------------
# Non-route functions
# ---------------------------------------------------------------------------


def test_regular_function_no_route_fields():
    """A function with no route decorator must have empty route_path and http_method."""
    source = """
def compute(x, y):
    return x + y
"""
    fns = _parse_functions(source)
    fn = next((f for f in fns if f.name == "compute"), None)
    assert fn is not None
    assert fn.route_path == ""
    assert fn.http_method == ""


def test_non_route_decorator_no_route_fields():
    """A function with a non-route decorator must not have route fields set."""
    source = """
@login_required
def profile(request):
    pass
"""
    fns = _parse_functions(source)
    fn = next((f for f in fns if f.name == "profile"), None)
    assert fn is not None
    assert fn.route_path == ""
    assert fn.http_method == ""


# ---------------------------------------------------------------------------
# Decorator name extraction (fix: decorator text without arguments)
# ---------------------------------------------------------------------------


def test_decorator_name_stripped_of_arguments():
    """Decorator names must not include call arguments (e.g., 'app.route' not 'app.route("/x")')."""
    source = """
@app.route('/x')
def handler():
    pass
"""
    fns = _parse_functions(source)
    fn = next((f for f in fns if f.name == "handler"), None)
    assert fn is not None
    # The decorator list should contain the name only, not the arguments
    assert any(d == "app.route" for d in fn.decorators), f"decorators={fn.decorators}"


def test_fastapi_decorator_name_in_decorator_list():
    """@router.get decorator list entry must be 'router.get', not 'router.get(\"/path\")'."""
    source = """
@router.get('/items')
def get_items():
    pass
"""
    fns = _parse_functions(source)
    fn = next((f for f in fns if f.name == "get_items"), None)
    assert fn is not None
    assert any(d == "router.get" for d in fn.decorators), f"decorators={fn.decorators}"
