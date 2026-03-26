"""Unit tests for dead-code analyzer fixes.

Covers:
  Fix 1 — Closure-returned functions must not be flagged dead.
  Fix 3 — Functions called only at module level must not be flagged dead.
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

from repograph.plugins.parsers.python.python_parser import PythonParser
from repograph.core.models import FileRecord
from repograph.utils.hashing import hash_file_content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(path: str, content: str) -> FileRecord:
    b = content.encode()
    return FileRecord(
        path=path, abs_path=f"/repo/{path}", name=path.split("/")[-1],
        extension=".py", language="python",
        size_bytes=len(b), line_count=b.count(b"\n") + 1,
        source_hash=hash_file_content(b),
        is_test=False, is_config=False, mtime=0.0,
    )


def _make_js_record(path: str, content: str) -> FileRecord:
    b = content.encode()
    ext = os.path.splitext(path)[1].lower()
    return FileRecord(
        path=path, abs_path=f"/repo/{path}", name=path.split("/")[-1],
        extension=ext, language="javascript",
        size_bytes=len(b), line_count=b.count(b"\n") + 1,
        source_hash=hash_file_content(b),
        is_test=False, is_config=False, mtime=0.0,
    )


def _parse(src: str, path: str = "test.py"):
    parser = PythonParser()
    rec = _make_record(path, src)
    return parser.parse(src.encode(), rec)


def _parse_js(src: str, path: str = "test.js"):
    from repograph.plugins.parsers.javascript.javascript_parser import JavaScriptParser

    parser = JavaScriptParser()
    rec = _make_js_record(path, src)
    return parser.parse(src.encode(), rec)


def _full_run(repo: str, rg_dir: str):
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    return run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, include_embeddings=False, full=True,
    ))


def _open_store(rg_dir: str):
    from repograph.graph_store.store import GraphStore
    store = GraphStore(os.path.join(rg_dir, "graph.db"))
    store.initialize_schema()
    return store


# ---------------------------------------------------------------------------
# Fix 1 — Closure exemption (parser-level)
# ---------------------------------------------------------------------------

class TestClosureReturnedParsing:
    """The Python parser must set is_closure_returned on directly-returned nested fns."""

    def test_simple_closure_is_tagged(self):
        src = """
def make_handler(name):
    def _handle(event):
        return name
    return _handle
"""
        pf = _parse(src)
        fn_names = {f.name: f for f in pf.functions}
        assert "_handle" in fn_names, "nested fn not extracted"
        assert fn_names["_handle"].is_closure_returned is True

    def test_async_closure_is_tagged(self):
        src = """
def make_stop(svc):
    async def _stop():
        svc.stop()
    return _stop
"""
        pf = _parse(src)
        fn_names = {f.name: f for f in pf.functions}
        assert "_stop" in fn_names
        assert fn_names["_stop"].is_closure_returned is True

    def test_non_returned_nested_fn_not_tagged(self):
        """A nested fn that is called but not returned should NOT be tagged."""
        src = """
def outer():
    def _inner():
        pass
    _inner()
"""
        pf = _parse(src)
        fn_names = {f.name: f for f in pf.functions}
        assert "_inner" in fn_names
        assert fn_names["_inner"].is_closure_returned is False

    def test_outer_fn_itself_not_tagged(self):
        """The outer factory function must not be tagged as closure_returned."""
        src = """
def make_thing():
    def _thing():
        pass
    return _thing
"""
        pf = _parse(src)
        fn_names = {f.name: f for f in pf.functions}
        assert fn_names["make_thing"].is_closure_returned is False

    def test_multiple_closures_all_tagged(self):
        src = """
def factory(x, y):
    def _a():
        return x
    def _b():
        return y
    if x:
        return _a
    return _b
"""
        pf = _parse(src)
        fn_names = {f.name: f for f in pf.functions}
        # Both _a and _b appear in return statements at the factory body level
        assert fn_names["_a"].is_closure_returned is True
        assert fn_names["_b"].is_closure_returned is True


class TestClosureExemptionIntegration:
    """Closure-returned functions must not appear in dead_code() output."""

    def test_closure_not_in_dead_code(self, tmp_path):
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "closure_factory")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        dead_names = {r["qualified_name"] for r in store.get_dead_functions()}
        store.close()

        assert "_handle" not in dead_names, "_handle (closure) wrongly flagged dead"
        assert "_stop" not in dead_names, "_stop (async closure) wrongly flagged dead"

    def test_truly_dead_helper_is_flagged(self, tmp_path):
        """truly_dead_helper in the fixture has no callers — must be flagged."""
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "closure_factory")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        dead_names = {r["qualified_name"] for r in store.get_dead_functions()}
        store.close()

        assert "truly_dead_helper" in dead_names


# ---------------------------------------------------------------------------
# Fix 3 — Module-level call tracking (parser-level)
# ---------------------------------------------------------------------------

class TestModuleLevelCallParsing:
    """The Python parser must create a __module__ sentinel and attribute
    module-level call sites to it."""

    def test_module_level_call_creates_sentinel(self):
        src = """
