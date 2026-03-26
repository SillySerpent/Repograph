"""Mirror layer — generate the full .repograph/ directory structure."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from repograph.core.models import FileRecord
from repograph.graph_store.store import GraphStore
from repograph.docs.structured import write_file_json
from repograph.docs.narrative import write_file_md
from repograph.docs.staleness import StalenessTracker


def generate_mirror(
    files: list[FileRecord],
    store: GraphStore,
    repograph_dir: str,
    staleness: StalenessTracker,
) -> None:
    """
    For every indexed source file, write:
      .repograph/mirror/<path>.json  — structured truth
      .repograph/mirror/<path>.md    — narrative
    Then write the top-level meta.json index.

    Also cleans up stale mirror artifacts for any source files that no
    longer exist in the current file set, so the mirror directory stays
    consistent with the repo.
    """
    mirror_dir = os.path.join(repograph_dir, "mirror")
    os.makedirs(mirror_dir, exist_ok=True)

    current_paths = {fr.path for fr in files}

    # --- Write / update mirrors for current files ---
    for fr in files:
        artifact_id = f"mirror:{fr.path}"
        is_stale = staleness.is_stale(artifact_id)

        write_file_json(fr, store, mirror_dir)
        write_file_md(fr, store, mirror_dir, is_stale=is_stale)

        staleness.record_artifact(
            artifact_id,
            artifact_type="mirror",
            source_hashes={fr.path: fr.source_hash},
        )

    # --- Remove stale mirror artifacts for deleted source files ---
    _cleanup_deleted_mirrors(current_paths, mirror_dir, staleness)

    _write_meta_json(files, store, repograph_dir)
    staleness.save()


def _cleanup_deleted_mirrors(
    current_paths: set[str],
    mirror_dir: str,
    staleness: StalenessTracker,
) -> int:
    """Delete mirror files whose source path is no longer in the repo.

    Walks the mirror directory and removes any .json/.md pair whose
    corresponding source path is absent from current_paths. Also purges
    the orphaned entry from the StalenessTracker so it doesn't accumulate.

    Returns the count of deleted files.
    """
    if not os.path.isdir(mirror_dir):
        return 0

    deleted = 0
    for dirpath, _dirs, filenames in os.walk(mirror_dir):
        for fname in filenames:
            abs_path = os.path.join(dirpath, fname)
            rel = os.path.relpath(abs_path, mirror_dir).replace("\\", "/")

            # Determine source path by stripping the .json / .md extension
            src_path: str | None = None
            for suffix in (".json", ".md"):
                if rel.endswith(suffix):
                    src_path = rel[: -len(suffix)]
                    break

            if src_path is None:
                continue  # unknown extension — leave alone

            if src_path not in current_paths:
                try:
                    os.remove(abs_path)
                    deleted += 1
                except OSError:
                    pass
                # Purge from staleness tracker
                artifact_id = f"mirror:{src_path}"
                staleness._data.pop(artifact_id, None)

    return deleted


def _write_meta_json(
    files: list[FileRecord],
    store: GraphStore,
    repograph_dir: str,
) -> None:
    """Write .repograph/meta.json with repo-level index."""
    stats = store.get_stats()
    pathways = store.get_all_pathways()

    meta = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "files": [fr.path for fr in files],
        "pathways": [
            {
                "id": p["id"],
                "name": p["name"],
                "display_name": p["display_name"],
                "confidence": p["confidence"],
                "step_count": p["step_count"],
                "source": p["source"],
            }
            for p in pathways
        ],
    }

    meta_path = os.path.join(repograph_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
