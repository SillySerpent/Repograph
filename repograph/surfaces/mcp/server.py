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
    """Create and return a FastMCP server wired to *service*.

    Parameters
    ----------
    service:
        An open ``RepoGraphService`` instance that provides graph data.
    port:
        Optional HTTP port for streamable-HTTP transport. When None (default),
        the server uses stdio transport.

    Returns
    -------
    FastMCP instance with all tools and resources registered. Call
    ``.run()`` or ``.run(transport="streamable-http")`` to start serving.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # pragma: no cover - optional dep path
        raise ImportError(
            "mcp package not installed. Install with: pip install 'mcp[cli]'"
        ) from e

    mcp = FastMCP("repograph", port=port if port is not None else 8000)

    def _log_tool_call(tool: str, **metadata) -> None:
        service._ensure_observability_session()
        _logger.info("mcp tool invoked", tool=tool, **metadata)

    @mcp.tool()
    def list_pathways() -> list[dict]:
        """Return all pathway names, descriptions, and confidence scores."""
        _log_tool_call("list_pathways")
        return service.pathways(min_confidence=0.0, include_tests=True)

    @mcp.tool()
    def get_pathway(name: str) -> str:
        """Return the full preformatted context document for a named pathway."""
        _log_tool_call("get_pathway", pathway_name=name)
        ctx = service.pathway_document(name)
        if ctx is None:
            return f"Pathway '{name}' not found. Call list_pathways() to see available pathways."
        return ctx

    @mcp.tool()
    def get_node(identifier: str) -> dict:
        """Return structured data for a file path or qualified symbol name."""
        _log_tool_call("get_node", identifier_len=len(identifier))
        return service.node(identifier) or {"error": f"No node found for '{identifier}'"}

    @mcp.tool()
    def get_dependents(symbol: str, depth: int = 3) -> dict:
        """Return all functions that directly or transitively call this symbol."""
        _log_tool_call("get_dependents", symbol_len=len(symbol), depth=int(depth))
        return service.dependents(symbol, depth=depth)

    @mcp.tool()
    def get_dependencies(symbol: str, depth: int = 3) -> dict:
        """Return all functions this symbol calls, transitively."""
        _log_tool_call("get_dependencies", symbol_len=len(symbol), depth=int(depth))
        return service.dependencies(symbol, depth=depth)

    @mcp.tool()
    def search(query: str, limit: int = 10) -> list[dict]:
        """Search by keyword or symbol name via the service lookup path."""
        _log_tool_call("search", query_len=len(query), limit=int(limit))
        return service.search(query, limit=limit)

    @mcp.tool()
    def impact(symbol: str, min_confidence: float = 0.5) -> dict:
        """Return blast-radius data with stable keys: will_break, may_break, warnings."""
        _log_tool_call("impact", symbol_len=len(symbol), min_confidence=float(min_confidence))
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
        _log_tool_call("trace_variable", variable_name_len=len(variable_name))
        return service.trace_variable(variable_name)

    @mcp.tool()
    def get_entry_points(limit: int | None = None) -> list[dict]:
        """Return the top entry points by score.

        When omitted, the shared service uses the configured ``entry_point_limit``
        setting for this repository.
        """
        _log_tool_call("get_entry_points", limit="default" if limit is None else int(limit))
        if limit is None:
            return service.entry_points()
        return service.entry_points(limit=limit)

    @mcp.tool()
    def get_dead_code() -> list[dict]:
        """Return dead-code findings (default tier: probably_dead)."""
        _log_tool_call("get_dead_code")
        return service.dead_code()

    @mcp.tool()
    def get_config(key: str) -> dict:
        """Return the current value of a RepoGraph setting.

        Parameters
        ----------
        key:
            Setting name, e.g. ``auto_dynamic_analysis``, ``exclude_dirs``.
            Pass an empty string to list all settings.
        """
        _log_tool_call("get_config", key=key)
        from repograph.settings import get_setting, load_settings
        from dataclasses import asdict
        if not key:
            return asdict(load_settings(service.repo_path))
        try:
            return {"key": key, "value": get_setting(service.repo_path, key)}
        except KeyError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def describe_config(key: str = "") -> dict | list[dict]:
        """Return setting schema/lifecycle details.

        Pass an empty string to describe all known settings.
        """
        _log_tool_call("describe_config", key=key)
        from repograph.settings import describe_setting, list_setting_metadata

        if not key:
            return list_setting_metadata(service.repo_path)
        try:
            return describe_setting(service.repo_path, key)
        except KeyError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def set_config(key: str, value: str) -> dict:
        """Persist a RepoGraph setting change.

        Changes are written to ``.repograph/settings.json`` and take effect
        immediately. Pass a JSON-encoded value for lists and booleans,
        e.g. ``'["vendor", "dist"]'`` for exclude_dirs.
        """
        _log_tool_call("set_config", key=key)
        from repograph.settings import set_setting
        import json as _json
        try:
            parsed = _json.loads(value)
        except (ValueError, TypeError):
            parsed = value
        try:
            set_setting(service.repo_path, key, parsed)
            return {"key": key, "value": parsed, "status": "saved"}
        except (KeyError, ValueError) as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def unset_config(key: str) -> dict:
        """Remove a runtime override for a setting."""
        _log_tool_call("unset_config", key=key)
        from repograph.settings import unset_setting

        try:
            unset_setting(service.repo_path, key)
            return {"key": key, "status": "cleared"}
        except KeyError as exc:
            return {"error": str(exc)}

    @mcp.resource("repograph://overview")
    def overview() -> str:
        _log_tool_call("overview")
        return json.dumps(service.status(), indent=2)

    @mcp.resource("repograph://pathways")
    def pathways_resource() -> str:
        _log_tool_call("pathways_resource")
        pathways = service.pathways(min_confidence=0.0, include_tests=True)
        return json.dumps(
            [
                {
                    "name": p["name"],
                    "description": p.get("description", ""),
                    "confidence": p.get("confidence", 0.0),
                }
                for p in pathways
            ],
            indent=2,
        )

    @mcp.resource("repograph://communities")
    def communities_resource() -> str:
        _log_tool_call("communities_resource")
        return json.dumps(service.communities(), indent=2)

    @mcp.resource("repograph://settings")
    def settings_resource() -> str:
        """Current effective settings for this repository."""
        _log_tool_call("settings_resource")
        from repograph.settings import load_settings
        from dataclasses import asdict
        return json.dumps(asdict(load_settings(service.repo_path)), indent=2)

    # ── Observability log access tools ─────────────────────────────────────

    @mcp.tool()
    def list_log_sessions() -> list[dict]:
        """List available observability log sessions (run_ids, timestamps, record counts)."""
        _log_tool_call("list_log_sessions")
        return service.list_log_sessions()

    @mcp.tool()
    def get_errors(run_id: str = "") -> list[dict]:
        """Return recent ERROR and CRITICAL log records for the given run (empty = latest)."""
        _log_tool_call("get_errors", run_id=run_id or "latest")
        return service.get_recent_errors(run_id=run_id or None)

    @mcp.tool()
    def get_log_subsystem(subsystem: str, run_id: str = "") -> list[dict]:
        """Return log records for one subsystem (pipeline, parsers, graph_store, …)."""
        _log_tool_call("get_log_subsystem", subsystem=subsystem, run_id=run_id or "latest")
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
            Natural-language question, e.g.
            "Which API layer functions have never been covered by tests?"
        model:
            Optional Anthropic model override. Leave empty to use the
            configured default (``REPOGRAPH_NL_MODEL`` env var, or the
            ``nl_model`` setting).
        """
        from repograph.surfaces.mcp.nl_query import NLQueryEngine
        _log_tool_call("query_graph", question_len=len(question), model=model or "")
        engine = NLQueryEngine(service, model=model or None)
        return engine.query(question)

    # ── Schema / registry resources ─────────────────────────────────────────

    @mcp.resource("repograph://schema")
    def schema_resource() -> str:
        _log_tool_call("schema_resource")
        return json.dumps(
            {
                "modules": service.modules(),
                "config_registry": service.config_registry(),
                "invariants": service.invariants(),
            },
            indent=2,
        )

    return mcp
