"""Phase 12 — Git Coupling: co-change analysis using GitPython."""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from repograph.core.models import CoupledWithEdge, NodeID
from repograph.graph_store.store import GraphStore


def run(
    store: GraphStore,
    repo_root: str,
    days: int = 180,
    min_count: int = 3,
    min_strength: float = 0.2,
) -> None:
    """
    Analyse git history for co-change patterns.
    Creates COUPLED_WITH edges for file pairs that frequently change together.
    Skipped silently if repo has no git history.
    """
    try:
        import git
    except ImportError:
        return

    try:
        repo = git.Repo(repo_root, search_parent_directories=True)
    except Exception:
        return  # Not a git repo

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    co_changes: dict[tuple[str, str], int] = defaultdict(int)
    solo_changes: dict[str, int] = defaultdict(int)

    try:
        commits = list(repo.iter_commits(since=cutoff.isoformat()))
    except Exception:
        return

    # Set of file paths that are actually indexed in the graph (all languages)
    indexed_paths: set[str] = set(store.get_all_file_hashes().keys())

    for commit in commits:
        try:
            changed = _changed_files(commit)
        except Exception:
            continue

        # Only track files we have actually indexed (respects all languages)
        changed = [f for f in changed if f in indexed_paths]
        if not changed:
            continue

        for f in changed:
            solo_changes[f] += 1

        for i, fa in enumerate(changed):
            for fb in changed[i + 1:]:
                key = (min(fa, fb), max(fa, fb))
                co_changes[key] += 1

    if not co_changes:
        return

    for (fa, fb), count in co_changes.items():
        if count < min_count:
            continue

        max_solo = max(solo_changes.get(fa, 1), solo_changes.get(fb, 1))
        strength = count / max_solo if max_solo > 0 else 0.0

        if strength < min_strength:
            continue

        from_id = NodeID.make_file_id(fa)
        to_id = NodeID.make_file_id(fb)

        edge = CoupledWithEdge(
            from_file_id=from_id,
            to_file_id=to_id,
            change_count=count,
            strength=strength,
        )
        try:
            store.insert_coupled_with_edge(edge)
        except Exception:
            pass


def _changed_files(commit) -> list[str]:
    """Return list of files changed in a commit."""
    if commit.parents:
        diffs = commit.diff(commit.parents[0])
        return [d.a_path or d.b_path for d in diffs]
    else:
        # Initial commit
        return list(commit.stats.files.keys())
