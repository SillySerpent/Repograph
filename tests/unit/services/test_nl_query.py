"""Tests for Block I5 — natural language → Cypher query engine."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(rows=None):
    """Return a mock service whose .query() returns *rows*."""
    svc = MagicMock()
    svc.query.return_value = rows or []
    return svc


def _engine(service=None, model="test-model"):
    from repograph.mcp.nl_query import NLQueryEngine
    return NLQueryEngine(service or _make_service(), model=model)


def _anthropic_response(cypher: str, explanation: str = "test"):
    """Return a mock Anthropic response object wrapping a JSON payload."""
    payload = json.dumps({"cypher": cypher, "explanation": explanation})
    content = MagicMock()
    content.text = payload
    resp = MagicMock()
    resp.content = [content]
    return resp


# ---------------------------------------------------------------------------
# I5.1 NLQueryEngine.query — basic translation and execution
# ---------------------------------------------------------------------------


def test_query_returns_rows_on_success():
    """A valid NL question produces cypher, rows, and row_count."""
    svc = _make_service(rows=[["fn::app::foo", "foo"], ["fn::app::bar", "bar"]])
    engine = _engine(svc)
    mock_resp = _anthropic_response("MATCH (f:Function) RETURN f.id, f.name LIMIT 10")

    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = mock_resp
        mock_get_client.return_value = client

        result = engine.query("List all functions")

    assert result["cypher"] is not None
    assert result["row_count"] == 2
    assert result["rows"] == [["fn::app::foo", "foo"], ["fn::app::bar", "bar"]]
    assert result["error"] is None


def test_query_includes_explanation():
    """result['explanation'] must be populated from the model response."""
    engine = _engine()
    mock_resp = _anthropic_response(
        "MATCH (f:Function) RETURN f.id LIMIT 5",
        explanation="Returns all function IDs up to 5",
    )
    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = mock_resp
        mock_get_client.return_value = client
        result = engine.query("show me functions")

    assert result["explanation"] == "Returns all function IDs up to 5"


def test_query_original_question_preserved():
    """result['question'] must echo back the original question."""
    engine = _engine()
    mock_resp = _anthropic_response("MATCH (f:Function) RETURN f.id LIMIT 1")
    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = mock_resp
        mock_get_client.return_value = client
        result = engine.query("What functions exist?")

    assert result["question"] == "What functions exist?"


# ---------------------------------------------------------------------------
# I5.2 Safety guard — write operations refused
# ---------------------------------------------------------------------------


def test_write_query_refused():
    """A Cypher query with CREATE must be refused before execution."""
    engine = _engine()
    mock_resp = _anthropic_response(
        "CREATE (f:Function {id: 'bad'}) RETURN f",
        explanation="Creates a function",
    )
    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = mock_resp
        mock_get_client.return_value = client
        result = engine.query("create a function")

    assert result["error"] is not None
    assert "write" in result["error"].lower() or "refused" in result["error"].lower()
    engine._service.query.assert_not_called()


def test_set_query_refused():
    """A Cypher query with SET must be refused."""
    engine = _engine()
    mock_resp = _anthropic_response("MATCH (f:Function) SET f.is_dead = true")
    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = mock_resp
        mock_get_client.return_value = client
        result = engine.query("mark all functions as dead")

    assert result["error"] is not None
    engine._service.query.assert_not_called()


def test_delete_query_refused():
    """DETACH DELETE must be refused."""
    engine = _engine()
    mock_resp = _anthropic_response("MATCH (f:Function) DETACH DELETE f")
    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = mock_resp
        mock_get_client.return_value = client
        result = engine.query("delete everything")

    assert result["error"] is not None
    engine._service.query.assert_not_called()


# ---------------------------------------------------------------------------
# I5.3 Null cypher — model cannot answer
# ---------------------------------------------------------------------------


def test_null_cypher_returns_error():
    """When the model returns cypher=null, result must have error set."""
    engine = _engine()
    payload = json.dumps({"cypher": None, "explanation": "Cannot answer this question."})
    content = MagicMock()
    content.text = payload
    resp = MagicMock()
    resp.content = [content]

    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = resp
        mock_get_client.return_value = client
        result = engine.query("what is the weather today?")

    assert result["cypher"] is None
    assert result["error"] is not None
    assert result["rows"] == []


# ---------------------------------------------------------------------------
# I5.4 Truncation at MAX_ROWS
# ---------------------------------------------------------------------------


def test_rows_truncated_at_max():
    """Results beyond MAX_ROWS must be truncated and truncated=True."""
    from repograph.mcp.nl_query import MAX_ROWS

    big_rows = [[str(i)] for i in range(MAX_ROWS + 50)]
    svc = _make_service(rows=big_rows)
    engine = _engine(svc)
    mock_resp = _anthropic_response("MATCH (f:Function) RETURN f.id")

    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = mock_resp
        mock_get_client.return_value = client
        result = engine.query("all functions")

    assert result["truncated"] is True
    assert result["row_count"] == MAX_ROWS
    assert len(result["rows"]) == MAX_ROWS


def test_rows_not_truncated_under_limit():
    """Results within MAX_ROWS must have truncated=False."""
    from repograph.mcp.nl_query import MAX_ROWS

    svc = _make_service(rows=[[str(i)] for i in range(MAX_ROWS - 1)])
    engine = _engine(svc)
    mock_resp = _anthropic_response("MATCH (f:Function) RETURN f.id LIMIT 5")

    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = mock_resp
        mock_get_client.return_value = client
        result = engine.query("some functions")

    assert result["truncated"] is False


# ---------------------------------------------------------------------------
# I5.5 Error handling
# ---------------------------------------------------------------------------


def test_missing_anthropic_package_raises_import_error():
    """When anthropic is not installed, _get_client must raise ImportError."""
    import sys
    engine = _engine()
    saved = sys.modules.get("anthropic")
    sys.modules["anthropic"] = None  # type: ignore[assignment]
    try:
        try:
            engine._get_client()
            assert False, "Expected ImportError"
        except ImportError as exc:
            assert "pip install anthropic" in str(exc)
    finally:
        if saved is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = saved


def test_translation_failure_returns_error():
    """An exception during _translate must set result['error'] without raising."""
    engine = _engine()
    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("network error")
        mock_get_client.return_value = client
        result = engine.query("anything")

    assert result["error"] is not None
    assert "network error" in result["error"]
    assert result["rows"] == []


def test_execution_failure_returns_error():
    """A KuzuDB execution error must set result['error'] without raising."""
    svc = _make_service()
    svc.query.side_effect = RuntimeError("binder exception")
    engine = _engine(svc)
    mock_resp = _anthropic_response("MATCH (f:Function) RETURN f.id")

    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = mock_resp
        mock_get_client.return_value = client
        result = engine.query("list functions")

    assert result["error"] is not None
    assert "binder exception" in result["error"]


def test_non_json_model_response_returns_error():
    """A model that returns non-JSON text must produce a clean error."""
    engine = _engine()
    content = MagicMock()
    content.text = "Sorry, I cannot help with that."
    resp = MagicMock()
    resp.content = [content]

    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = resp
        mock_get_client.return_value = client
        result = engine.query("something")

    assert result["error"] is not None


def test_markdown_fences_stripped():
    """Model responses wrapped in ```json fences must be parsed correctly."""
    engine = _engine(_make_service(rows=[["foo"]]))
    payload = json.dumps({"cypher": "MATCH (f:Function) RETURN f.name LIMIT 1", "explanation": "x"})
    content = MagicMock()
    content.text = f"```json\n{payload}\n```"
    resp = MagicMock()
    resp.content = [content]

    with patch.object(engine, "_get_client") as mock_get_client:
        client = MagicMock()
        client.messages.create.return_value = resp
        mock_get_client.return_value = client
        result = engine.query("function names")

    assert result["error"] is None
    assert result["row_count"] == 1
