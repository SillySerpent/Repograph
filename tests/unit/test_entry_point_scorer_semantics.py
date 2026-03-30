from __future__ import annotations

from repograph.plugins.static_analyzers.pathways.scorer import score_function_verbose


def test_resource_lifecycle_methods_are_demoted() -> None:
    close_score = score_function_verbose(
        {
            "name": "close",
            "qualified_name": "GraphStoreBase.close",
            "file_path": "repograph/graph_store/store_base.py",
            "is_exported": False,
            "decorators": [],
        },
        callees_count=4,
        callers_count=0,
    ).final_score
    handler_score = score_function_verbose(
        {
            "name": "handle_request",
            "qualified_name": "handlers.handle_request",
            "file_path": "src/handlers/http.py",
            "is_exported": False,
            "decorators": [],
        },
        callees_count=4,
        callers_count=0,
    ).final_score
    assert close_score < handler_score
