"""Tests for F6 — name normalization index and cross-language name similarity (Block F6)."""
from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# normalize_cross_lang_name
# ---------------------------------------------------------------------------


def test_camel_case_to_snake():
    from repograph.parsing.cross_lang_resolver import normalize_cross_lang_name
    assert normalize_cross_lang_name("getUser") == "get_user"


def test_pascal_case_to_snake():
    from repograph.parsing.cross_lang_resolver import normalize_cross_lang_name
    assert normalize_cross_lang_name("GetUser") == "get_user"


def test_snake_case_unchanged():
    from repograph.parsing.cross_lang_resolver import normalize_cross_lang_name
    assert normalize_cross_lang_name("get_user") == "get_user"


def test_camel_and_snake_normalize_to_same():
    from repograph.parsing.cross_lang_resolver import normalize_cross_lang_name
    assert normalize_cross_lang_name("getUser") == normalize_cross_lang_name("get_user")


def test_single_word_lowercase():
    from repograph.parsing.cross_lang_resolver import normalize_cross_lang_name
    assert normalize_cross_lang_name("login") == "login"


def test_multi_word_camel():
    from repograph.parsing.cross_lang_resolver import normalize_cross_lang_name
    assert normalize_cross_lang_name("createNewUser") == "create_new_user"


# ---------------------------------------------------------------------------
# build_cross_lang_name_index
# ---------------------------------------------------------------------------


def _make_fn(fn_id: str, name: str, file_path: str, language: str = "python",
             is_exported: bool = True):
    from repograph.core.models import FunctionNode
    return FunctionNode(
        id=fn_id, name=name, qualified_name=name,
        file_path=file_path, line_start=1, line_end=3,
        signature=f"def {name}()", docstring=None,
        is_method=False, is_async=False, is_exported=is_exported,
        decorators=[], param_names=[], return_type=None, source_hash="x",
    )


def _make_pf(path: str, language: str, functions):
    from repograph.core.models import ParsedFile, FileRecord
    fr = FileRecord(
        path=path, abs_path=path, name=Path(path).name,
        extension=Path(path).suffix, language=language,
        size_bytes=0, line_count=5, source_hash="x",
        is_test=False, is_config=False, mtime=0.0,
    )
    pf = ParsedFile(file_record=fr)
    pf.functions = list(functions)
    return pf


def test_index_buckets_python_and_js_functions_by_normalized_name():
    from repograph.parsing.cross_lang_resolver import build_cross_lang_name_index

    py_fn = _make_fn("fn::py_get_user", "get_user", "app.py", "python")
    js_fn = _make_fn("fn::js_getUser", "getUser", "app.ts", "typescript")

    py_pf = _make_pf("app.py", "python", [py_fn])
    js_pf = _make_pf("app.ts", "typescript", [js_fn])

    index = build_cross_lang_name_index([py_pf, js_pf])

    assert "get_user" in index
    assert "python" in index["get_user"]
    assert "fn::py_get_user" in index["get_user"]["python"]
    assert "typescript" in index["get_user"]
    assert "fn::js_getUser" in index["get_user"]["typescript"]


def test_index_excludes_non_exported_functions():
    from repograph.parsing.cross_lang_resolver import build_cross_lang_name_index

    private_fn = _make_fn("fn::private", "_helper", "app.py", "python", is_exported=False)
    py_pf = _make_pf("app.py", "python", [private_fn])

    index = build_cross_lang_name_index([py_pf])
    # _helper normalises to 'helper' — but function is not exported, so excluded
    for bucket in index.values():
        for lang_ids in bucket.values():
            assert "fn::private" not in lang_ids


def test_index_only_includes_known_languages():
    from repograph.parsing.cross_lang_resolver import build_cross_lang_name_index

    html_pf = _make_pf("index.html", "html", [])
    index = build_cross_lang_name_index([html_pf])
    assert index == {}


# ---------------------------------------------------------------------------
# get_cross_lang_candidates
# ---------------------------------------------------------------------------


def test_get_candidates_excludes_source_language():
    from repograph.parsing.cross_lang_resolver import build_cross_lang_name_index, get_cross_lang_candidates

    py_fn = _make_fn("fn::py", "getUser", "a.py", "python")
    js_fn = _make_fn("fn::js", "getUser", "a.ts", "typescript")
    py_pf = _make_pf("a.py", "python", [py_fn])
    js_pf = _make_pf("a.ts", "typescript", [js_fn])

    index = build_cross_lang_name_index([py_pf, js_pf])
    candidates = get_cross_lang_candidates(index, "get_user", source_lang="python")

    assert "python" not in candidates
    assert "typescript" in candidates
    assert "fn::js" in candidates["typescript"]


def test_get_candidates_returns_empty_for_unknown_name():
    from repograph.parsing.cross_lang_resolver import build_cross_lang_name_index, get_cross_lang_candidates

    index = build_cross_lang_name_index([])
    result = get_cross_lang_candidates(index, "nonexistent_function", source_lang="python")
    assert result == {}
