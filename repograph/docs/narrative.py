"""Narrative Markdown sidecar files for each source file."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from repograph.graph_store.store import GraphStore
from repograph.core.models import FileRecord


def write_file_md(
    file_record: FileRecord,
    store: GraphStore,
    mirror_dir: str,
    is_stale: bool = False,
) -> str:
    """
    Write a Markdown narrative doc for a source file.
    Returns the markdown text.
    """
    functions = store.get_functions_in_file(file_record.path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stale_warning = "\n> ⚠️ **STALE** — source file changed since last sync\n" if is_stale else ""

    lines = [
        f"# {file_record.path}",
        f"> **Status**: {'stale' if is_stale else 'current'} (last synced: {now})",
        f"> **Language**: {file_record.language}",
        stale_warning,
        "",
    ]

    if not functions:
        lines.append("*No functions extracted from this file.*\n")
    else:
        lines.append("## Functions\n")
        for fn in functions:
            callers = store.get_callers(fn["id"])
            callees = store.get_callees(fn["id"])

            caller_names = ", ".join(c["qualified_name"].split(":")[-1] for c in callers[:5])
            callee_names = ", ".join(c["qualified_name"].split(":")[-1] for c in callees[:5])

            dead_tag = " *(dead)*" if fn.get("is_dead") else ""
            entry_tag = " *(entry point)*" if fn.get("is_entry_point") else ""
            decs = fn.get("decorators", [])
            dec_line = f"\n*Decorators: {', '.join(decs)}*" if decs else ""

            lines += [
                f"### `{fn['signature']}`{dead_tag}{entry_tag}",
                f"*Lines {fn['line_start']}–{fn['line_end']}*{dec_line}",
                "",
            ]
            if caller_names:
                lines.append(f"Called by: {caller_names}")
            if callee_names:
                lines.append(f"Calls: {callee_names}")

            doc = fn.get("docstring") or ""
            if doc:
                lines += ["", doc]

            lines.append("")
            lines.append("---")
            lines.append("")

    text = "\n".join(lines)

    out_path = _mirror_md_path(mirror_dir, file_record.path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    return text


def _mirror_md_path(mirror_dir: str, source_path: str) -> str:
    return os.path.join(mirror_dir, source_path + ".md")
