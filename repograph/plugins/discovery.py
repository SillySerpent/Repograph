"""Ordered discovery of built-in plugins (`<pkg>.<name>.plugin:build_plugin`).

See ``docs/plugins/DISCOVERY.md``.
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any


PARSER_ORDER = ("python", "javascript", "typescript")

STATIC_ANALYZER_ORDER = (
    "pathways",
    "dead_code",
    "duplicates",
    "event_topology",
    "async_tasks",
)

FRAMEWORK_ADAPTER_ORDER = ("flask", "fastapi", "react", "nextjs")

DEMAND_ANALYZER_ORDER = (
    "dead_code",
    "private_surface_access",
    "config_boundary_reads",
    "db_shortcuts",
    "ui_boundary_paths",
    "duplicates",
    "contract_rules",
    "boundary_shortcuts",
    "architecture_conformance",
    "boundary_rules",
    "class_roles",
    "decomposition_signals",
    "config_flow",
    "module_component_signals",
)

EXPORTER_ORDER = (
    "docs_mirror",
    "pathway_contexts",
    "agent_guide",
    "modules",
    "pathways",
    "summary",
    "config_registry",
    "invariants",
    "event_topology",
    "async_tasks",
    "entry_points",
    "doc_warnings",
    "runtime_overlay_summary",
    "observed_runtime_findings",
    "report_surfaces",
)

EVIDENCE_PRODUCER_ORDER = ("declared_dependencies", "runtime_overlay")

DYNAMIC_ANALYZER_ORDER = ("runtime_overlay", "runtime_quality")


def import_build_plugin(base_pkg: str, name: str) -> Callable[[], Any]:
    """Import ``build_plugin`` from ``<base_pkg>.<name>.plugin``."""
    mod = importlib.import_module(f"{base_pkg}.{name}.plugin")
    build = getattr(mod, "build_plugin", None)
    if build is None or not callable(build):
        raise ImportError(f"{base_pkg}.{name}.plugin has no callable build_plugin")
    return build


def iter_build_plugins(
    base_pkg: str,
    names: tuple[str, ...],
    *,
    skip_import_error: bool = False,
) -> list[Callable[[], Any]]:
    """Return ``build_plugin`` callables in ``names`` order."""
    out: list[Callable[[], Any]] = []
    for name in names:
        try:
            out.append(import_build_plugin(base_pkg, name))
        except ImportError:
            if skip_import_error:
                continue
            raise
    return out


def load_optional_entry_point_plugins(
    group: str,
    register: Callable[[Any], None],
) -> None:
    """Load optional third-party plugins from setuptools entry points (if any)."""
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return
    eps = entry_points()
    if hasattr(eps, "select"):
        selected = eps.select(group=group)
    else:
        selected = eps.get(group, ())
    for ep in selected:
        try:
            fn = ep.load()
            if callable(fn):
                register(fn())
        except Exception:
            continue
