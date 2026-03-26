"""Unit tests for variable extractor and resolver."""
from __future__ import annotations

import pytest
from repograph.plugins.parsers.python.python_parser import PythonParser
from repograph.variables.extractor import VariableScopeExtractor
from repograph.variables.resolver import ArgumentChainResolver
from repograph.core.models import FileRecord


def _parse(src: str, path: str = "test.py"):
    from repograph.utils.hashing import hash_file_content
    content = src.encode()
    fr = FileRecord(
        path=path, abs_path=f"/repo/{path}", name=path.split("/")[-1],
        extension=".py", language="python",
        size_bytes=len(content), line_count=content.count(b"\n") + 1,
        source_hash=hash_file_content(content),
        is_test=False, is_config=False, mtime=0.0,
    )
    return PythonParser().parse(content, fr)


class TestVariableScopeExtractor:
    def test_parameters_found(self):
        pf = _parse("def foo(x, y):\n    pass\n")
        extractor = VariableScopeExtractor([pf])
        fn = pf.functions[0]
        assert extractor.lookup(fn.id, "x") is not None
        assert extractor.lookup(fn.id, "y") is not None

    def test_typed_parameter_type(self):
        pf = _parse("def foo(x: int, y: str):\n    pass\n")
        extractor = VariableScopeExtractor([pf])
        fn = pf.functions[0]
        xvar = extractor.lookup(fn.id, "x")
        assert xvar is not None
        assert xvar.inferred_type == "int"

    def test_assignment_in_scope(self):
        pf = _parse("def foo():\n    result = 42\n    return result\n")
        extractor = VariableScopeExtractor([pf])
        fn = pf.functions[0]
        v = extractor.lookup(fn.id, "result")
        assert v is not None
        assert v.inferred_type == "int"

    def test_param_by_index(self):
        pf = _parse("def foo(a, b, c):\n    pass\n")
        extractor = VariableScopeExtractor([pf])
        fn = pf.functions[0]
        p0 = extractor.get_param_by_index(fn.id, 0)
        p1 = extractor.get_param_by_index(fn.id, 1)
        p2 = extractor.get_param_by_index(fn.id, 2)
        assert p0 is not None and p1 is not None and p2 is not None
        assert p0.name == "a"
        assert p1.name == "b"
        assert p2.name == "c"

    def test_param_by_name(self):
        pf = _parse("def foo(x: int, y: str):\n    pass\n")
        extractor = VariableScopeExtractor([pf])
        fn = pf.functions[0]
        assert extractor.get_param_by_name(fn.id, "x") is not None
        assert extractor.get_param_by_name(fn.id, "missing") is None


class TestArgumentChainResolver:
    def test_positional_binding(self):
        src = "def caller(val):\n    callee(val)\n\ndef callee(x):\n    pass\n"
        pf = _parse(src)
        extractor = VariableScopeExtractor([pf])

        caller_fn = next(f for f in pf.functions if f.name == "caller")
        callee_fn = next(f for f in pf.functions if f.name == "callee")

        fake_call_edges = [{
            "from": caller_fn.id, "to": callee_fn.id,
            "line": 2, "confidence": 0.9, "reason": "direct_call",
        }]
        resolver = ArgumentChainResolver(extractor, fake_call_edges, [pf])
        edges = resolver.build_flows_into_edges()

        assert len(edges) >= 1
        edge = edges[0]
        assert edge.via_argument == "x"
        assert edge.confidence == pytest.approx(0.81, rel=0.01)

    def test_keyword_binding(self):
        src = "def caller(name):\n    callee(target=name)\n\ndef callee(target):\n    pass\n"
        pf = _parse(src)
        extractor = VariableScopeExtractor([pf])

        caller_fn = next(f for f in pf.functions if f.name == "caller")
        callee_fn = next(f for f in pf.functions if f.name == "callee")

        fake_call_edges = [{
            "from": caller_fn.id, "to": callee_fn.id,
            "line": 2, "confidence": 1.0, "reason": "direct_call",
        }]
        resolver = ArgumentChainResolver(extractor, fake_call_edges, [pf])
        edges = resolver.build_flows_into_edges()

        assert any(e.via_argument == "target" for e in edges)
