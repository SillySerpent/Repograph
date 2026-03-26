"""Event topology static analyzer.

Extracts genuine event-bus publish/subscribe call sites from parsed files.

The plugin fires on on_graph_built and exposes extract_event_topology() for
tests and meta JSON writers.
"""
from __future__ import annotations

from repograph.core.models import ParsedFile
from repograph.core.plugin_framework import PluginManifest, StaticAnalyzerPlugin
from repograph.graph_store.store import GraphStore
from repograph.plugins.utils import write_meta_json

_PUBLISH_METHODS = frozenset({"publish", "publish_critical", "emit", "fire", "dispatch", "send_event"})
_SUBSCRIBE_METHODS = frozenset({"subscribe", "add_listener", "add_handler", "listen", "on"})
_ALL_BUS_METHODS = _PUBLISH_METHODS | _SUBSCRIBE_METHODS


def _is_event_arg(expr: str) -> bool:
    s = expr.strip()
    if not s:
        return False
    if "." in s:
        parts = s.split(".")
        last = parts[-1]
        if last and last.replace("_", "").replace("0123456789", "").isupper():
            return True
        if parts[-1].startswith("Event(") or (parts[0][0].isupper() and "(" in s):
            return True
    if s[0].isupper() and s.endswith(")") and "(" in s:
        return True
    return False


def _resolve_event_type(expr: str) -> str:
    s = expr.strip()
    if "type=" in s:
        after = s.split("type=", 1)[1].split(",")[0].split(")")[0].strip()
        return (after.split(".")[-1] if "." in after else after)[:80]
    if "." in s:
        return s.split(".")[-1][:80]
    return s[:80]


def extract_event_topology(store: GraphStore, parsed_files: list[ParsedFile]) -> list[dict]:
    """Extract event-bus publish/subscribe relationships from call sites.

    Only call sites whose first argument is recognisably an event type
    (enum member or event constructor) are included, eliminating false
    positives from DB connections, WebSocket URL subscriptions, etc.
    """
    _ = store
    rows: list[dict] = []
    for pf in parsed_files:
        for site in pf.call_sites:
            bare = site.callee_text.split(".")[-1]
            if bare not in _ALL_BUS_METHODS or not site.argument_exprs:
                continue
            first_arg = site.argument_exprs[0]
            if not _is_event_arg(first_arg):
                continue
            role = "publish" if bare in _PUBLISH_METHODS else "subscribe"
            confidence = 0.9 if ("EventType." in first_arg or ("." in first_arg and first_arg.split(".")[-1].isupper())) else 0.7
            rows.append({
                "function_id": site.caller_function_id,
                "file_path": pf.file_record.path,
                "line": site.call_site_line,
                "role": role,
                "bus_method": bare,
                "event_type": _resolve_event_type(first_arg),
                "event_arg": first_arg[:120],
                "confidence": confidence,
            })
    return rows


class EventTopologyAnalyzerPlugin(StaticAnalyzerPlugin):
    """Detects pub/sub event bus call sites across the codebase."""

    manifest = PluginManifest(
        id="static_analyzer.event_topology",
        name="Event topology analyzer",
        kind="static_analyzer",
        description="Detects pub/sub event-bus publish/subscribe call sites.",
        requires=("call_sites",),
        produces=("findings.event_topology",),
        hooks=("on_graph_built",),
        order=220,
        after=("static_analyzer.pathways",),
    )

    def analyze(self, store: GraphStore | None = None, repograph_dir: str = "", parsed=None, **kwargs) -> list[dict]:
        if store is None:
            service = kwargs.get("service")
            if service is None:
                return []
            return service.event_topology()
        rows = extract_event_topology(store, parsed or [])
        if repograph_dir:
            write_meta_json(repograph_dir, "event_topology.json", rows)
        return rows


def build_plugin() -> EventTopologyAnalyzerPlugin:
    return EventTopologyAnalyzerPlugin()
