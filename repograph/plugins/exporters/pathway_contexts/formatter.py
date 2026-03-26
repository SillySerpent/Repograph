# Canonical context-document formatter owned by the pathway-context exporter.
"""Context document formatter — renders pathway context into AI-readable text.

Generates an AI-oriented context document for each pathway, including:
- Execution steps with role annotations
- Config key dependencies extracted from source
- I/O and async annotations for danger-zone awareness
- Variable threads
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from repograph.graph_store.store import GraphStore
from .budget import TokenBudgetManager
from repograph.utils import logging as rg_log

SEP = "═" * 55

# Patterns for extracting config key reads from source lines
_CONFIG_PATTERNS = [
    re.compile(r"""(?:cfg|config|settings|conf)\s*\[\s*["']([^"']+)["']\s*\]"""),
    re.compile(r"""(?:cfg|config|settings|conf)\.get\s*\(\s*["']([^"']+)["']"""),
    re.compile(r"""os\.(?:getenv|environ\.get|environ\[)\s*\(?["']([^"']+)["']"""),
]

# Patterns that indicate I/O or side-effect operations
_IO_INDICATORS = {
    "db_operation": re.compile(
        r"\.execute\(|\.commit\(|\.fetchall\(|\.fetchone\(|\.cursor\("
        r"|session\.|\.query\(|\.insert\(|\.update\(|\.delete\(",
        re.I,
    ),
    # Anchored to known HTTP client names to avoid false-positives on
    # dict.get(), cfg.get(), FlagStore.get(), etc.
    "http_call": re.compile(
        r"(?:requests|httpx|aiohttp|urllib\.request|urllib\.urlopen)\b"
        r"|(?:self\._session|self\.session|self\.client|self\._client"
        r"|self\._rest|session|client|resp|response)\s*\.\s*"
        r"(?:get|post|put|patch|delete)\s*\(",
        re.I,
    ),
    "file_io": re.compile(
        r"open\(|\.read\(|\.write\(|\.readlines\(|pathlib\.|shutil\.",
    ),
    "async_operation": re.compile(
        r"\bawait\b|\basync\s+def\b|\basync\s+for\b|\basync\s+with\b",
    ),
    "websocket": re.compile(
        r"websocket|ws_connect|\.send\(|\.recv\(",
        re.I,
    ),
}


def format_context_doc(
    pathway: dict,
    steps: list[dict],
    store: GraphStore,
    budget: TokenBudgetManager,
) -> str:
    """Render a full context document for a pathway."""
    from repograph.utils.fs import _KNOWN_OSS_PACKAGES

    # Separate vendored steps (from in-tree OSS copies) so they don't pollute
    # the execution walkthrough.  A step is considered vendored when its
    # top-level path segment (or second segment for src/) matches a known
    # OSS package name.
    def _step_is_vendored(fp: str) -> bool:
        parts = [p for p in fp.replace("\\", "/").split("/") if p]
        if not parts:
            return False
        candidates = {parts[0].lower().replace("-", "_")}
        if len(parts) >= 2:
            candidates.add(parts[1].lower().replace("-", "_"))
        return bool(candidates & _KNOWN_OSS_PACKAGES)

    prod_steps = [s for s in steps if not _step_is_vendored(s.get("file_path", ""))]
    vendored_steps = [s for s in steps if _step_is_vendored(s.get("file_path", ""))]

    lines: list[str] = []

    lines += [
        SEP,
        f"PATHWAY: {pathway.get('name', '')}",
        f"Display: {pathway.get('display_name', '')}",
        f"Source:  {pathway.get('source', 'auto_detected')}",
        f"Confidence: {pathway.get('confidence', 0.0):.2f}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        SEP,
        "",
    ]

    lines += [
        "INTERPRETATION",
        "Steps follow breadth-first search over CALLS edges from the entry function.",
        "Order is not guaranteed to match source-line order or a single runtime trace",
        "(branches, loops, and conditions may reorder work).",
        "Pathways starting in Python omit JavaScript/TypeScript callees from the same walk.",
        "",
    ]

    desc = pathway.get("description", "")
    if desc:
        lines += ["DESCRIPTION", desc, ""]

    # Participating files — production only (vendored listed as footnote)
    files = list(dict.fromkeys(
        s.get("file_path", "") for s in prod_steps if s.get("file_path")
    ))
    if files:
        lines.append("PARTICIPATING FILES (BFS discovery order)")
        for i, fp in enumerate(files, 1):
            lines.append(f"  {i}. {fp}")
        if vendored_steps:
            vendored_files = sorted({s.get("file_path", "").split("/")[0]
                                      for s in vendored_steps if s.get("file_path")})
            lines.append(
                f"  [+ {len(vendored_steps)} step(s) in vendored "
                f"lib(s): {', '.join(vendored_files)}]"
            )
        lines.append("")

    # Use only production steps for source analysis and rendering
    steps = prod_steps

    # Read source snippets for config/IO analysis
    # (done once, shared across all steps)
    step_sources = _load_step_sources(steps, store)

    # Execution steps — trim to budget
    trimmed_steps = budget.trim_steps(steps)
    trimmed_count = len(steps) - len(trimmed_steps)

    lines.append("EXECUTION STEPS")
    box_width = 53
    for seq_num, step in enumerate(trimmed_steps, start=1):
        role = step.get("role", "service")
        fname = step.get("function_name") or step.get("name", "?")
        fpath = step.get("file_path", "")
        ls = step.get("line_start", 0)
        le = step.get("line_end", 0)
        bfs_depth = step.get("step_order", step.get("order", 0))
        decs: list[str] = step.get("decorators", [])
        fid = step.get("function_id", "") or step.get("id", "")

        # seq_num is the human-readable sequential counter (1, 2, 3…).
        # bfs_depth is the BFS traversal depth preserved for tracing.
        header = f" STEP {seq_num} [depth {bfs_depth}] [{role}] {fname}"
        file_line = f" File: {fpath} : {ls}-{le}"
        lines.append("┌" + "─" * box_width + "┐")
        lines.append("│" + header[:box_width].ljust(box_width) + "│")
        lines.append("│" + file_line[:box_width].ljust(box_width) + "│")
        if decs:
            dec_line = f" Decorator: {decs[0]}"
            lines.append("│" + dec_line[:box_width].ljust(box_width) + "│")

        # Docstring annotation — first sentence, muted style prefix
        doc = step.get("docstring") or ""
        if not doc:
            # Try a lightweight store lookup so the formatter works even when
            # docstrings aren't pre-loaded into the step dict.
            try:
                fn_data = store.get_function_by_id(fid) if fid else None
                if fn_data:
                    doc = fn_data.get("docstring") or ""
            except Exception as exc:
                rg_log.warn_once(f"pathway_contexts: failed docstring lookup for {fid}: {exc}")
        doc_summary = _docstring_first_sentence(doc)
        if doc_summary:
            doc_line = f" \"{doc_summary}\""
            lines.append("│" + doc_line[:box_width].ljust(box_width) + "│")

        # I/O annotations for this step
        src = step_sources.get(fid, "")
        io_tags = _detect_io_tags(src)
        if io_tags:
            io_line = f" ⚡ {', '.join(io_tags)}"
            lines.append("│" + io_line[:box_width].ljust(box_width) + "│")

        lines.append("└" + "─" * box_width + "┘")

    if trimmed_count > 0:
        lines.append(f"\n[TRIMMED: {trimmed_count} steps omitted for token budget]\n")

    lines.append("")

    # Config keys section — extracted from all step sources
    all_source = "\n".join(step_sources.values())
    config_keys = _extract_config_keys(all_source)
    if config_keys:
        lines.append("CONFIG DEPENDENCIES")
        lines.append("  Keys read by functions in this pathway:")
        for key in sorted(config_keys):
            lines.append(f"    • {key}")
        lines.append("")

    # Variable threads (if any in pathway data)
    try:
        import json
        vt_raw = pathway.get("variable_threads", "[]") or "[]"
        threads = json.loads(vt_raw) if isinstance(vt_raw, str) else vt_raw
        if threads:
            lines.append("VARIABLE THREADS")
            for t in threads[:5]:
                name = t.get("name", "?")
                steps_t = t.get("steps", [])
                lines.append(f"  Thread \"{name}\":")
                if steps_t:
                    step_strs = [f"step_{s[0]+1}.{s[1].split(':')[-1]}" for s in steps_t[:4]]
                    lines.append("    " + " → ".join(step_strs))
            lines.append("")
    except Exception as exc:
        rg_log.warn_once(f"pathway_contexts: failed parsing variable threads for {pathway.get('id', '?')}: {exc}")

    lines += [SEP, ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Source analysis helpers
# ---------------------------------------------------------------------------

def _load_step_sources(steps: list[dict], store: GraphStore) -> dict[str, str]:
    """Load source text for each step function.

    Returns {function_id: source_text}.  Uses the file path and line range
    stored in the step to read from disk.  Falls back gracefully if the
    file isn't readable.
    """
    sources: dict[str, str] = {}
    # Try to find the repo root from the store's DB path
    try:
        repo_root = store.db_path.rsplit("/.repograph", 1)[0] if hasattr(store, "db_path") else ""
    except Exception:
        repo_root = ""

    for step in steps:
        fid = step.get("function_id", "") or step.get("id", "")
        if not fid or fid in sources:
            continue
        fpath = step.get("file_path", "")
        ls = step.get("line_start", 0)
        le = step.get("line_end", 0)
        if not fpath or not ls:
            sources[fid] = ""
            continue
        # Try reading from disk
        try:
            full_path = os.path.join(repo_root, fpath) if repo_root else fpath
            with open(full_path, "r", errors="replace") as f:
                all_lines = f.readlines()
            start = max(0, ls - 1)
            end = le if le else min(start + 50, len(all_lines))
            sources[fid] = "".join(all_lines[start:end])
        except Exception as exc:
            rg_log.warn_once(f"pathway_contexts: failed reading source for {fpath}:{ls}-{le}: {exc}")
            sources[fid] = ""
    return sources


def _extract_config_keys(source: str) -> list[str]:
    """Extract configuration key names from source text."""
    keys: set[str] = set()
    for pattern in _CONFIG_PATTERNS:
        for match in pattern.finditer(source):
            keys.add(match.group(1))
    return sorted(keys)


def _docstring_first_sentence(docstring: str) -> str:
    """Return the first sentence of a docstring, capped at 100 characters.

    Used to annotate pathway step boxes so an AI reading the context doc
    can understand what each step does without opening the source file.
    Returns an empty string when the docstring is absent or empty.
    """
    if not docstring:
        return ""
    text = docstring.strip()

    # Walk lines, skip blank lines and Google/reST section headers
    # (lines ending in ":" with no leading space, or indented continuation
    # lines that are part of a param/return block).
    _SECTION_HEADER = re.compile(r"^[A-Za-z][A-Za-z ]*:\s*$")
    in_section = False
    for line in text.split("\n"):
        raw = line
        stripped = line.strip()
        if not stripped:
            continue
        # A section header starts a block we want to skip
        if _SECTION_HEADER.match(stripped):
            in_section = True
            continue
        # An indented line inside a section block — skip
        if in_section and raw and raw[0] in (" ", "\t"):
            continue
        # Back to normal prose
        in_section = False
        first_line = stripped
        # Truncate at first sentence-ending period
        for i, ch in enumerate(first_line):
            if ch == "." and (i + 1 >= len(first_line) or first_line[i + 1] == " "):
                return first_line[: i + 1][:100]
        return first_line[:100]

    return ""


def _detect_io_tags(source: str) -> list[str]:
    """Detect I/O and side-effect patterns in a function's source.

    Returns a list of human-readable tags like "db", "http", "async", "file_io".
    """
    tags: list[str] = []
    for label, pattern in _IO_INDICATORS.items():
        if pattern.search(source):
            # Human-friendly labels
            friendly = {
                "db_operation": "database",
                "http_call": "HTTP",
                "file_io": "file I/O",
                "async_operation": "async",
                "websocket": "websocket",
            }
            tags.append(friendly.get(label, label))
    return tags
