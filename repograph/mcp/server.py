"""MCP server for RepoGraph backed by the shared service layer.

:class:`~repograph.services.repo_graph_service.RepoGraphService` provides the
data; this module registers a **small** set of FastMCP tools and resources.
It does not mirror every CLI command (no ``sync``, ``full_report``, etc. by
default). See ``docs/SURFACES.md`` for the tool list and defaults.
"""
from __future__ import annotations

import json

from repograph.services import RepoGraphService
from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="mcp")


def create_server(service: RepoGraphService, *, port: int | None = None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # pragma: no cover - optional dep path
        raise ImportError(
            "mcp package not installed. Install with: pip install 'mcp[cli]'"
        ) from e

    mcp = FastMCP("repograph", port=port if port is not None else 8000)

    @mcp.tool()
    def list_pathways() -> list[dict]:
        """Return all pathway names, descriptions, and confidence scores."""
        return service.pathways(min_confidence=0.0, include_tests=True)

    @mcp.tool()
    def get_pathway(name: str) -> str:
        """Return the full preformatted context document for a named pathway."""
        ctx = service.pathway_document(name)
        if ctx is None:
            return f"Pathway '{name}' not found. Call list_pathways() to see available pathways."
        return ctx

    @mcp.tool()
    def get_node(identifier: str) -> dict:
        """Return structured data for a file path or qualified symbol name."""
        return service.node(identifier) or {"error": f"No node found for '{identifier}'"}

    @mcp.tool()
    def get_dependents(symbol: str, depth: int = 3) -> dict:
        """Return all functions that directly or transitively call this symbol."""
        return service.dependents(symbol, depth=depth)

    @mcp.tool()
    def get_dependencies(symbol: str, depth: int = 3) -> dict:
        """Return all functions this symbol calls, transitively."""
        return service.dependencies(symbol, depth=depth)

    @mcp.tool()
    def search(query: str, limit: int = 10) -> list[dict]:
        """Search by concept, keyword, or symbol name."""
        return service.search(query, limit=limit)

    @mcp.tool()
    def impact(symbol: str, min_confidence: float = 0.5) -> dict:
        """Return blast-radius style data with stable keys: will_break, may_break, warnings."""
        data = service.impact(symbol)
        if data.get("error"):
            return {
                "symbol": symbol,
                "error": data["error"],
                "will_break": [],
                "may_break": [],
                "warnings": list(data.get("warnings") or []),
            }
        if data.get("ambiguous"):
            return {
                "symbol": symbol,
                "ambiguous": True,
                "matches": list(data.get("matches") or []),
                "will_break": [],
                "may_break": [],
                "warnings": list(data.get("warnings") or []),
            }
        direct = data.get("direct_callers") or []
        return {
            "symbol": data.get("symbol", symbol),
            "will_break": [c for c in direct if c.get("confidence", 0) >= min_confidence],
            "may_break": list(data.get("transitive_callers") or []),
            "warnings": list(data.get("warnings") or []),
        }

    @mcp.tool()
    def trace_variable(variable_name: str) -> dict:
        """Trace how a named variable flows through the graph (variables + FLOWS_INTO edges)."""
        return service.trace_variable(variable_name)

    @mcp.tool()
    def get_entry_points(limit: int = 20) -> list[dict]:
        """Return the top entry points by score."""
        return service.entry_points(limit=limit)

    @mcp.tool()
    def get_dead_code() -> list[dict]:
        """Return dead-code findings using the same default tier as :meth:`RepoGraphService.dead_code` (probably_dead)."""
        return service.dead_code()

    @mcp.resource("repograph://overview")
    def overview() -> str:
        return json.dumps(service.status(), indent=2)

    @mcp.resource("repograph://pathways")
    def pathways_resource() -> str:
        pathways = service.pathways(min_confidence=0.0, include_tests=True)
        return json.dumps(
            [{"name": p["name"], "description": p.get("description", ""), "confidence": p.get("confidence", 0.0)} for p in pathways],
            indent=2,
        )

    @mcp.resource("repograph://communities")
    def communities_resource() -> str:
        return json.dumps(service.communities(), indent=2)

    # ── Observability log access tools ─────────────────────────────────────

    @mcp.tool()
    def list_log_sessions() -> list[dict]:
        """List available observability log sessions (run_ids, timestamps, record counts)."""
        return service.list_log_sessions()

    @mcp.tool()
    def get_errors(run_id: str = "") -> list[dict]:
        """Return recent ERROR and CRITICAL log records for the given run (empty = latest)."""
        _logger.info("mcp tool: get_errors", run_id=run_id or "latest")
        return service.get_recent_errors(run_id=run_id or None)

    @mcp.tool()
    def get_log_subsystem(subsystem: str, run_id: str = "") -> list[dict]:
        """Return log records for one subsystem (pipeline, parsers, graph_store, …)."""
        _logger.info("mcp tool: get_log_subsystem", subsystem=subsystem, run_id=run_id or "latest")
        return service.get_log_session(run_id=run_id or None, subsystem=subsystem)

    # ── Natural language query (Block I5) ───────────────────────────────────

    @mcp.tool()
    def query_graph(question: str, model: str = "") -> dict:
        """Translate a plain-English question about the codebase into Cypher and return results.

        Requires the ``anthropic`` package and a valid ``ANTHROPIC_API_KEY`` env var.
        The query is always read-only — write operations are refused before execution.

        Parameters
        ----------
        question:
            Natural-language question about the codebase, e.g.
            "Which API layer functions have never been covered by tests?"
        model:
            Optional Anthropic model override. Leave empty to use the default
            (``REPOGRAPH_NL_MODEL`` env var, or claude-haiku-4-5-20251001).
        """
        from repograph.mcp.nl_query import NLQueryEngine
        _logger.info("mcp tool: query_graph", question_len=len(question))
        engine = NLQueryEngine(service, model=model or None)
        return engine.query(question)

    # ── Schema / registry resources ─────────────────────────────────────────

    @mcp.resource("repograph://schema")
    def schema_resource() -> str:
        return json.dumps(
            {
                "modules": service.modules(),
                "config_registry": service.config_registry(),
                "invariants": service.invariants(),
            },
            indent=2,
        )

    return mcp
