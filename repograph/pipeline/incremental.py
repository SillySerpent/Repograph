"""Incremental diff engine — compute which files changed since last run."""
from __future__ import annotations

import json
import os

from repograph.core.models import FileRecord, DiffResult, AffectedSet
from repograph.graph_store.store import GraphStore
from repograph.observability import get_logger, log_degraded

_logger = get_logger(__name__, subsystem="incremental")


def expand_reparse_paths_for_incremental(
    store: GraphStore,
    *,
    added: set[str],
    changed: set[str],
    removed: set[str],
    current_paths: set[str],
) -> set[str]:
    """Expand ``added | changed`` with files that must be re-parsed so CALLS stay correct.

    When a callee file is replaced or removed, :meth:`GraphStore.delete_file_nodes`
    detaches all ``CALLS`` edges involving its functions. Phase 5 only runs on
    ``parsed`` files, so *callers in unchanged files* would otherwise keep missing
    edges until those callers are edited.

    This returns the union of:

    * ``added | changed`` (as before),
    * **reverse CALLS** — distinct ``a.file_path`` for
      ``(a:Function)-[:CALLS]->(b:Function)`` where ``b.file_path`` is in
      ``changed | removed`` (query **before** deletes),
    * **reverse IMPORTS** — :meth:`GraphStore.get_importers` for each path in
      ``added | changed | removed`` (importers must refresh when a target file
      is added, updated, or deleted).

    Only paths present in ``current_paths`` (still on disk) are kept.
    """
    base = added | changed
    out: set[str] = set(base)
    callee_gone = changed | removed

    # D1: single bulk query instead of N per-file queries
    if callee_gone:
        try:
            rows = store.query(
                """
                MATCH (a:Function)-[:CALLS]->(b:Function)
                WHERE b.file_path IN $fps
                RETURN DISTINCT a.file_path
                """,
                {"fps": list(callee_gone)},
            )
            for r in rows:
                p = r[0]
                if p and p in current_paths:
                    out.add(p)
        except Exception as exc:
            log_degraded(
                _logger,
                "reverse-CALLS bulk expansion failed — affected callers may be incomplete",
                exc=exc,
                partial_result="all reverse-CALLS callers skipped",
            )

    import_targets = added | changed | removed
    if import_targets:
        try:
            for im in store.get_bulk_importers(list(import_targets)):
                if im in current_paths:
                    out.add(im)
        except Exception as exc:
            log_degraded(
                _logger,
                "reverse-IMPORTS bulk expansion failed — affected importers may be incomplete",
                exc=exc,
                partial_result="all importers skipped",
            )

    return {p for p in out if p in current_paths}


class IncrementalDiff:
    """Computes the diff between the last indexed state and the current filesystem."""

    def __init__(self, repograph_dir: str) -> None:
        self._index_path = os.path.join(repograph_dir, "meta", "file_index.json")

    def _load_index(self) -> dict[str, str]:
        if os.path.exists(self._index_path):
            try:
                with open(self._index_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                log_degraded(
                    _logger,
                    "file index could not be loaded — treating all files as new",
                    exc=exc,
                    partial_result="empty index",
                    index_path=self._index_path,
                )
        return {}

    def compute(self, current_map: dict[str, FileRecord]) -> DiffResult:
        """Compare current files against stored index."""
        stored = self._load_index()
        current_hashes: dict[str, str | None] = {}
        for path, fr in current_map.items():
            if fr.source_hash is None:
                _logger.warning(
                    "FileRecord has no source_hash — treating file as changed",
                    path=path,
                )
            current_hashes[path] = fr.source_hash

        added = {p for p in current_hashes if p not in stored}
        removed = {p for p in stored if p not in current_hashes}
        changed = {
            p for p in current_hashes
            if p in stored and current_hashes[p] != stored[p]
        }
        return DiffResult(added=added, removed=removed, changed=changed)

    def compute_affected(self, diff: DiffResult, store: GraphStore) -> AffectedSet:
        """Expand changed/added files to include their importers (legacy helper).

        For full caller ∪ importer expansion used by incremental sync, see
        :func:`expand_reparse_paths_for_incremental`.
        """
        affected = set(diff.added | diff.changed)
        for path in list(diff.changed):
            importers = store.get_importers(path)
            affected.update(importers)
        return AffectedSet(
            reparse=diff.added | diff.changed,
            recheck_calls=affected,
            remove=diff.removed,
            all_affected=affected,
        )

    def save_index(self, current_map: dict[str, FileRecord]) -> None:
        os.makedirs(os.path.dirname(self._index_path), exist_ok=True)
        index = {path: fr.source_hash for path, fr in current_map.items()}
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

    def is_first_run(self) -> bool:
        return not os.path.exists(self._index_path)
