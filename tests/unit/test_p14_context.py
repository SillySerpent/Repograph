"""Phase 14 prose vs code disambiguation."""
from repograph.pipeline.phases.p14_context import should_skip_moved_reference_for_prose


def test_skip_symbol_in_audit_table_row():
    line = (
        "| FIX-001 | High | `storage/schema.py`, `storage/writer.py` | "
        "Added `symbol` + `advisor_compute_ms` columns to `advisor_decisions` table"
    )
    assert should_skip_moved_reference_for_prose(line, "symbol") is True


def test_do_not_skip_symbol_in_architecture_doc():
    line = "The `symbol` registry lives in `src/market/models.py` only."
    assert should_skip_moved_reference_for_prose(line, "symbol") is False


def test_non_ambiguous_token():
    line = "| x | Added `SelfTunerManager` | column foo |"
    assert should_skip_moved_reference_for_prose(line, "SelfTunerManager") is False
