"""Unit tests for JavaScript is_script_global tagging."""
from __future__ import annotations

import os
import pytest

from repograph.plugins.parsers.javascript.javascript_parser import JavaScriptParser
from repograph.core.models import FileRecord
from repograph.utils.hashing import hash_file_content


def _make_record(path: str = "utils.js", content: str = "") -> FileRecord:
    b = content.encode()
    return FileRecord(
        path=path, abs_path=f"/repo/{path}", name=path.split("/")[-1],
        extension=".js", language="javascript",
        size_bytes=len(b), line_count=b.count(b"\n") + 1,
        source_hash=hash_file_content(b),
        is_test=False, is_config=False, mtime=0.0,
    )


@pytest.fixture
def parser():
    return JavaScriptParser()


class TestScriptGlobalTagging:
    """Module-scope JS functions must be tagged is_script_global=True."""

    def test_module_scope_function_tagged(self, parser):
        src = b"function formatPrice(p) { return p.toFixed(2); }\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        fn = next(f for f in pf.functions if f.name == "formatPrice")
        assert fn.is_script_global is True

    def test_arrow_function_at_module_scope_tagged(self, parser):
        src = b"const apiFetch = (url) => fetch(url).then(r => r.json());\n"
        pf = parser.parse(src, _make_record(content=src.decode()))
        fn = next((f for f in pf.functions if f.name == "apiFetch"), None)
        assert fn is not None
        assert fn.is_script_global is True

    def test_class_method_not_tagged(self, parser):
        src = b"""
class ChartManager {
  constructor(id) { this.id = id; }
  init() { return this.id; }
}
"""
        pf = parser.parse(src, _make_record(content=src.decode()))
        methods = [f for f in pf.functions if f.is_method]
        assert len(methods) >= 1
        for m in methods:
            assert m.is_script_global is False, \
                f"class method {m.name!r} wrongly tagged as script global"

    def test_nested_function_not_tagged(self, parser):
        src = b"""
function outer(x) {
  function _inner(y) { return x + y; }
  return _inner;
}
"""
        pf = parser.parse(src, _make_record(content=src.decode()))
        outer = next(f for f in pf.functions if f.name == "outer")
        assert outer.is_script_global is True  # outer is module-scope
        inner = next((f for f in pf.functions if f.name == "_inner"), None)
        if inner is not None:
            assert inner.is_script_global is False  # _inner is nested

    def test_multiple_module_scope_functions_all_tagged(self, parser):
        src = b"""
function formatTs(ts) { return new Date(ts).toISOString(); }
function timeSince(ts) { return Date.now() - ts; }
function safeJson(s) { try { return JSON.parse(s); } catch(e) { return null; } }
"""
        pf = parser.parse(src, _make_record(content=src.decode()))
        for name in ("formatTs", "timeSince", "safeJson"):
            fn = next(f for f in pf.functions if f.name == name)
            assert fn.is_script_global is True, \
                f"{name!r} should be is_script_global but is not"


class TestScriptGlobalIntegration:
    """End-to-end: script-global functions in script-tag-loaded files must
    not be flagged dead, even with zero explicit callers."""

    def test_script_global_not_in_dead_code(self, tmp_path):
        import os
        import shutil
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "script_tag_globals")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)

        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        run_full_pipeline(RunConfig(
            repo_root=repo, repograph_dir=rg_dir,
            include_git=False, include_embeddings=False, full=True,
        ))

        from repograph.graph_store.store import GraphStore
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        dead = store.get_dead_functions()
        store.close()

        dead_names = {r["qualified_name"] for r in dead}
        # formatPrice and apiFetch are loaded via <script src> and must not be dead
        assert "formatPrice" not in dead_names, \
            "formatPrice (script global) wrongly flagged dead"
        assert "apiFetch" not in dead_names, \
            "apiFetch (script global) wrongly flagged dead"
        assert "formatTs" not in dead_names, \
            "formatTs (script global) wrongly flagged dead"


