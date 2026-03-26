"""Unit tests for the JavaScript parser."""
from __future__ import annotations

import pytest
from repograph.plugins.parsers.javascript.javascript_parser import JavaScriptParser
from repograph.core.models import FileRecord
from repograph.utils.hashing import hash_file_content


def _make_record(path: str = "test.js", content: str = "") -> FileRecord:
    content_bytes = content.encode()
    return FileRecord(
        path=path, abs_path=f"/repo/{path}", name=path.split("/")[-1],
        extension=".js", language="javascript",
        size_bytes=len(content_bytes), line_count=content_bytes.count(b"\n") + 1,
        source_hash=hash_file_content(content_bytes),
        is_test=False, is_config=False, mtime=0.0,
    )


@pytest.fixture
def parser():
    return JavaScriptParser()


class TestJSFunctionExtraction:
    def test_function_declaration(self, parser):
        src = b"function foo(x, y) { return x + y; }\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        assert any(f.name == "foo" for f in pf.functions)

    def test_arrow_function(self, parser):
        src = b"const bar = (a) => { return a * 2; };\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        assert any(f.name == "bar" for f in pf.functions)

    def test_async_function(self, parser):
        src = b"async function fetchData(url) { return url; }\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        fn = next((f for f in pf.functions if f.name == "fetchData"), None)
        assert fn is not None
        assert fn.is_async is True

    def test_class_method(self, parser):
        src = b"class Foo {\n  constructor(x) { this.x = x; }\n  getX() { return this.x; }\n}\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        names = {f.name for f in pf.functions}
        assert "constructor" in names
        assert "getX" in names

    def test_method_is_method(self, parser):
        src = b"class Foo {\n  doThing() { return 1; }\n}\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        methods = [f for f in pf.functions if f.is_method]
        assert len(methods) >= 1

    def test_qualified_name_includes_class(self, parser):
        src = b"class Auth {\n  login(email) { return email; }\n}\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        method = next((f for f in pf.functions if f.name == "login"), None)
        assert method is not None
        assert "Auth" in method.qualified_name


class TestJSClassExtraction:
    def test_class_declaration(self, parser):
        src = b"class MyClass { }\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        assert any(c.name == "MyClass" for c in pf.classes)

    def test_class_with_extends(self, parser):
        src = b"class Dog extends Animal { }\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        cls = pf.classes[0]
        assert "Animal" in cls.base_names


class TestJSImportExtraction:
    def test_esm_import(self, parser):
        src = b"import express from 'express';\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        assert any(i.module_path == "express" for i in pf.imports)

    def test_named_import(self, parser):
        src = b"import { Router } from 'express';\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        imp = pf.imports[0]
        assert imp.module_path == "express"
        assert "Router" in imp.imported_names

    def test_require_import(self, parser):
        src = b"const fs = require('fs');\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        assert any(i.module_path == "fs" for i in pf.imports)

    def test_relative_require(self, parser):
        src = b"const auth = require('./services/auth');\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        assert any("./services/auth" in i.module_path for i in pf.imports)


class TestJSCallSiteExtraction:
    def test_function_call(self, parser):
        src = b"function caller() { doSomething(); }\nfunction doSomething() {}\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        assert any(s.callee_text == "doSomething" for s in pf.call_sites)

    def test_method_call(self, parser):
        src = b"function caller(obj) { obj.method(x); }\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        assert any("method" in s.callee_text for s in pf.call_sites)

    def test_call_in_async(self, parser):
        src = b"async function handler(req) { const data = await fetchData(req.url); }\nfunction fetchData(u) {}\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        assert any("fetchData" in s.callee_text for s in pf.call_sites)
