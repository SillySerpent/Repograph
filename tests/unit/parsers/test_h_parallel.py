"""Tests for Block H — parallel parsing, batch writes, parallel phases."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# H1: Thread-local parser (BaseParser.parser property)
# ---------------------------------------------------------------------------


def test_parser_property_returns_per_thread_instance():
    """Different threads must get different ts.Parser instances."""
    from repograph.plugins.parsers.python.python_parser import PythonParser

    p = PythonParser()
    instances: list[object] = []

    def get_parser():
        instances.append(p.parser)

    t1 = threading.Thread(target=get_parser)
    t2 = threading.Thread(target=get_parser)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(instances) == 2
    # Each thread got its own instance — they must be different objects
    assert instances[0] is not instances[1], (
        "Thread-local storage must produce separate ts.Parser instances per thread"
    )


def test_parser_property_same_thread_returns_same_instance():
    """Within a single thread, the same ts.Parser instance is reused."""
    from repograph.plugins.parsers.python.python_parser import PythonParser

    p = PythonParser()
    inst_a = p.parser
    inst_b = p.parser
    assert inst_a is inst_b, "Repeated access in same thread must return cached instance"


def test_different_parser_subclasses_get_separate_slots():
    """Different parser subclass instances must not share the same thread-local slot."""
    from repograph.plugins.parsers.python.python_parser import PythonParser
    from repograph.plugins.parsers.javascript.javascript_parser import JavaScriptParser

    py = PythonParser()
    js = JavaScriptParser()
    assert py.parser is not js.parser, (
        "Python and JavaScript parsers must have separate thread-local slots"
    )


# ---------------------------------------------------------------------------
# H1: Parallel parse in p03_parse._parse_files_parallel
# ---------------------------------------------------------------------------


def _make_file_record(path: str, language: str = "python"):
    from repograph.core.models import FileRecord
    return FileRecord(
        path=path, abs_path=path, name=Path(path).name,
        extension=Path(path).suffix, language=language,
        size_bytes=0, line_count=5, source_hash="x",
        is_test=False, is_config=False, mtime=0.0,
    )


def test_parse_files_parallel_returns_results_in_order():
    """_parse_files_parallel must return ParsedFile results in the same order as input."""
    from repograph.pipeline.phases.p03_parse import _parse_files_parallel
    from repograph.core.models import ParsedFile

    files = [_make_file_record(f"app/module_{i}.py") for i in range(10)]

    with patch("repograph.pipeline.phases.p03_parse._parse_one_file") as mock_parse:
        mock_parse.side_effect = lambda fr: ParsedFile(file_record=fr)
        results = _parse_files_parallel(files)

    assert len(results) == 10
    for i, (fr, pf) in enumerate(zip(files, results)):
        assert pf.file_record.path == fr.path, (
            f"Result at index {i} has wrong file_record — order was not preserved"
        )


def test_parse_files_parallel_handles_exception_gracefully():
    """A parsing failure must produce an empty ParsedFile, not crash the phase."""
    from repograph.pipeline.phases.p03_parse import _parse_files_parallel
    from repograph.core.models import ParsedFile

    files = [_make_file_record("app/bad.py"), _make_file_record("app/good.py")]

    def side_effect(fr):
        if "bad" in fr.path:
            raise ValueError("simulated parse error")
        return ParsedFile(file_record=fr)

    with patch("repograph.pipeline.phases.p03_parse._parse_one_file",
               side_effect=side_effect):
        results = _parse_files_parallel(files)

    assert len(results) == 2
    # The bad file should produce an empty ParsedFile (not raise)
    assert results[0].file_record.path == "app/bad.py"
    assert results[1].file_record.path == "app/good.py"
    assert results[1].functions == []  # good file is also empty since we return ParsedFile(fr)


# ---------------------------------------------------------------------------
# H2: batch_upsert_functions / batch_upsert_classes
# ---------------------------------------------------------------------------


def _make_fn(fn_id: str, name: str, file_path: str):
    from repograph.core.models import FunctionNode
    return FunctionNode(
        id=fn_id, name=name, qualified_name=name,
        file_path=file_path, line_start=1, line_end=5,
        signature=f"def {name}()", docstring=None,
        is_method=False, is_async=False, is_exported=True,
        decorators=[], param_names=[], return_type=None, source_hash="x",
    )


def _make_cls(cls_id: str, name: str, file_path: str):
    from repograph.core.models import ClassNode
    return ClassNode(
        id=cls_id, name=name, qualified_name=name,
        file_path=file_path, line_start=1, line_end=10,
        docstring=None, base_names=[], is_exported=True, source_hash="x",
    )


def test_batch_upsert_functions_calls_upsert_for_each(tmp_path):
    """batch_upsert_functions must call upsert_function once per function node."""
    from repograph.graph_store.store import GraphStore

    db = str(tmp_path / "g.db")
    store = GraphStore(db)
    store.initialize_schema()

    fns = [_make_fn(f"fn::{i}", f"func_{i}", "app/a.py") for i in range(5)]
    store.batch_upsert_functions(fns)

    # Verify all functions are in the DB
    rows = store.query("MATCH (f:Function) RETURN f.id ORDER BY f.id")
    ids_in_db = {r[0] for r in rows}
    for fn in fns:
        assert fn.id in ids_in_db, f"Function {fn.id} not found after batch_upsert_functions"

    store.close()


def test_batch_upsert_classes_calls_upsert_for_each(tmp_path):
    """batch_upsert_classes must upsert each ClassNode to the DB."""
    from repograph.graph_store.store import GraphStore

    db = str(tmp_path / "g.db")
    store = GraphStore(db)
    store.initialize_schema()

    classes = [_make_cls(f"cls::{i}", f"MyClass{i}", "app/a.py") for i in range(3)]
    store.batch_upsert_classes(classes)

    rows = store.query("MATCH (c:Class) RETURN c.id ORDER BY c.id")
    ids_in_db = {r[0] for r in rows}
    for cls in classes:
        assert cls.id in ids_in_db, f"Class {cls.id} not found after batch_upsert_classes"

    store.close()


def test_batch_vs_sequential_upsert_identical_db_state(tmp_path):
    """Batch and sequential upserts must produce identical DB state."""
    from repograph.graph_store.store import GraphStore

    fns = [_make_fn(f"fn::{i}", f"func_{i}", "app/a.py") for i in range(8)]

    # Sequential
    db_seq = str(tmp_path / "seq.db")
    store_seq = GraphStore(db_seq)
    store_seq.initialize_schema()
    for fn in fns:
        store_seq.upsert_function(fn)
    seq_rows = sorted(store_seq.query("MATCH (f:Function) RETURN f.id, f.name"))
    store_seq.close()

    # Batch
    db_batch = str(tmp_path / "batch.db")
    store_batch = GraphStore(db_batch)
    store_batch.initialize_schema()
    store_batch.batch_upsert_functions(fns)
    batch_rows = sorted(store_batch.query("MATCH (f:Function) RETURN f.id, f.name"))
    store_batch.close()

    assert seq_rows == batch_rows, (
        "batch_upsert_functions must produce identical DB state to sequential upserts"
    )


def test_batch_upsert_functions_empty_list_is_no_op(tmp_path):
    """batch_upsert_functions with an empty list must not raise and leave DB unchanged."""
    from repograph.graph_store.store import GraphStore

    db = str(tmp_path / "g.db")
    store = GraphStore(db)
    store.initialize_schema()
    store.batch_upsert_functions([])
    rows = store.query("MATCH (f:Function) RETURN count(f)")
    assert rows[0][0] == 0
    store.close()


# ---------------------------------------------------------------------------
# H3: _run_phases_parallel — parallel phase execution
# ---------------------------------------------------------------------------


def test_run_phases_parallel_calls_all_phases():
    """_run_phases_parallel must invoke all 8 core phases."""
    from repograph.pipeline.runner import _run_phases_parallel, RunConfig

    config = RunConfig(
        repo_root="/tmp", repograph_dir="/tmp/.repograph",
        include_git=False, full=True,
    )
    store = MagicMock()
    symbol_table = MagicMock()
    parsed = []

    phase_calls = []

    def make_run(name):
        def run(*args, **kwargs):
            phase_calls.append(name)
        return run

    # Patch all the phases to track calls
    import repograph.pipeline.phases.p04_imports as p04
    import repograph.pipeline.phases.p05_calls as p05
    import repograph.pipeline.phases.p05b_callbacks as p05b
    import repograph.pipeline.phases.p05c_http_calls as p05c
    import repograph.pipeline.phases.p06_heritage as p06
    import repograph.pipeline.phases.p06b_layer_classify as p06b
    import repograph.pipeline.phases.p07_variables as p07
    import repograph.pipeline.phases.p08_types as p08

    patches = [
        patch.object(p04, "run", make_run("p04")),
        patch.object(p05, "run", make_run("p05")),
        patch.object(p05b, "run", make_run("p05b")),
        patch.object(p05c, "run", make_run("p05c")),
        patch.object(p06, "run", make_run("p06")),
        patch.object(p06b, "run", make_run("p06b")),
        patch.object(p07, "run", make_run("p07")),
        patch.object(p08, "run", make_run("p08")),
    ]
    for p in patches:
        p.start()

    try:
        _run_phases_parallel(config, parsed, store, symbol_table)
    finally:
        for p in patches:
            p.stop()

    called = set(phase_calls)
    assert "p04" in called
    assert "p05" in called
    assert "p05b" in called
    assert "p05c" in called
    assert "p06" in called
    assert "p06b" in called
    assert "p07" in called
    assert "p08" in called


def test_run_phases_parallel_phase_failure_handled():
    """A phase failure with continue_on_error must not prevent other phases from completing."""
    from repograph.pipeline.runner import _run_phases_parallel, RunConfig

    config = RunConfig(
        repo_root="/tmp", repograph_dir="/tmp/.repograph",
        include_git=False, full=True, continue_on_error=True,
    )
    store = MagicMock()
    symbol_table = MagicMock()
    parsed = []

    completed: list[str] = []

    import repograph.pipeline.phases.p04_imports as p04
    import repograph.pipeline.phases.p05_calls as p05
    import repograph.pipeline.phases.p05b_callbacks as p05b
    import repograph.pipeline.phases.p05c_http_calls as p05c
    import repograph.pipeline.phases.p06_heritage as p06
    import repograph.pipeline.phases.p06b_layer_classify as p06b
    import repograph.pipeline.phases.p07_variables as p07
    import repograph.pipeline.phases.p08_types as p08

    def fail(*args, **kwargs):
        raise RuntimeError("intentional failure")

    def succeed(name):
        def _run(*args, **kwargs):
            completed.append(name)
        return _run

    patches = [
        patch.object(p04, "run", fail),
        patch.object(p05, "run", succeed("p05")),
        patch.object(p05b, "run", succeed("p05b")),
        patch.object(p05c, "run", succeed("p05c")),
        patch.object(p06, "run", succeed("p06")),
        patch.object(p06b, "run", succeed("p06b")),
        patch.object(p07, "run", succeed("p07")),
        patch.object(p08, "run", succeed("p08")),
    ]
    for p in patches:
        p.start()

    try:
        _run_phases_parallel(config, parsed, store, symbol_table)
    finally:
        for p in patches:
            p.stop()

    # All non-failing phases should have completed
    assert "p05" in completed
    assert "p06" in completed
    assert "p07" in completed