class TestScriptGlobalCallEdges:
    """CALLS edges must be created for script-global cross-file calls.

    When app.js calls apiFetch() (defined in utils.js) and both are loaded
    via <script> tags from index.html, Phase 5 must create a CALLS edge from
    loadData → apiFetch even though there is no import statement.
    """

    def test_calls_edge_created_through_shared_scope(self, tmp_path):
        import os
        import shutil
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "script_tag_globals")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)

        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        run_full_pipeline(RunConfig(
            repo_root=repo, repograph_dir=rg_dir,
            include_git=False, include_embeddings=False, full=True,
        ))

        from repograph.graph_store.store import GraphStore
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        rows = store.query(
            "MATCH (caller:Function)-[:CALLS]->(callee:Function) "
            "WHERE callee.name = 'apiFetch' "
            "RETURN caller.name"
        )
        store.close()

        callers = {r[0] for r in rows}
        assert "loadData" in callers, (
            f"Expected loadData → apiFetch CALLS edge via script-global scope, "
            f"got callers: {callers}"
        )

    def test_utils_functions_have_callers_via_shared_scope(self, tmp_path):
        """formatPrice and formatTs called from app.js must have CALLS edges."""
        import os
        import shutil
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "script_tag_globals")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)

        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        run_full_pipeline(RunConfig(
            repo_root=repo, repograph_dir=rg_dir,
            include_git=False, include_embeddings=False, full=True,
        ))

        from repograph.graph_store.store import GraphStore
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()

        for fn_name in ("formatPrice", "formatTs"):
            rows = store.query(
                "MATCH (caller:Function)-[:CALLS]->(callee:Function) "
                "WHERE callee.name = $name "
                "RETURN caller.name",
                {"name": fn_name}
            )
            callers = {r[0] for r in rows}
            assert callers, (
                f"Expected at least one caller for {fn_name} via shared script scope, "
                f"got none"
            )

        store.close()


class TestScriptTagServerPrefixResolution:
    """HTML files that use server-relative /static/ URL prefixes (Flask pattern)
    must still resolve to the correct repo files via suffix-fallback lookup.

    Reproduces the working-repo bug where:
        <script src="/static/js/utils.js?v=21">
    lives at src/ui/static/index.html but the JS file is at
        src/ui/static/js/utils.js
    so the scanner returns 'static/js/utils.js' but the repo path starts
    with 'src/ui/static/js/utils.js' — no direct match in path_index.
    """

    FIXTURE = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "fixtures",
                     "script_tag_server_prefix")
    )

    def test_html_imports_js_via_suffix_fallback(self, tmp_path):
        """IMPORTS edges must be created even when /static/ doesn't match
        the repo's src/ui/static/ prefix."""
        import shutil
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(self.FIXTURE, repo)

        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        run_full_pipeline(RunConfig(
            repo_root=repo, repograph_dir=rg_dir,
            include_git=False, include_embeddings=False, full=True,
        ))

        from repograph.graph_store.store import GraphStore
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        rows = store.query(
            """
            MATCH (h:File)-[:IMPORTS]->(js:File)
            WHERE h.language = 'html' AND js.language = 'javascript'
            RETURN h.path, js.path
            """
        )
        store.close()

        js_targets = {r[1] for r in rows}
        assert any("utils.js" in p for p in js_targets), (
            f"Expected utils.js in HTML→JS IMPORTS edges, got: {js_targets}"
        )
        assert any("app.js" in p for p in js_targets), (
            f"Expected app.js in HTML→JS IMPORTS edges, got: {js_targets}"
        )

    def test_utils_functions_not_dead_with_server_prefix(self, tmp_path):
        """apiFetch and formatPrice must not be dead when loaded via
        a server-prefix path with query string caching."""
        import shutil
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(self.FIXTURE, repo)

        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        run_full_pipeline(RunConfig(
            repo_root=repo, repograph_dir=rg_dir,
            include_git=False, include_embeddings=False, full=True,
        ))

        from repograph.graph_store.store import GraphStore
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        dead = {r["qualified_name"] for r in store.get_dead_functions()}
        store.close()

        assert "apiFetch" not in dead, (
            "apiFetch loaded via /static/js/utils.js?v=21 must not be dead"
        )
        assert "formatPrice" not in dead, (
            "formatPrice loaded via /static/js/utils.js?v=21 must not be dead"
        )
