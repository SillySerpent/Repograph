# Canonical pathway-description generation owned by the pathways plugin.
"""Generate human-readable pathway descriptions from docstrings (RG-02 / IMP-05).

Runs after pathway steps are known (Phase 10 or PathwayAssembler). Reads module
docstrings via ``GraphStore.get_file`` for participating files.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repograph.graph_store.store import GraphStore


def generate_description(
    entry_fn: dict,
    participating_files: list[str],
    store: "GraphStore",
    io_tags: list[str],
    *,
    step_count: int = 0,
    file_count: int = 0,
) -> str:
    """Build a short pathway description from docstrings and I/O tags.

    Args:
        entry_fn: Function record dict (must include ``docstring``, ``qualified_name``).
        participating_files: Distinct file paths touched by the pathway (up to 3 used).
        store: Graph store for ``get_file`` (module docstrings).
        io_tags: Labels such as ``async``, ``database``, ``network``.
        step_count: Number of pathway steps (fallback text).
        file_count: Distinct files (fallback text).

    Returns:
        One paragraph, at most ~300 characters; never empty.
    """
    qn = entry_fn.get("qualified_name", "") or ""
    parts: list[str] = []

    doc = (entry_fn.get("docstring") or "").strip()
    if doc:
        parts.append(_first_sentence(doc, max_len=200))

    snippets: list[str] = []
    for fp in participating_files[:3]:
        try:
            finfo = store.get_file(fp)
            if not finfo:
                continue
            fdoc = (finfo.get("docstring") or "").strip()
            if fdoc:
                snippets.append(_first_sentence(fdoc, max_len=80))
        except Exception:
            continue
    if snippets:
        uniq = list(dict.fromkeys(snippets))
        if uniq:
            parts.append("Touches themes: " + ", ".join(uniq[:4]) + ".")

    if io_tags:
        tag_str = ", ".join(sorted({t.strip() for t in io_tags if t.strip()}))
        if tag_str:
            parts.append(f"Tags: {tag_str}.")

    text = " ".join(p for p in parts if p).strip()
    text = _truncate_words(text, 300)

    if not text:
        text = (
            f"Execution flow starting from {qn} through {step_count} steps "
            f"across {file_count or len(participating_files)} files."
        )
    return text


def _first_sentence(text: str, max_len: int = 200) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    for i, ch in enumerate(text):
        if ch == "." and (i + 1 >= len(text) or text[i + 1] == " "):
            return text[: i + 1][:max_len]
    return text[:max_len]


def _truncate_words(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…" if cut else text[:max_len]
