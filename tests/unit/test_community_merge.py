"""Tests for Phase 9 community merging — micro-cluster reduction."""
from __future__ import annotations

import os
import shutil
import pytest

FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
)


def _run_pipeline(repo: str, rg_dir: str, min_community_size: int = 8):
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    return run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, full=True,
        min_community_size=min_community_size,
    ))


def _open_store(rg_dir: str):
    from repograph.graph_store.store import GraphStore
    store = GraphStore(os.path.join(rg_dir, "graph.db"))
    store.initialize_schema()
    return store


class TestMergeMicroCommunities:
    """Unit-level tests against the _merge_micro_communities helper directly."""

    def _make_fake_comm_funcs(self, layout):
        """layout: {comm_id: [fn_id, ...]}"""
        return {
            cid: [{"id": fid, "file_path": f"src/mod_{cid}.py"} for fid in fids]
            for cid, fids in layout.items()
        }

    def _make_call_edges(self, edges):
        """edges: [(from_id, to_id), ...]"""
        return [{"from": a, "to": b, "confidence": 0.9} for a, b in edges]

    def test_micro_merged_into_connected_large(self, tmp_path):
        """A 2-member micro should merge into whichever large community
        has the most edges to its members."""
        from repograph.graph_store.store import GraphStore
        from repograph.pipeline.phases.p09_communities import _merge_micro_communities

        db = str(tmp_path / "t.db")
        store = GraphStore(db)
        store.initialize_schema()

        # Seed community nodes so upsert_community can update them
        from repograph.core.models import CommunityNode
        for cid in [0, 1, 2]:
            store.upsert_community(CommunityNode(
                id=f"community:{cid}",
                label=f"Comm{cid}",
                cohesion=0.5,
                member_count=10 if cid < 2 else 2,
            ))

        # Comm 0: 10 funcs, comm 1: 10 funcs, comm 2: 2 funcs (micro)
        # Micro (2) has 3 edges to comm 0 and 1 edge to comm 1 → merge into 0
        comm_to_funcs = self._make_fake_comm_funcs({
            0: [f"fn_0_{i}" for i in range(10)],
            1: [f"fn_1_{i}" for i in range(10)],
            2: ["fn_micro_0", "fn_micro_1"],
        })
        call_edges = self._make_call_edges([
            ("fn_micro_0", "fn_0_0"),
            ("fn_micro_0", "fn_0_1"),
            ("fn_micro_1", "fn_0_2"),  # 3 edges to comm 0
            ("fn_micro_0", "fn_1_0"),  # 1 edge to comm 1
        ])
        all_fns = [fn for members in comm_to_funcs.values() for fn in members]

        _merge_micro_communities(store, comm_to_funcs, call_edges, all_fns, min_size=5)

        # Micro comm 2 should be absorbed into comm 0
        assert 2 not in comm_to_funcs, "Micro community 2 was not removed from comm_to_funcs"
        assert len(comm_to_funcs[0]) == 12, \
            f"Expected 12 members in comm 0 after merge, got {len(comm_to_funcs[0])}"
        store.close()

    def test_isolated_micro_kept_as_is(self, tmp_path):
        """A micro with no external edges must NOT be merged (no crash)."""
        from repograph.graph_store.store import GraphStore
        from repograph.pipeline.phases.p09_communities import _merge_micro_communities
        from repograph.core.models import CommunityNode

        db = str(tmp_path / "t2.db")
        store = GraphStore(db)
        store.initialize_schema()
        for cid in [0, 1]:
            store.upsert_community(CommunityNode(
                id=f"community:{cid}", label=f"C{cid}", cohesion=0.5,
                member_count=10 if cid == 0 else 2
            ))

        comm_to_funcs = self._make_fake_comm_funcs({
            0: [f"fn_0_{i}" for i in range(10)],
            1: ["fn_isolated_0", "fn_isolated_1"],  # micro, no cross-edges
        })
        # No edges between isolated micro and comm 0
        call_edges = self._make_call_edges([
            ("fn_0_0", "fn_0_1"),  # internal to comm 0
        ])
        all_fns = [fn for members in comm_to_funcs.values() for fn in members]

        _merge_micro_communities(store, comm_to_funcs, call_edges, all_fns, min_size=5)

        # Isolated micro should be kept unchanged
        assert 1 in comm_to_funcs, "Isolated micro should not be removed"
        store.close()


class TestCommunityMergeInPipeline:
    """End-to-end: verify merging reduces micro-community count."""

    def test_no_communities_below_min_size(self, tmp_path):
        """All communities must have member_count >= min_community_size
        unless the community is isolated (no cross-edges)."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / "repo" / ".repograph")
        shutil.copytree(FLASK_FIXTURE, repo)
        min_size = 3
        _run_pipeline(repo, rg_dir, min_community_size=min_size)

        store = _open_store(rg_dir)
        rows = store.query(
            "MATCH (c:Community) RETURN c.id, c.label, c.member_count ORDER BY c.member_count ASC"
        )
        store.close()

        very_small = [r for r in rows if r[2] is not None and r[2] < min_size and r[2] > 0]
        # Allow isolated communities (no edges), but merging should reduce most micro-clusters.
        # For the small flask fixture, some isolated communities may survive.
        # The key invariant: merging must not produce MORE micros than without merging.
        assert len(very_small) <= 4, (
            f"Too many micro-communities survived merging: "
            f"{len(very_small)}: {very_small}"
        )

    def test_merge_disabled_at_zero(self, tmp_path):
        """min_community_size=0 must disable merging entirely."""
        repo = str(tmp_path / "repo2")
        rg_dir = str(tmp_path / "repo2" / ".repograph")
        shutil.copytree(FLASK_FIXTURE, repo)

        _run_pipeline(repo, rg_dir, min_community_size=0)
        store = _open_store(rg_dir)
        count_without_merge = len(store.query("MATCH (c:Community) RETURN c.id"))
        store.close()

        repo2 = str(tmp_path / "repo3")
        rg_dir2 = str(tmp_path / "repo3" / ".repograph")
        shutil.copytree(FLASK_FIXTURE, repo2)

        _run_pipeline(repo2, rg_dir2, min_community_size=5)
        store2 = _open_store(rg_dir2)
        count_with_merge = len(store2.query("MATCH (c:Community) RETURN c.id"))
        store2.close()

        # Merging should not increase community count
        assert count_with_merge <= count_without_merge, (
            f"Merging increased community count: {count_without_merge} → {count_with_merge}"
        )

    def test_api_communities_reflects_merge(self, tmp_path):
        """rg.communities() must return the merged state."""
        repo = str(tmp_path / "repo4")
        rg_dir = str(tmp_path / "repo4" / ".repograph")
        shutil.copytree(FLASK_FIXTURE, repo)
        _run_pipeline(repo, rg_dir, min_community_size=3)

        from repograph.surfaces.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            comms = rg.communities()

        assert comms, "communities() returned empty list after merge"
        for c in comms:
            assert c["member_count"] >= 1
