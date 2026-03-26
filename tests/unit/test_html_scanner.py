"""Unit tests for the HTML script-tag scanner (parsing/html_scanner.py)."""
from __future__ import annotations

import pytest

from repograph.parsing.html_scanner import scan_script_tags


class TestScriptTagExtraction:
    """Basic extraction from <script src="..."> tags."""

    def test_simple_script_tag(self):
        html = b'<script src="/static/js/utils.js"></script>'
        result = scan_script_tags(html, "index.html")
        assert "static/js/utils.js" in result

    def test_relative_src_resolved(self):
        html = b'<script src="./js/app.js"></script>'
        result = scan_script_tags(html, "public/index.html")
        assert "public/js/app.js" in result

    def test_versioned_query_string_stripped(self):
        html = b'<script src="/static/js/utils.js?v=21"></script>'
        result = scan_script_tags(html, "index.html")
        assert any("utils.js" in p and "?" not in p for p in result)

    def test_multiple_scripts_all_returned(self):
        html = b"""
        <script src="/js/utils.js"></script>
        <script src="/js/app.js"></script>
        <script src="/js/dashboard.js"></script>
        """
        result = scan_script_tags(html, "index.html")
        assert len(result) == 3

    def test_deduplication(self):
        html = b"""
        <script src="/js/utils.js"></script>
        <script src="/js/utils.js"></script>
        """
        result = scan_script_tags(html, "index.html")
        assert result.count("js/utils.js") == 1

    def test_result_is_sorted(self):
        html = b"""
        <script src="/js/z.js"></script>
        <script src="/js/a.js"></script>
        """
        result = scan_script_tags(html, "index.html")
        assert result == sorted(result)


class TestCDNExclusion:
    """CDN and absolute URLs must be excluded."""

    def test_https_cdn_excluded(self):
        html = b'<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>'
        result = scan_script_tags(html, "index.html")
        assert result == []

    def test_http_cdn_excluded(self):
        html = b'<script src="http://code.jquery.com/jquery.min.js"></script>'
        result = scan_script_tags(html, "index.html")
        assert result == []

    def test_protocol_relative_excluded(self):
        html = b'<script src="//cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>'
        result = scan_script_tags(html, "index.html")
        assert result == []

    def test_local_script_included_alongside_cdn(self):
        html = b"""
        <script src="https://cdn.example.com/lib.js"></script>
        <script src="/static/js/utils.js"></script>
        """
        result = scan_script_tags(html, "index.html")
        assert len(result) == 1
        assert "utils.js" in result[0]


class TestESModuleExclusion:
    """type="module" scripts use ES imports, not globals — must be excluded."""

    def test_type_module_excluded(self):
        html = b'<script type="module" src="/static/js/main.js"></script>'
        result = scan_script_tags(html, "index.html")
        assert result == []

    def test_type_module_case_insensitive(self):
        html = b'<script type="Module" src="/static/js/main.js"></script>'
        result = scan_script_tags(html, "index.html")
        assert result == []

    def test_non_module_type_included(self):
        html = b'<script type="text/javascript" src="/static/js/utils.js"></script>'
        result = scan_script_tags(html, "index.html")
        assert "static/js/utils.js" in result


class TestPathResolution:
    """Path resolution for relative and absolute-from-root paths."""

    def test_absolute_from_root_strips_leading_slash(self):
        html = b'<script src="/static/js/utils.js"></script>'
        result = scan_script_tags(html, "src/ui/index.html")
        assert "static/js/utils.js" in result

    def test_relative_path_resolved_against_html_dir(self):
        html = b'<script src="../js/utils.js"></script>'
        result = scan_script_tags(html, "src/ui/index.html")
        assert "src/js/utils.js" in result

    def test_path_traversal_outside_root_excluded(self):
        html = b'<script src="../../../outside.js"></script>'
        result = scan_script_tags(html, "index.html")
        # Must not escape repo root
        assert not any(".." in p for p in result)

    def test_non_js_extension_excluded(self):
        html = b'<script src="/static/loader.css"></script>'
        result = scan_script_tags(html, "index.html")
        assert result == []

    def test_typescript_extension_included(self):
        html = b'<script src="/static/js/utils.ts"></script>'
        result = scan_script_tags(html, "index.html")
        assert "static/js/utils.ts" in result

    def test_empty_html(self):
        result = scan_script_tags(b"", "index.html")
        assert result == []

    def test_html_without_scripts(self):
        html = b"<html><body><p>Hello</p></body></html>"
        result = scan_script_tags(html, "index.html")
        assert result == []
