"""Natural language → Cypher query translator for the RepoGraph MCP layer (Block I5).

Translates a plain-English question about the codebase into a KuzuDB Cypher query
using the Anthropic API, executes it against the graph, and returns structured results.

Usage (direct)::

    from repograph.surfaces.mcp.nl_query import NLQueryEngine

    engine = NLQueryEngine(service)
    result = engine.query("Which functions in the api layer have never been covered by tests?")
    print(result["cypher"])
    print(result["rows"])

The ``anthropic`` package is an optional runtime dependency.  The tool raises
``ImportError`` with a clear install message when it is absent.

Design constraints
------------------
- The translator never executes arbitrary Cypher from user input directly. The
  model is constrained to return only ``MATCH … RETURN`` queries (read-only).
  Any generated query containing ``CREATE``, ``SET``, ``DELETE``, or ``MERGE``
  is rejected before execution.
- The system prompt is schema-derived and fully inline — no network requests
  beyond the single Anthropic API call.
- Results are capped at ``MAX_ROWS = 200`` rows to prevent OOM on large graphs.
- The Anthropic model defaults to ``claude-haiku-4-5-20251001`` for low-latency
  translation, but is overridable via ``REPOGRAPH_NL_MODEL`` env var.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="mcp")

MAX_ROWS = 200

# ---------------------------------------------------------------------------
# Cypher safety guard
# ---------------------------------------------------------------------------

_WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|SET|DELETE|MERGE|DETACH|REMOVE|DROP)\b",
    re.IGNORECASE,
)


def _is_read_only(cypher: str) -> bool:
    """Return True when the query contains no write-mode keywords."""
    return not bool(_WRITE_KEYWORDS.search(cypher))


# ---------------------------------------------------------------------------
# Schema context fed to the model
# ---------------------------------------------------------------------------

_SCHEMA_SUMMARY = """\
KuzuDB graph schema for a code-intelligence repository called RepoGraph.

Node types and their key properties:
- File(id, path, language, size_bytes, line_count, is_test, is_config, layer)
- Folder(id, path, name, depth)
- Function(id, name, qualified_name, file_path, line_start, line_end,
           is_method, is_async, is_exported, is_entry_point, entry_score,
           is_dead, dead_code_tier, dead_code_reason, community_id,
           runtime_observed, runtime_observed_calls, is_covered,
           layer, role, http_method, route_path, is_test)
- Class(id, name, qualified_name, file_path, base_names, is_exported,
        community_id, is_type_referenced)
- Variable(id, name, function_id, file_path, line_number, inferred_type,
           is_parameter, is_return)
- Import(id, file_path, module_path, resolved_path, imported_names, is_wildcard)
- Pathway(id, name, description, entry_function, step_count, confidence)
- Community(id, label, cohesion, member_count)
- DuplicateSymbol(id, name, kind, occurrence_count, severity)
- DocWarning(id, doc_path, symbol_text, warning_type, severity)

Relationship types:
- (Folder)-[:CONTAINS]->(File)
- (File)-[:IN_FOLDER]->(Folder)
- (File)-[:IMPORTS {confidence, line_number}]->(File)
- (Function)-[:CALLS {call_site_line, confidence, reason}]->(Function)
- (Variable)-[:FLOWS_INTO {confidence}]->(Variable)
- (File)-[:DEFINES]->(Function)
- (File)-[:DEFINES_CLASS]->(Class)
- (Class)-[:HAS_METHOD]->(Function)
- (Class)-[:EXTENDS {confidence}]->(Class)
- (Class)-[:IMPLEMENTS {confidence}]->(Class)
- (Function)-[:MEMBER_OF]->(Community)
- (Class)-[:CLASS_IN]->(Community)
- (Function)-[:STEP_IN_PATHWAY {step_order, role}]->(Pathway)
- (Function)-[:MAKES_HTTP_CALL {http_method, url_pattern, confidence}]->(Function)
- (Function)-[:COUPLED_WITH {coupling_score}]->(Function)

Enum values:
  Function.layer: "db", "persistence", "business_logic", "api", "ui", "util", "unknown"
  Function.role: "repository", "service", "controller", "handler", "page", "component", "util", "model", "unknown"
  Function.dead_code_tier: "definitely_dead", "probably_dead", "possibly_dead", ""
  DuplicateSymbol.severity: "high", "medium", "low"

