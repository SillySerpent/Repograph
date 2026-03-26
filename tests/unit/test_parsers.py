"""Unit tests for the Python parser."""
from __future__ import annotations

import pytest
from repograph.plugins.parsers.python.python_parser import PythonParser
from repograph.core.models import FileRecord


def _make_record(path: str = "test.py", content: str = "") -> FileRecord:
    from repograph.utils.hashing import hash_file_content
    content_bytes = content.encode()
    return FileRecord(
        path=path, abs_path=f"/repo/{path}", name=path.split("/")[-1],
        extension=".py", language="python",
        size_bytes=len(content_bytes), line_count=content_bytes.count(b"\n") + 1,
        source_hash=hash_file_content(content_bytes),
        is_test=False, is_config=False, mtime=0.0,
    )


@pytest.fixture
def parser():
    return PythonParser()


class TestFunctionExtraction:
    def test_simple_function(self, parser):
        src = b"def foo(x, y):\n    return x + y\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assert len(pf.functions) == 1
        fn = pf.functions[0]
        assert fn.name == "foo"
        assert fn.param_names == ["x", "y"]
        assert fn.is_async is False
        assert fn.is_method is False

    def test_async_function(self, parser):
        src = b"async def bar(request):\n    pass\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assert pf.functions[0].is_async is True

    def test_typed_function(self, parser):
        src = b"def greet(name: str, count: int = 1) -> str:\n    return name * count\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        fn = pf.functions[0]
        assert fn.return_type == "str"
        assert "name" in fn.param_names
        assert "count" in fn.param_names

    def test_method_in_class(self, parser):
        src = b"class Foo:\n    def bar(self, x):\n        pass\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        fn = pf.functions[0]
        assert fn.name == "bar"
        assert fn.is_method is True
        assert fn.qualified_name == "Foo.bar"
        assert "x" in fn.param_names
        assert "self" not in fn.param_names

    def test_decorated_function(self, parser):
        src = b"@app.route('/login', methods=['POST'])\ndef login():\n    pass\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        fn = pf.functions[0]
        assert fn.name == "login"
        assert len(fn.decorators) >= 1
        assert any("app.route" in d for d in fn.decorators)

    def test_docstring_extraction(self, parser):
        src = b'def documented():\n    """This is a docstring."""\n    pass\n'
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assert pf.functions[0].docstring == "This is a docstring."

    def test_nested_function(self, parser):
        src = b"def outer(x):\n    def inner(y):\n        return y\n    return inner(x)\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        names = {fn.name for fn in pf.functions}
        assert "outer" in names
        assert "inner" in names

    def test_line_spans(self, parser):
        src = b"def foo():\n    x = 1\n    y = 2\n    return x + y\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        fn = pf.functions[0]
        assert fn.line_start == 1
        assert fn.line_end >= 4


class TestClassExtraction:
    def test_simple_class(self, parser):
        src = b"class Foo:\n    pass\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assert len(pf.classes) == 1
        assert pf.classes[0].name == "Foo"

    def test_class_with_bases(self, parser):
        src = b"class Bar(Foo, Mixin):\n    pass\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        cls = pf.classes[0]
        assert "Foo" in cls.base_names
        assert "Mixin" in cls.base_names

    def test_class_docstring(self, parser):
        src = b'class Thing:\n    """A thing."""\n    pass\n'
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assert pf.classes[0].docstring == "A thing."


class TestImportExtraction:
    def test_import_statement(self, parser):
        src = b"import os\nimport sys\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        mods = [i.module_path for i in pf.imports]
        assert "os" in mods
        assert "sys" in mods

    def test_from_import(self, parser):
        src = b"from pathlib import Path\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assert len(pf.imports) == 1
        imp = pf.imports[0]
        assert imp.module_path == "pathlib"
        assert "Path" in imp.imported_names

    def test_relative_import(self, parser):
        src = b"from .utils import helper\n"
        fr = _make_record(path="pkg/module.py", content=src.decode())
        pf = parser.parse(src, fr)
        assert pf.imports[0].module_path.startswith(".")

    def test_wildcard_import(self, parser):
        src = b"from os.path import *\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assert pf.imports[0].is_wildcard is True


class TestVariableExtraction:
    def test_parameter_extraction(self, parser):
        src = b"def foo(x, y):\n    pass\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        params = [v for v in pf.variables if v.is_parameter]
        assert len(params) == 2
        names = {p.name for p in params}
        assert "x" in names and "y" in names

    def test_typed_parameter(self, parser):
        src = b"def foo(x: int) -> None:\n    pass\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        params = [v for v in pf.variables if v.is_parameter]
        assert params[0].inferred_type == "int"

    def test_assignment_extraction(self, parser):
        src = b"def foo():\n    result = 42\n    return result\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assigns = [v for v in pf.variables if not v.is_parameter and not v.is_return]
        assert any(v.name == "result" for v in assigns)

    def test_return_tracking(self, parser):
        src = b"def foo():\n    return 42\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        returns = [v for v in pf.variables if v.is_return]
        assert len(returns) >= 1


class TestCallSiteExtraction:
    def test_simple_call(self, parser):
        src = b"def caller():\n    foo()\n\ndef foo():\n    pass\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assert any(site.callee_text == "foo" for site in pf.call_sites)

    def test_call_with_args(self, parser):
        src = b"def caller(x, y):\n    bar(x, y)\n\ndef bar(a, b):\n    pass\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        bar_calls = [s for s in pf.call_sites if s.callee_text == "bar"]
        assert len(bar_calls) >= 1
        assert "x" in bar_calls[0].argument_exprs

    def test_method_call(self, parser):
        src = b"def caller(obj):\n    obj.method()\n"
        fr = _make_record(content=src.decode())
        pf = parser.parse(src, fr)
        assert any("method" in site.callee_text for site in pf.call_sites)