from helpers import setup

CONFIG = setup()
"""
        pf = _parse(src)
        sentinels = [f for f in pf.functions if f.is_module_caller]
        assert len(sentinels) == 1, "expected exactly one __module__ sentinel"
        assert sentinels[0].name == "__module__"

    def test_module_level_call_attributed_to_sentinel(self):
        src = """
from helpers import get_config

PATH = get_config()
"""
        pf = _parse(src)
        sentinel = next(f for f in pf.functions if f.is_module_caller)
        module_calls = [
            s for s in pf.call_sites
            if s.caller_function_id == sentinel.id
        ]
        callee_texts = [s.callee_text for s in module_calls]
        assert "get_config" in callee_texts

    def test_function_body_calls_not_in_module_sentinel(self):
        """Calls inside function bodies must NOT be attributed to __module__."""
        src = """
def foo():
    bar()

def bar():
    pass
"""
        pf = _parse(src)
        sentinels = [f for f in pf.functions if f.is_module_caller]
        # No top-level calls exist, so no __module__ sentinel should be created
        assert len(sentinels) == 0

    def test_if_name_main_calls_tracked(self):
        """Calls inside ``if __name__ == '__main__':`` are module-level."""
        src = """
from helpers import init

if __name__ == '__main__':
    init()
"""
        pf = _parse(src)
        sentinels = [f for f in pf.functions if f.is_module_caller]
        assert len(sentinels) == 1
        module_calls = [
            s for s in pf.call_sites
            if s.caller_function_id == sentinels[0].id
        ]
        assert any("init" in s.callee_text for s in module_calls)


class TestModuleLevelCallParsingJS:
    """JavaScript mirrors Python: ``__module__`` sentinel + module-scope call sites."""

    def test_module_level_call_creates_sentinel_js(self):
        src = """
function callee() { return 1; }
callee();
"""
        pf = _parse_js(src)
        sentinels = [f for f in pf.functions if f.is_module_caller]
        assert len(sentinels) == 1
        assert sentinels[0].qualified_name == "__module__"

    def test_module_level_call_attributed_to_sentinel_js(self):
        src = """
function getThing() { return 1; }
getThing();
"""
        pf = _parse_js(src)
        sentinel = next(f for f in pf.functions if f.is_module_caller)
        names = [s.callee_text for s in pf.call_sites if s.caller_function_id == sentinel.id]
        assert "getThing" in names

    def test_no_top_level_calls_no_sentinel_js(self):
        src = """
function foo() { bar(); }
function bar() { return 1; }
"""
        pf = _parse_js(src)
        assert not any(f.is_module_caller for f in pf.functions)


class TestModuleLevelCallIntegration:
    """Functions called only at module level must not appear in dead_code()."""

    def test_module_level_callee_not_dead(self, tmp_path):
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "module_level_call")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        dead_names = {r["qualified_name"] for r in store.get_dead_functions()}
        store.close()

        assert "get_default_config_path" not in dead_names, \
            "get_default_config_path (module-level callee) wrongly flagged dead"
        assert "get_repo_root" not in dead_names, \
            "get_repo_root (module-level callee) wrongly flagged dead"

    def test_truly_dead_still_flagged(self, tmp_path):
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "module_level_call")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        dead_names = {r["qualified_name"] for r in store.get_dead_functions()}
        store.close()

        assert "truly_dead" in dead_names

    def test_module_sentinel_not_in_dead_code_output(self, tmp_path):
        """The __module__ sentinel itself must never appear in dead_code output."""
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "module_level_call")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        dead = store.get_dead_functions()
        store.close()

        sentinel_in_dead = any("__module__" in r["qualified_name"] for r in dead)
        assert not sentinel_in_dead, "__module__ sentinel must not appear in dead code"

    def test_js_module_level_callee_not_dead(self, tmp_path):
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "js_module_level")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        dead_names = {r["qualified_name"] for r in store.get_dead_functions()}
        store.close()

        assert "liveCallee" not in dead_names
        assert "neverCalled" in dead_names
