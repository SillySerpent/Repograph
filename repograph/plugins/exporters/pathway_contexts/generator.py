# Canonical context generation owned by the pathway-context exporter.
"""Context document generator — assembles preformatted context docs for AI injection."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from repograph.graph_store.store import GraphStore
from .budget import TokenBudgetManager
from .formatter import format_context_doc
from repograph.utils import logging as rg_log


def generate_pathway_context(
    pathway_id: str,
    store: GraphStore,
    max_tokens: int = 2000,
) -> str:
    """
    Generate a context document for a pathway and store it back in the graph.
    Returns the formatted context text.
    """
    pathway = store.get_pathway_by_id(pathway_id)
    if not pathway:
        return ""

    # Get steps for the pathway
    steps = store.get_pathway_steps(pathway_id)
    if not steps:
        return ""

    budget = TokenBudgetManager(max_tokens=max_tokens)
    context_doc = format_context_doc(pathway, steps, store, budget)

    # Update pathway with context doc
    store.update_pathway_context(pathway_id, context_doc)

    return context_doc


def generate_all_pathway_contexts(store: GraphStore, max_tokens: int = 2000) -> int:
    """Generate context docs for all pathways. Returns count updated."""
    pathways = store.get_all_pathways()
    updated = 0
    for p in pathways:
        try:
            ctx = generate_pathway_context(p["id"], store, max_tokens)
            if ctx:
                updated += 1
        except Exception as exc:
            pid = p.get("id", "?") if isinstance(p, dict) else "?"
            rg_log.warn_once(f"pathway_contexts: failed generating context for {pid}: {exc}")
    return updated
