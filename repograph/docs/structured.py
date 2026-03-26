"""Structured JSON ground-truth sidecar files for each source file."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from repograph.graph_store.store import GraphStore
from repograph.core.models import FileRecord


def write_file_json(
    file_record: FileRecord,
    store: GraphStore,
    mirror_dir: str,
) -> dict:
    """
    Write a structured JSON sidecar for a source file to .repograph/mirror/<path>.json.
    Returns the JSON dict.
    """
    functions = store.get_functions_in_file(file_record.path)

    fn_dicts = []
    for fn in functions:
        callers = store.get_callers(fn["id"])
        callees = store.get_callees(fn["id"])
        fn_dicts.append({
            "id": fn["id"],
            "name": fn["name"],
            "qualified_name": fn["qualified_name"],
            "signature": fn["signature"],
            "line_start": fn["line_start"],
            "line_end": fn["line_end"],
            "docstring": fn.get("docstring") or "",
            "is_entry_point": fn.get("is_entry_point", False),
            "is_dead": fn.get("is_dead", False),
            "decorators": fn.get("decorators", []),
            "param_names": fn.get("param_names", []),
            "callers": [
                {"id": c["id"], "qualified_name": c["qualified_name"], "confidence": c["confidence"]}
                for c in callers
            ],
            "callees": [
                {"id": c["id"], "qualified_name": c["qualified_name"], "confidence": c["confidence"]}
                for c in callees
            ],
        })

    doc = {
        "schema_version": "1.0",
        "source_file": file_record.path,
        "source_hash": file_record.source_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_stale": False,
        "language": file_record.language,
        "functions": fn_dicts,
    }

    out_path = _mirror_json_path(mirror_dir, file_record.path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)

    return doc


def _mirror_json_path(mirror_dir: str, source_path: str) -> str:
    return os.path.join(mirror_dir, source_path + ".json")
