"""Unit tests for event topology extraction (IMP-01).

Verifies that:
- Real EventBus calls (EventType.* arg, Event(type=...) arg) are captured.
- False positives (db_path, URL strings, plain names) are rejected.
- Role (publish / subscribe) is correctly assigned.
- Confidence is higher for fully-resolved enum references.

INVARIANT: These tests run without a graph store or filesystem — all inputs
are constructed in-memory via dataclasses.
"""
from __future__ import annotations

from repograph.plugins.static_analyzers.event_topology.plugin import (
    _is_event_arg,
    _resolve_event_type,
    extract_event_topology,
)
from repograph.core.models import CallSite, FileRecord, ParsedFile


# ---------------------------------------------------------------------------
# _is_event_arg unit tests
# ---------------------------------------------------------------------------


def test_event_type_enum_member_accepted():
    assert _is_event_arg("EventType.BAR_CLOSE_1M") is True


def test_event_type_with_spaces_accepted():
    assert _is_event_arg("  EventType.ORDER_FILLED  ") is True


def test_event_constructor_accepted():
    assert _is_event_arg('Event(type=EventType.TRADE_CLOSED, data={})') is True


def test_custom_enum_all_caps_member_accepted():
    assert _is_event_arg("MyEvents.USER_CREATED") is True


def test_db_path_rejected():
    assert _is_event_arg("db_path") is False


def test_fstring_db_rejected():
    assert _is_event_arg('f"file:{db_path}?mode=ro"') is False


def test_self_url_rejected():
    assert _is_event_arg("self.url") is False


def test_str_cast_rejected():
    assert _is_event_arg("str(db_path)") is False


def test_none_rejected():
    assert _is_event_arg("None") is False


def test_integer_rejected():
    assert _is_event_arg("42") is False


def test_empty_string_rejected():
    assert _is_event_arg("") is False


def test_plain_variable_name_rejected():
    assert _is_event_arg("queue") is False


# ---------------------------------------------------------------------------
# _resolve_event_type unit tests
# ---------------------------------------------------------------------------


def test_resolve_enum_member():
    assert _resolve_event_type("EventType.BAR_CLOSE_1M") == "BAR_CLOSE_1M"


def test_resolve_event_constructor():
    result = _resolve_event_type("Event(type=EventType.ORDER_FILLED, data={})")
    assert result == "ORDER_FILLED"


def test_resolve_event_constructor_no_enum():
    result = _resolve_event_type("Event(type=MY_EVENT)")
    assert result == "MY_EVENT"


def test_resolve_fallback():
    result = _resolve_event_type("SomeExpr")
    assert result == "SomeExpr"


# ---------------------------------------------------------------------------
# extract_event_topology integration-level unit tests
# ---------------------------------------------------------------------------


def _make_fr(path: str = "src/test.py") -> FileRecord:
    return FileRecord(
        path=path, abs_path=f"/repo/{path}", name="test.py",
        extension=".py", language="python", size_bytes=100,
        line_count=10, source_hash="abc", is_test=False,
        is_config=False, mtime=0.0,
    )


def _make_pf(call_sites: list[CallSite], path: str = "src/test.py") -> ParsedFile:
    pf = ParsedFile(file_record=_make_fr(path))
    pf.call_sites = call_sites
    return pf


def _site(callee: str, args: list[str], line: int = 1, fid: str = "fn:f") -> CallSite:
    return CallSite(
        caller_function_id=fid,
        callee_text=callee,
        call_site_line=line,
        argument_exprs=args,
        keyword_args={},
        file_path="src/test.py",
    )


class _FakeStore:
    """Minimal stub — extract_event_topology only uses store as a reserved arg."""
    pass


def test_real_subscribe_captured():
    pf = _make_pf([_site("bus.subscribe", ["EventType.BAR_CLOSE_1M", "self._queue"])])
    rows = extract_event_topology(_FakeStore(), [pf])  # type: ignore[arg-type]
    assert len(rows) == 1
    r = rows[0]
    assert r["role"] == "subscribe"
    assert r["event_type"] == "BAR_CLOSE_1M"
    assert r["confidence"] == 0.9


def test_real_publish_captured():
    pf = _make_pf([_site("bus.publish", ['Event(type=EventType.TRADE_CLOSED, data={})'])])
    rows = extract_event_topology(_FakeStore(), [pf])  # type: ignore[arg-type]
    assert len(rows) == 1
    assert rows[0]["role"] == "publish"
    assert rows[0]["event_type"] == "TRADE_CLOSED"


def test_publish_critical_captured():
    pf = _make_pf([_site("self._bus.publish_critical", ['Event(type=EventType.ORDER_FILLED, data={})'])])
    rows = extract_event_topology(_FakeStore(), [pf])  # type: ignore[arg-type]
    assert len(rows) == 1
    assert rows[0]["role"] == "publish"


def test_db_connect_not_captured():
    pf = _make_pf([_site("aiosqlite.connect", ["db_path"])])
    rows = extract_event_topology(_FakeStore(), [pf])  # type: ignore[arg-type]
    assert rows == [], f"Expected no rows, got {rows}"


def test_ws_subscribe_url_not_captured():
    pf = _make_pf([_site("ws_client.subscribe", ["self.url"])])
    rows = extract_event_topology(_FakeStore(), [pf])  # type: ignore[arg-type]
    assert rows == [], f"Expected no rows for URL subscribe, got {rows}"


def test_sqlite_fstring_not_captured():
    pf = _make_pf([_site("sqlite3.connect", ['f"file:{db_path}?mode=ro"'])])
    rows = extract_event_topology(_FakeStore(), [pf])  # type: ignore[arg-type]
    assert rows == []


def test_no_args_not_captured():
    pf = _make_pf([_site("bus.subscribe", [])])
    rows = extract_event_topology(_FakeStore(), [pf])  # type: ignore[arg-type]
    assert rows == []


def test_mixed_real_and_noise():
    """Real EventBus calls are captured; noise calls are filtered out."""
    sites = [
        _site("bus.subscribe", ["EventType.BAR_CLOSE_1M", "q"], line=10),
        _site("aiosqlite.connect", ["db_path"], line=20),
        _site("ws.subscribe", ["self.url"], line=30),
        _site("bus.publish", ['Event(type=EventType.ORDER_FILLED, data={})'], line=40),
        _site("sqlite3.connect", ['f"file:{db}"'], line=50),
    ]
    pf = _make_pf(sites)
    rows = extract_event_topology(_FakeStore(), [pf])  # type: ignore[arg-type]
    assert len(rows) == 2, f"Expected 2 real rows, got {len(rows)}: {rows}"
    types = {r["event_type"] for r in rows}
    assert types == {"BAR_CLOSE_1M", "ORDER_FILLED"}


def test_file_path_propagated():
    pf = _make_pf(
        [_site("bus.subscribe", ["EventType.TICK_PRICE"], fid="fn:bots/bot.py:on_start")],
        path="src/bots/bot.py",
    )
    rows = extract_event_topology(_FakeStore(), [pf])  # type: ignore[arg-type]
    assert rows[0]["file_path"] == "src/bots/bot.py"
    assert rows[0]["function_id"] == "fn:bots/bot.py:on_start"
