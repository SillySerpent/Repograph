"""Tests for F7 — pathway walker cross-language traversal via MAKES_HTTP_CALL edges."""
from __future__ import annotations

from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fn_dict(fn_id: str, name: str, file_path: str, entry_score: float = 0.5):
    return {
        "id": fn_id,
        "name": name,
        "qualified_name": name,
        "file_path": file_path,
        "line_start": 1,
        "line_end": 10,
        "entry_score": entry_score,
        "is_entry_point": True,
        "decorators": [],
        "language": "python" if file_path.endswith(".py") else "typescript",
    }


def _make_store(
    functions: dict,
    callees: dict[str, list[dict]],
    http_callees: dict[str, list[dict]],
) -> MagicMock:
    """Build a minimal GraphStore mock for PathwayAssembler tests."""
    store = MagicMock()
    store.get_function_by_id.side_effect = lambda fn_id: functions.get(fn_id)
    store.get_callees.side_effect = lambda fn_id: callees.get(fn_id, [])
    store.get_http_callees.side_effect = lambda fn_id: http_callees.get(fn_id, [])
    store.get_flows_into_edges.return_value = []
    store.query.return_value = []
    return store


# ---------------------------------------------------------------------------
# test_pathway_traverses_makes_http_call_edge
# ---------------------------------------------------------------------------


def test_pathway_traverses_makes_http_call_edge():
    """Pathway BFS must follow MAKES_HTTP_CALL edges across the language boundary."""
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler

    py_caller = _make_fn_dict("fn::py_caller", "send_request", "app/client.py")
    ts_handler = _make_fn_dict("fn::ts_handler", "handlePost", "api/route.ts")
    ts_db = _make_fn_dict("fn::ts_db", "saveRecord", "api/db.ts")

    functions = {
        "fn::py_caller": py_caller,
        "fn::ts_handler": ts_handler,
        "fn::ts_db": ts_db,
    }
    callees = {
        # ts_handler calls ts_db via regular CALLS edge within TypeScript
        "fn::ts_handler": [{"id": "fn::ts_db", "confidence": 0.9}],
    }
    http_callees = {
        # py_caller reaches ts_handler via MAKES_HTTP_CALL
        "fn::py_caller": [
            {"id": "fn::ts_handler", "confidence": 0.85, "http_method": "POST"}
        ],
    }

    store = _make_store(functions, callees, http_callees)
    assembler = PathwayAssembler(store)
    doc = assembler.assemble("fn::py_caller")

    assert doc is not None
    step_ids = [s.function_id for s in doc.steps]
    assert "fn::py_caller" in step_ids, "Python entry must be in pathway"
    assert "fn::ts_handler" in step_ids, "TS handler must be reached via MAKES_HTTP_CALL"
    assert "fn::ts_db" in step_ids, "TS db function must be reached via chained CALLS"


# ---------------------------------------------------------------------------
# test_cross_lang_step_flag_set
# ---------------------------------------------------------------------------


def test_cross_lang_step_flag_set():
    """Steps reached via MAKES_HTTP_CALL must have cross_lang_step=True."""
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler

    py_caller = _make_fn_dict("fn::py", "call_api", "app/main.py")
    ts_handler = _make_fn_dict("fn::ts", "handleGet", "api/users/route.ts")
    ts_db = _make_fn_dict("fn::ts_db", "fetchUsers", "api/users/db.ts")

    functions = {"fn::py": py_caller, "fn::ts": ts_handler, "fn::ts_db": ts_db}
    callees = {"fn::ts": [{"id": "fn::ts_db", "confidence": 0.9}]}
    http_callees = {
        "fn::py": [{"id": "fn::ts", "confidence": 0.85, "http_method": "GET"}],
    }

    store = _make_store(functions, callees, http_callees)
    assembler = PathwayAssembler(store)
    doc = assembler.assemble("fn::py")

    assert doc is not None
    ts_step = next((s for s in doc.steps if s.function_id == "fn::ts"), None)
    assert ts_step is not None
    assert ts_step.cross_lang_step is True
    assert ts_step.http_method == "GET"


# ---------------------------------------------------------------------------
# test_cross_lang_http_role_assigned
# ---------------------------------------------------------------------------


