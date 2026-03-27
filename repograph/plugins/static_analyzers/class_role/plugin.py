"""Class role analyzer — static analyzer plugin (Block G2).

Classifies classes into roles (repository, service, controller, handler,
page, component, util, model, unknown) using:

  1. Inheritance base-name heuristics (highest priority)
  2. Method name pattern heuristics
  3. File-path heuristics (fallback)

For each classified class, all of its methods (HAS_METHOD edges) are updated
with the class's role so the graph can answer "show me all repository methods".

Plugin contract
---------------
  kind:  static_analyzer
  hook:  on_graph_built
  input: store (GraphStore)
  output: None (side effects: update_function_layer_role calls)

All classification rules live in ``repograph.plugins.layer_rules``; this
plugin reads them.  Rule logic does not belong here.
"""
from __future__ import annotations

import logging
import os
import re

from repograph.core.plugin_framework import PluginManifest, StaticAnalyzerPlugin
from repograph.graph_store.store import GraphStore
from repograph.plugins.layer_rules import (
    INHERIT_ROLE_RULES,
    PATH_LAYER_RULES,
    PATH_ROLE_RULES,
    VALID_ROLES,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Method-name heuristics — patterns that suggest a particular role
# ---------------------------------------------------------------------------
# Checked against *all* method names in the class.  The first matching pattern
# determines the role (unless inheritance already resolved it).

_METHOD_ROLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Persistence / repository patterns
    (re.compile(r"^(get_by_\w+|find_by_\w+|save|delete|insert|update|upsert|find_all|list_all)$"), "repository"),
    (re.compile(r"^(create|bulk_create|bulk_delete|filter|exists|count)$"), "repository"),
    # Service patterns
    (re.compile(r"^(process|execute|handle|dispatch|validate|calculate|compute|notify|send_\w+)$"), "service"),
    # Controller / handler patterns
    (re.compile(r"^(get|post|put|patch|delete|handle_request|index|show|create|destroy|update)$"), "handler"),
    # UI component patterns
    (re.compile(r"^(render|mount|unmount|on_click|on_change|on_submit|use_effect|use_state)$"), "component"),
]

# ---------------------------------------------------------------------------
# ORM / framework base-name patterns
# ---------------------------------------------------------------------------
# Detected via regex against any base class name (case-insensitive).

_INHERIT_ROLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(repository|repo)$", re.I), "repository"),
    (re.compile(r"(service|usecase|use_case)$", re.I), "service"),
    (re.compile(r"(controller|view|handler|viewset)$", re.I), "controller"),
    (re.compile(r"(component|widget|page)$", re.I), "component"),
    (re.compile(r"(model|entity|schema|basemodel|declarativebase)$", re.I), "model"),
    (re.compile(r"^(base|mixin)$", re.I), ""),  # skip — too generic, not a role signal
]


class ClassRoleAnalyzerPlugin(StaticAnalyzerPlugin):
    """Classifies classes into roles and propagates the role to their methods."""

    manifest = PluginManifest(
        id="static_analyzer.class_role",
        name="Class role analyzer",
        kind="static_analyzer",
        description="Classifies classes into architectural roles and tags their methods.",
        requires=("symbols", "call_edges"),
        produces=("findings.class_roles",),
        hooks=("on_graph_built",),
        order=110,
        after=("static_analyzer.pathways",),
    )

    def analyze(self, store: GraphStore | None = None, **kwargs) -> list[dict]:
        """Classify all classes and update their methods' role fields."""
        if store is None:
            service = kwargs.get("service")
            if service is None:
                return []
            store = getattr(service, "_store", None)
            if not isinstance(store, GraphStore):
                return []

        return run_class_role_analysis(store)


# ---------------------------------------------------------------------------
# Core analysis — shared by plugin.analyze() and tests
# ---------------------------------------------------------------------------


def run_class_role_analysis(store: GraphStore) -> list[dict]:
    """Classify all classes; update method function nodes in the graph.

    Returns a list of classification result dicts (for inspection/testing).
    """
    findings: list[dict] = []
    all_classes = store.get_all_classes()

    for cls in all_classes:
        class_id = cls["id"]
        class_name = cls.get("name", "")
        file_path = cls.get("file_path", "") or ""
        base_names: list[str] = cls.get("base_names") or []

        role = _classify_class_role(class_name, base_names, file_path, store, class_id)
        if not role:
            role = "unknown"

        findings.append({
            "class_id": class_id,
            "class_name": class_name,
            "file_path": file_path,
            "role": role,
        })

        # Propagate role to all methods of this class
        _update_methods(store, class_id, file_path, role)

    _logger.info("class_role: classified %d classes", len(findings))
    return findings


def _classify_class_role(
    class_name: str,
    base_names: list[str],
    file_path: str,
    store: GraphStore,
    class_id: str,
) -> str:
    # --- 1. Explicit base-name lookup (exact match from INHERIT_ROLE_RULES) ---
    for base in base_names:
        if base in INHERIT_ROLE_RULES:
            role = INHERIT_ROLE_RULES[base]
            if role:
                return role

    # --- 2. Pattern-based inheritance heuristics ---
    for base in base_names:
        for pattern, role in _INHERIT_ROLE_PATTERNS:
            if role and pattern.search(base):
                return role

    # --- 3. Method-name heuristics ---
    method_names = _get_method_names(store, class_id)
    for mname in method_names:
        for pattern, role in _METHOD_ROLE_PATTERNS:
            if pattern.match(mname):
                return role

    # --- 4. File-path heuristics ---
    lower_fp = file_path.lower()
    for fragment, role in PATH_ROLE_RULES:
        if fragment in lower_fp:
            return role

    return ""


def _get_method_names(store: GraphStore, class_id: str) -> list[str]:
    """Return the names of all methods of the given class."""
    try:
        rows = store.query(
            "MATCH (c:Class {id: $id})-[:HAS_METHOD]->(f:Function) RETURN f.name",
            {"id": class_id},
        )
        return [r[0] for r in rows if r[0]]
    except Exception as exc:
        _logger.warning("class_role: get_method_names failed for %s: %s", class_id, exc)
        return []


def _update_methods(store: GraphStore, class_id: str, file_path: str, role: str) -> None:
    """Update the layer+role on every method of a class."""
    # Determine the layer for the class's file
    layer = _classify_layer_from_path(file_path)

    try:
        rows = store.query(
            "MATCH (c:Class {id: $id})-[:HAS_METHOD]->(f:Function) RETURN f.id",
            {"id": class_id},
        )
        for row in rows:
            fn_id = row[0]
            if not fn_id:
                continue
            try:
                store.update_function_layer_role(fn_id, layer, role)
            except Exception as exc:
                _logger.warning(
                    "class_role: update_function_layer_role failed for %s: %s",
                    fn_id, exc,
                )
    except Exception as exc:
        _logger.warning("class_role: _update_methods failed for class %s: %s", class_id, exc)


def _classify_layer_from_path(file_path: str) -> str:
    lower = file_path.lower()
    for fragment, layer in PATH_LAYER_RULES:
        if fragment in lower:
            return layer
    return "unknown"