Query language: KuzuDB Cypher (OpenCypher subset).
- Use single quotes for string literals.
- Use $param syntax for parameter placeholders.
- LIMIT results to at most 50 unless the user asks for more.
- RETURN only the columns the user actually needs.
"""

_SYSTEM_PROMPT = f"""\
You are a KuzuDB Cypher query generator for a code graph.

{_SCHEMA_SUMMARY}

Rules:
1. Respond with ONLY a JSON object with these fields:
   - "cypher": the Cypher query string (read-only MATCH…RETURN only)
   - "explanation": one sentence describing what the query does
2. Do NOT include CREATE, SET, DELETE, MERGE, DETACH, or REMOVE in the query.
3. If the question cannot be answered with the available schema, set
   "cypher" to null and explain why in "explanation".
4. Always add LIMIT unless the user explicitly asks for all results.
"""


# ---------------------------------------------------------------------------
# NLQueryEngine
# ---------------------------------------------------------------------------


class NLQueryEngine:
    """Translates natural-language questions to Cypher and executes them.

    Parameters
    ----------
    service:
        An open ``RepoGraphService`` instance used to execute the generated query.
    model:
        Anthropic model ID. Defaults to the ``REPOGRAPH_NL_MODEL`` env var or
        ``claude-haiku-4-5-20251001``.
    max_tokens:
        Maximum tokens for the translation response (small — JSON only).
    """

    def __init__(
        self,
        service: Any,
        *,
        model: str | None = None,
        max_tokens: int = 512,
    ) -> None:
        self._service = service
        self._model = (
            model
            or os.environ.get("REPOGRAPH_NL_MODEL")
            or "claude-haiku-4-5-20251001"
        )
        self._max_tokens = max_tokens

    def _get_client(self):
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "anthropic package is required for natural-language queries. "
                "Install it with: pip install anthropic"
            ) from exc
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Set it to use natural-language graph queries."
            )
        return anthropic.Anthropic(api_key=api_key)

    def _translate(self, question: str) -> dict[str, str | None]:
        """Call the Anthropic API and return {cypher, explanation}."""
        client = self._get_client()
        response = client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if model wraps response
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Model returned non-JSON response: {raw[:200]}"
            ) from exc

    def query(self, question: str) -> dict[str, Any]:
        """Translate *question* to Cypher, execute, and return results.

        Returns
        -------
        dict with keys:
            - ``question``: the original question
            - ``cypher``: the generated Cypher (or None)
            - ``explanation``: model's description of the query
            - ``rows``: list of result rows (each a list of values)
            - ``columns``: column names when available (list[str] or None)
            - ``row_count``: number of rows returned
            - ``truncated``: True if results were capped at MAX_ROWS
            - ``error``: error message if translation or execution failed
        """
        result: dict[str, Any] = {
            "question": question,
            "cypher": None,
            "explanation": None,
            "rows": [],
            "columns": None,
            "row_count": 0,
            "truncated": False,
            "error": None,
        }

        # Step 1: translate
        try:
            translation = self._translate(question)
        except Exception as exc:
            _logger.warning("nl_query: translation failed", exc_msg=str(exc))
            result["error"] = str(exc)
            return result

        cypher = translation.get("cypher")
        explanation = translation.get("explanation", "")
        result["cypher"] = cypher
        result["explanation"] = explanation

        if not cypher:
            result["error"] = explanation or "Model could not generate a query for this question."
            return result

        # Step 2: safety check
        if not _is_read_only(cypher):
            result["error"] = (
                "Generated query contains write operations — execution refused for safety."
            )
            result["cypher"] = cypher  # keep for inspection
            return result

        # Step 3: execute
        try:
            rows = self._service.query(cypher)
        except Exception as exc:
            _logger.warning("nl_query: query execution failed", cypher=cypher, exc_msg=str(exc))
            result["error"] = f"Query execution failed: {exc}"
            return result

        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]

        result["rows"] = [list(row) for row in rows]
        result["row_count"] = len(rows)
        result["truncated"] = truncated

        _logger.info(
            "nl_query: executed",
            question_len=len(question),
            row_count=len(rows),
            truncated=truncated,
        )
        return result