def test_cross_lang_http_role_assigned():
    """Steps reached via MAKES_HTTP_CALL must have role='cross_lang_http'."""
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler

    py_caller = _make_fn_dict("fn::py", "fetch_users", "services/user_svc.py")
    ts_handler = _make_fn_dict("fn::ts", "getUsers", "pages/api/users.ts")
    ts_db = _make_fn_dict("fn::ts_db", "queryUsers", "pages/api/db.ts")

    functions = {"fn::py": py_caller, "fn::ts": ts_handler, "fn::ts_db": ts_db}
    callees = {"fn::ts": [{"id": "fn::ts_db", "confidence": 0.9}]}
    http_callees = {
        "fn::py": [{"id": "fn::ts", "confidence": 0.85, "http_method": "GET"}],
    }

    store = _make_store(functions, callees, http_callees)
    assembler = PathwayAssembler(store)
    doc = assembler.assemble("fn::py")

    assert doc is not None
    ts_step = next((s for s in doc.steps if s.function_id == "fn::ts"), None)
    assert ts_step is not None
    assert ts_step.role == "cross_lang_http"


# ---------------------------------------------------------------------------
# test_entry_step_not_cross_lang
# ---------------------------------------------------------------------------


def test_entry_step_not_cross_lang():
    """The entry step itself must never be marked cross_lang_step."""
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler

    py_entry = _make_fn_dict("fn::entry", "run_job", "jobs/worker.py")
    py_helper = _make_fn_dict("fn::helper", "do_work", "jobs/tasks.py")
    py_sub = _make_fn_dict("fn::sub", "sub_work", "jobs/sub.py")

    functions = {"fn::entry": py_entry, "fn::helper": py_helper, "fn::sub": py_sub}
    callees = {
        "fn::entry": [{"id": "fn::helper", "confidence": 0.9}],
        "fn::helper": [{"id": "fn::sub", "confidence": 0.9}],
    }
    http_callees = {}

    store = _make_store(functions, callees, http_callees)
    assembler = PathwayAssembler(store)
    doc = assembler.assemble("fn::entry")

    assert doc is not None
    entry_step = doc.steps[0]
    assert entry_step.function_id == "fn::entry"
    assert entry_step.cross_lang_step is False
    assert entry_step.role == "entry"


# ---------------------------------------------------------------------------
# test_max_depth_prevents_infinite_loop
# ---------------------------------------------------------------------------


def test_max_depth_prevents_infinite_loop():
    """Cyclic call graphs must not cause infinite BFS loops; MAX_PATHWAY_STEPS guards it."""
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler
    from repograph.plugins.static_analyzers.pathways.pathway_bfs import MAX_PATHWAY_STEPS

    # Build a chain of 100 functions — far more than MAX_PATHWAY_STEPS
    num_fns = 100
    fn_ids = [f"fn::step_{i}" for i in range(num_fns)]
    functions = {
        fid: _make_fn_dict(fid, f"step_{i}", f"app/step_{i}.py")
        for i, fid in enumerate(fn_ids)
    }
    # Create a simple linear chain: step_0 → step_1 → ... → step_99
    callees = {
        fn_ids[i]: [{"id": fn_ids[i + 1], "confidence": 0.9}]
        for i in range(num_fns - 1)
    }
    http_callees = {}

    store = _make_store(functions, callees, http_callees)
    assembler = PathwayAssembler(store)
    doc = assembler.assemble(fn_ids[0])

    # Must complete without hanging, and step count must not exceed MAX_PATHWAY_STEPS
    assert doc is not None
    assert len(doc.steps) <= MAX_PATHWAY_STEPS


# ---------------------------------------------------------------------------
# test_cyclic_graph_terminates
# ---------------------------------------------------------------------------


def test_cyclic_graph_terminates():
    """A cyclic CALLS graph (a → b → a) must not cause an infinite loop."""
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler

    fn_a = _make_fn_dict("fn::a", "func_a", "app/a.py", entry_score=1.0)
    fn_b = _make_fn_dict("fn::b", "func_b", "app/b.py")
    fn_c = _make_fn_dict("fn::c", "func_c", "app/c.py")

    functions = {"fn::a": fn_a, "fn::b": fn_b, "fn::c": fn_c}
    callees = {
        "fn::a": [{"id": "fn::b", "confidence": 0.9}],
        "fn::b": [{"id": "fn::a", "confidence": 0.9}, {"id": "fn::c", "confidence": 0.8}],
    }
    http_callees = {}

    store = _make_store(functions, callees, http_callees)
    assembler = PathwayAssembler(store)
    doc = assembler.assemble("fn::a")

    # Must complete without hanging
    assert doc is not None
    # visited guard ensures no function appears twice
    step_ids = [s.function_id for s in doc.steps]
    assert len(step_ids) == len(set(step_ids)), "No function should appear twice in steps"


