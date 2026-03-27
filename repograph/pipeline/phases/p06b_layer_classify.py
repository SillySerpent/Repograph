"""Phase 6b — Architecture layer classification.

Classifies every function and file node into a layer (api, persistence,
business_logic, ui, util, unknown) and assigns file-level roles.

Classification priority (highest wins):
  1. Explicit framework tags — set by p03b_framework_tags (already on the node,
     skip functions whose layer is already set to a non-empty, non-"unknown" value)
  2. Import-based layer detection — if the file imports from a known
     framework/library, assign the corresponding layer to ALL functions in
     that file.
  3. File-path heuristics — use the file path to infer layer and role.
  4. Default — "unknown"

All detection rules live in ``repograph.plugins.layer_rules`` (the plugin area).
This phase reads rules; it does not contain them.
"""
from __future__ import annotations

import logging

from repograph.core.models import ParsedFile
from repograph.graph_store.store import GraphStore
from repograph.plugins.layer_rules import (
    IMPORT_LAYER_RULES,
    PATH_LAYER_RULES,
    PATH_ROLE_RULES,
)

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public phase entry point
# ---------------------------------------------------------------------------


def run(parsed_files: list[ParsedFile], store: GraphStore) -> int:
    """Classify all functions and files into architecture layers.

    Returns the number of nodes updated.
    """
    updated = 0

    for pf in parsed_files:
        if pf.file_record is None:
            continue

        file_path = pf.file_record.path
        lang = pf.file_record.language

        # --- Determine the file's layer (import-based, then path-based) ---
        file_layer = _classify_layer_from_imports(pf)
        if not file_layer:
            file_layer = _classify_layer_from_path(file_path)
        if not file_layer:
            file_layer = "unknown"

        # --- Determine the file's role from its path ---
        file_role = _classify_role_from_path(file_path) or "unknown"

        # --- Update File node ---
        file_id = f"file::{file_path}"
        try:
            store.update_file_layer(file_id, file_layer)
        except Exception as exc:
            _logger.warning(
                "p06b: update_file_layer failed for %s: %s", file_path, exc
            )

        # --- Update Function nodes ---
        for fn in pf.functions:
            # Skip functions already tagged with a meaningful layer
            # (e.g., route handlers tagged by p03b_framework_tags)
            existing_layer = getattr(fn, "layer", "") or ""
            if existing_layer and existing_layer != "unknown":
                continue

            layer = file_layer
            role = file_role

            # Override: test helpers live in test files
            if pf.file_record.is_test:
                role = "test_helper"

            try:
                store.update_function_layer_role(fn.id, layer, role)
                updated += 1
            except Exception as exc:
                _logger.warning(
                    "p06b: update_function_layer_role failed for %s: %s",
                    fn.id,
                    exc,
                )

    _logger.info("p06b: classified %d function nodes", updated)
    return updated


# ---------------------------------------------------------------------------
# Helpers — rules are read from layer_rules.py, not defined here
# ---------------------------------------------------------------------------


def _classify_layer_from_imports(pf: ParsedFile) -> str:
    """Return a layer string if any import matches an import-layer rule, else ''."""
    for imp in pf.imports:
        module = imp.module_path or ""
        for layer, prefixes in IMPORT_LAYER_RULES.items():
            for prefix in prefixes:
                if module == prefix or module.startswith(prefix + "."):
                    return layer
    return ""


def _classify_layer_from_path(file_path: str) -> str:
    """Return a layer string if the file path matches a path-layer rule, else ''."""
    lower = file_path.lower()
    for fragment, layer in PATH_LAYER_RULES:
        if fragment in lower:
            return layer
    return ""


def _classify_role_from_path(file_path: str) -> str:
    """Return a role string if the file path matches a path-role rule, else ''."""
    lower = file_path.lower()
    for fragment, role in PATH_ROLE_RULES:
        if fragment in lower:
            return role
    return ""
