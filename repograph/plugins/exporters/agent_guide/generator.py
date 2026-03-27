# Canonical agent-guide generation owned by the agent-guide exporter.
"""AGENT_GUIDE.md generator — tells AI agents how to navigate the system."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

from repograph.config import AGENT_GUIDE_MAX_FILE_READ_BYTES as _MAX_FILE_READ_BYTES
from repograph.graph_store.store import GraphStore
from repograph.utils import logging as rg_log


# ---------------------------------------------------------------------------
# Repo-context helpers
# ---------------------------------------------------------------------------

def _extract_repo_summary(repo_root: str) -> str:
    """Read the first meaningful paragraph from README.md or a docs overview file.

    Handles the common Markdown pattern where a sentence ends with a colon
    and is followed by a bullet list on the next block:

        This project does X with:

        - feature A
        - feature B

    In that case both blocks are joined so the summary is complete.

    Returns an empty string when nothing readable is found — callers must
    handle the empty case gracefully.
    """
    candidates = [
        "README.md", "README.rst", "README.txt",
        "docs/ai/REPO_MAP.md", "docs/README.md", "docs/OVERVIEW.md",
    ]
    for rel in candidates:
        fpath = os.path.join(repo_root, rel)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                raw = f.read(_MAX_FILE_READ_BYTES)
            # Split on blank lines and iterate blocks
            blocks = raw.split("\n\n")
            for i, block in enumerate(blocks):
                block = block.strip()
                if not block:
                    continue
                # Skip pure heading blocks (lines starting with # only)
                non_heading = [ln for ln in block.splitlines()
                               if ln.strip() and not ln.strip().startswith("#")]
                if not non_heading:
                    continue
                # Skip badge/shield lines and CI blocks
                text = " ".join(non_heading)
                if "![" in text or "<!--" in text:
                    continue
                # Found the first real paragraph.
                # If it ends with ":" it likely introduces a list in the next
                # block. Peek: if every non-empty line starts with a list
                # marker (-, *, or digit+.) append it to complete the sentence.
                summary = text.strip()
                if summary.endswith(":") and i + 1 < len(blocks):
                    next_block = blocks[i + 1].strip()
                    next_lines = [ln.strip() for ln in next_block.splitlines()
                                  if ln.strip()]
                    _list_re = re.compile(r"^[-*]|\d+\.")
                    if next_lines and all(_list_re.match(ln) for ln in next_lines):
                        items = [ln.lstrip("-*0123456789. ") for ln in next_lines]
                        summary = summary + " " + " / ".join(items)
                # Cap at 600 chars
                return summary[:600]
        except OSError:
            continue
    return ""


def _extract_doc_index(repo_root: str) -> list[tuple[str, str]]:
    """Scan docs/ directories and return [(relative_path, first_heading)]
    for up to 20 Markdown files.  Silently skips unreadable files.
    """
    results: list[tuple[str, str]] = []
    search_dirs = ["docs", "doc", "documentation"]
    for d in search_dirs:
        docs_path = os.path.join(repo_root, d)
        if not os.path.isdir(docs_path):
            continue
        for root, _, files in os.walk(docs_path):
            for fn in sorted(files):
                if not fn.endswith(".md"):
                    continue
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, repo_root)
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        first = f.readline().strip().lstrip("# ").strip()
                    results.append((rel, first or fn))
                except OSError:
                    results.append((rel, fn))
                if len(results) >= 20:
                    return results
    return results


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_agent_guide(store: GraphStore, repo_root: str, repograph_dir: str) -> str:
    """Generate AGENT_GUIDE.md from actual repo knowledge and write it.

    Parameters
    ----------
    store:
        Open GraphStore for the indexed repo.
    repo_root:
        Absolute path to the repository root directory.
    repograph_dir:
        Directory where AGENT_GUIDE.md will be written.

    Returns
    -------
    str
        The full guide text.
    """
    stats = store.get_stats()
    pathways = store.get_all_pathways()
    entry_points = store.get_entry_points(limit=10)

    repo_name = os.path.basename(os.path.abspath(repo_root))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- Repo summary (from README / docs) ----------------------------------
    repo_summary = _extract_repo_summary(repo_root)
    doc_index = _extract_doc_index(repo_root)

    prod_pathways = [p for p in pathways if p.get("source") != "auto_detected_test"]
    test_pathways = [p for p in pathways if p.get("source") == "auto_detected_test"]
    sorted_prod = sorted(
        prod_pathways,
        key=lambda x: (-(x.get("importance_score") or 0.0), -(x.get("confidence") or 0.0)),
    )

    # Pick best example pathway for Step 2 navigation hint
    example_pathway = sorted_prod[0]["name"] if sorted_prod else "your_pathway_name"

    lines = [
        "# RepoGraph Agent Guide",
        f"Generated: {now} | Repo: {repo_name} | "
        f"{len(pathways)} pathways | {stats.get('functions', 0)} symbols",
        "",
    ]

    # Repo summary block (only when we found something meaningful)
    if repo_summary:
        lines += [
            "## About This Repo",
            "",
            repo_summary,
            "",
        ]

    lines += [
        "## What This System Provides",
        "",
        "RepoGraph has analyzed this repo and produced a structured intelligence layer.",
        "You have access to 10 MCP tools and this guide. **Read this guide fully** before",
        "making any code changes.",
        "",
        "## How to Navigate This Repo",
        "",
        "### Step 1 — Orient with pathways",
        "When you enter this repo for the first time or encounter an unfamiliar feature:",
        "```",
        "list_pathways()",
        "```",
        "This returns every named pathway with its description and confidence.",
        "Pick the one most relevant to your task.",
        "",
        "### Step 2 — Get full pathway context",
        "```",
        f'get_pathway("{example_pathway}")',
        "```",
        "This returns the complete context document: every file, every step, variable",
        "threads, failure points. Read this before opening any source files.",
        "",
        "### Step 3 — Before changing anything",
        "```",
        "impact(\"function_name\")",
        "```",
        "Before editing ANY function, call impact() to see the blast radius.",
        "Never skip this step.",
        "",
        "### Step 4 — Trace data flow",
        "```",
        "trace_variable(\"variable_name\", pathway=\"pathway_name\")",
        "```",
        "When you need to understand what data is in play, use trace_variable().",
        "",
        "### Step 5 — Find something unfamiliar",
        "```",
        "search(\"description of what you're looking for\")",
        "```",
        "Use search() when you don't know the exact symbol name.",
        "",
    ]

    # Production pathways table (sorted by importance_score)
    if sorted_prod:
        lines += [
            "## Available Pathways in This Repo",
            "",
            "| Name | Entry Point | Steps | Importance | Confidence | Source |",
            "|------|-------------|-------|-----------|-----------|--------|",
        ]
        for p in sorted_prod:
            conf = p.get("confidence") or 0.0
            imp = p.get("importance_score") or 0.0
            lines.append(
                f"| {p['name']} | {p.get('entry_function', '').split(':')[-1]} "
                f"| {p.get('step_count', 0)} | {imp:.2f} | {conf:.2f}"
                f" | {p.get('source', 'auto')} |"
            )
        lines.append("")

    if test_pathways:
        lines += [
            f"## Test Coverage Pathways ({len(test_pathways)} total)",
            "",
            "These pathways begin from test entry points and reflect test coverage "
            "rather than production execution paths.",
            "Run `list_pathways(include_tests=True)` via the API to see them.",
            "",
        ]

    # Top entry points
    if entry_points:
        lines += [
            "## Top Entry Points",
            "",
            "| Function | File | Score |",
            "|----------|------|-------|",
        ]
        for ep in entry_points[:10]:
            lines.append(
                f"| {ep.get('qualified_name', '').split(':')[-1]} "
                f"| {ep.get('file_path', '')} "
                f"| {ep.get('entry_score', 0):.2f} |"
            )
        lines.append("")

    # Documentation index
    if doc_index:
        lines += [
            "## Documentation Index",
            "",
            "The following documentation files exist in this repo:",
            "",
        ]
        for rel_path, heading in doc_index:
            lines.append(f"- `{rel_path}` — {heading}")
        lines.append("")

    try:
        ev_rows = store.get_event_topology()
    except Exception as exc:
        rg_log.warn_once(f"agent_guide: failed loading event topology: {exc}")
        ev_rows = []
    if ev_rows:
        lines += [
            "## Event Bus",
            "",
            "Heuristic publish/subscribe call sites (Phase 19). Verify in source.",
            "",
        ]
        for r in ev_rows[:40]:
            lines.append(
                f"- `{r.get('event_type', '?')}` — {r.get('role', '')} "
                f"({r.get('file_path', '')}:{r.get('line', '')})"
            )
        lines.append("")

    try:
        tasks = store.get_async_tasks()
    except Exception as exc:
        rg_log.warn_once(f"agent_guide: failed loading async tasks: {exc}")
        tasks = []
    if tasks:
        lines += [
            "## Background Tasks",
            "",
            "``asyncio.create_task`` / ``ensure_future`` sites (Phase 20).",
            "",
        ]
        for t in tasks[:40]:
            lines.append(
                f"- {t.get('spawner_fn_id', '')}: {t.get('coroutine_name', '')} "
                f"(name={t.get('task_name', '')})"
            )
        lines.append("")

    lines += [
        "## Confidence Interpretation",
        "",
        "- **0.9–1.0**: HIGH — derived from direct static analysis, trust fully",
        "- **0.7–0.9**: MEDIUM — one hop of inference (method call on untyped receiver)",
        "- **0.5–0.7**: LOW — inferred from pattern matching, verify before relying on",
        "- **< 0.5**: UNCERTAIN — do not rely on without manual check",
        "",
        "## Staleness",
        "",
        "If a tool returns `\"stale\": true`, the source file changed since last sync.",
        "Run `repograph sync` to update. Stale data may be wrong.",
        "",
        "## What This System Does NOT Know",
        "",
        "- Runtime behavior (only static analysis)",
        "- Dynamic dispatch via string keys or reflection (confidence will be LOW)",
        "- External service behavior (HTTP calls show as terminal nodes)",
        "- Generated code (migrations, protobuf) — excluded from analysis",
        "",
        "## Repo Stats",
        "",
    ]
    for k, v in stats.items():
        lines.append(f"- **{k.replace('_', ' ').title()}**: {v}")

    guide = "\n".join(lines) + "\n"

    out_path = os.path.join(repograph_dir, "AGENT_GUIDE.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(guide)

    return guide