# ---------------------------------------------------------------------------
# test_http_callee_not_filtered_by_cross_language_guard
# ---------------------------------------------------------------------------


def test_http_callee_not_filtered_by_cross_language_guard():
    """MAKES_HTTP_CALL callees must bypass the cross-language filter that blocks CALLS edges."""
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler

    # Python caller → TypeScript handler: would be blocked by should_skip_cross_language_step
    # for normal CALLS edges, but MAKES_HTTP_CALL must bypass that filter.
    py_entry = _make_fn_dict("fn::py", "call_endpoint", "app/client.py")
    ts_handler = _make_fn_dict("fn::ts", "postHandler", "api/users/route.ts")
    ts_db = _make_fn_dict("fn::ts_db", "insertUser", "api/users/db.ts")

    functions = {"fn::py": py_entry, "fn::ts": ts_handler, "fn::ts_db": ts_db}
    # Only CALLS edge is from ts_handler to ts_db (within TypeScript)
    callees = {"fn::ts": [{"id": "fn::ts_db", "confidence": 0.9}]}
    http_callees = {
        "fn::py": [{"id": "fn::ts", "confidence": 0.85, "http_method": "POST"}],
    }

    store = _make_store(functions, callees, http_callees)
    assembler = PathwayAssembler(store)
    doc = assembler.assemble("fn::py")

    assert doc is not None
    step_ids = [s.function_id for s in doc.steps]
    assert "fn::ts" in step_ids, (
        "TypeScript handler must be included via MAKES_HTTP_CALL "
        "even though it crosses a language boundary"
    )


# ---------------------------------------------------------------------------
# test_http_method_propagated_to_subsequent_steps
# ---------------------------------------------------------------------------


def test_http_method_propagated_correctly():
    """The http_method on a cross_lang_step matches the edge that delivered it."""
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler

    py_fn = _make_fn_dict("fn::py", "submit_form", "web/submit.py")
    ts_fn = _make_fn_dict("fn::ts", "handlePost", "api/form/route.ts")
    ts_save = _make_fn_dict("fn::ts_save", "saveForm", "api/form/db.ts")

    functions = {"fn::py": py_fn, "fn::ts": ts_fn, "fn::ts_save": ts_save}
    callees = {"fn::ts": [{"id": "fn::ts_save", "confidence": 0.9}]}
    http_callees = {
        "fn::py": [{"id": "fn::ts", "confidence": 0.9, "http_method": "POST"}],
    }

    store = _make_store(functions, callees, http_callees)
    assembler = PathwayAssembler(store)
    doc = assembler.assemble("fn::py")

    assert doc is not None
    ts_step = next(s for s in doc.steps if s.function_id == "fn::ts")
    assert ts_step.http_method == "POST"
    assert ts_step.cross_lang_step is True


# ---------------------------------------------------------------------------
# test_same_language_http_callee_still_followed
# ---------------------------------------------------------------------------


def test_same_language_http_callee_still_followed():
    """MAKES_HTTP_CALL edges within the same language (Python→Python) are also followed."""
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler

    py_client = _make_fn_dict("fn::client", "call_internal", "services/client.py")
    py_server = _make_fn_dict("fn::server", "internal_api", "services/api.py")
    py_db = _make_fn_dict("fn::db", "query_data", "services/db.py")

    functions = {"fn::client": py_client, "fn::server": py_server, "fn::db": py_db}
    callees = {"fn::server": [{"id": "fn::db", "confidence": 0.9}]}
    http_callees = {
        "fn::client": [{"id": "fn::server", "confidence": 0.85, "http_method": "GET"}],
    }

    store = _make_store(functions, callees, http_callees)
    assembler = PathwayAssembler(store)
    doc = assembler.assemble("fn::client")

    assert doc is not None
    step_ids = [s.function_id for s in doc.steps]
    assert "fn::server" in step_ids
