"""Integration tests for incremental sync correctness."""
from __future__ import annotations

import os
import shutil
import tempfile
import pytest

SIMPLE_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_simple")


class TestIncrementalSync:
    def test_changed_file_detected(self, tmp_path):
        """A modified file should appear in the diff."""
        import shutil
        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        from repograph.pipeline.incremental import IncrementalDiff
        from repograph.pipeline.phases.p01_walk import run as walk

        # Copy fixture to writable dir
        repo = str(tmp_path / "repo")
        shutil.copytree(os.path.abspath(SIMPLE_FIXTURE), repo)
        rg_dir = str(tmp_path / ".repograph")

        config = RunConfig(repo_root=repo, repograph_dir=rg_dir,
                           include_git=False, full=True)
        run_full_pipeline(config)

        # Save index
        differ = IncrementalDiff(rg_dir)
        files = walk(repo)
        differ.save_index({fr.path: fr for fr in files})

        # Modify a file
        main_py = os.path.join(repo, "main.py")
        with open(main_py, "a") as f:
            f.write("\n# modified\n")

        # Recompute
        new_files = walk(repo)
        diff = differ.compute({fr.path: fr for fr in new_files})

        assert "main.py" in diff.changed
        assert not diff.added
        assert not diff.removed

    def test_added_file_detected(self, tmp_path):
        import shutil
        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        from repograph.pipeline.incremental import IncrementalDiff
        from repograph.pipeline.phases.p01_walk import run as walk

        repo = str(tmp_path / "repo")
        shutil.copytree(os.path.abspath(SIMPLE_FIXTURE), repo)
        rg_dir = str(tmp_path / ".repograph")

        config = RunConfig(repo_root=repo, repograph_dir=rg_dir,
                           include_git=False, full=True)
        run_full_pipeline(config)
        differ = IncrementalDiff(rg_dir)
        files = walk(repo)
        differ.save_index({fr.path: fr for fr in files})

        # Add a new file
        new_file = os.path.join(repo, "new_module.py")
        with open(new_file, "w") as f:
            f.write("def new_function():\n    pass\n")

        new_files = walk(repo)
        diff = differ.compute({fr.path: fr for fr in new_files})
        assert "new_module.py" in diff.added

    def test_deleted_file_detected(self, tmp_path):
        import shutil
        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        from repograph.pipeline.incremental import IncrementalDiff
        from repograph.pipeline.phases.p01_walk import run as walk

        repo = str(tmp_path / "repo")
        shutil.copytree(os.path.abspath(SIMPLE_FIXTURE), repo)
        rg_dir = str(tmp_path / ".repograph")

        config = RunConfig(repo_root=repo, repograph_dir=rg_dir,
                           include_git=False, full=True)
        run_full_pipeline(config)
        differ = IncrementalDiff(rg_dir)
        files = walk(repo)
        differ.save_index({fr.path: fr for fr in files})

        # Delete a file
        os.remove(os.path.join(repo, "services.py"))

        new_files = walk(repo)
        diff = differ.compute({fr.path: fr for fr in new_files})
        assert "services.py" in diff.removed

    def test_incremental_sync_updates_graph(self, tmp_path):
        import shutil
        from repograph.graph_store.store import GraphStore
        from repograph.pipeline.runner import RunConfig, run_full_pipeline, run_incremental_pipeline
        from repograph.pipeline.incremental import IncrementalDiff
        from repograph.pipeline.phases.p01_walk import run as walk

        repo = str(tmp_path / "repo")
        shutil.copytree(os.path.abspath(SIMPLE_FIXTURE), repo)
        rg_dir = str(tmp_path / ".repograph")

        config = RunConfig(repo_root=repo, repograph_dir=rg_dir,
                           include_git=False, full=True)
        run_full_pipeline(config)

        differ = IncrementalDiff(rg_dir)
        files = walk(repo)
        differ.save_index({fr.path: fr for fr in files})

        # Add new function
        new_file = os.path.join(repo, "extra.py")
        with open(new_file, "w") as f:
            f.write("def brand_new_function(x, y):\n    return x * y\n")

        # Run incremental
        run_incremental_pipeline(config)

        # Verify new function is in the graph
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        results = store.search_functions_by_name("brand_new_function")
        assert len(results) >= 1

    def test_stale_flags_on_change(self, tmp_path):
        import shutil
        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        from repograph.pipeline.incremental import IncrementalDiff
        from repograph.pipeline.phases.p01_walk import run as walk
        from repograph.docs.staleness import StalenessTracker

        repo = str(tmp_path / "repo")
        shutil.copytree(os.path.abspath(SIMPLE_FIXTURE), repo)
        rg_dir = str(tmp_path / ".repograph")

        config = RunConfig(repo_root=repo, repograph_dir=rg_dir,
                           include_git=False, full=True)
        run_full_pipeline(config)
        differ = IncrementalDiff(rg_dir)
        files = walk(repo)
        differ.save_index({fr.path: fr for fr in files})

        # Record an artifact depending on services.py
        staleness = StalenessTracker(rg_dir)
        from repograph.utils.hashing import hash_file
        h = hash_file(os.path.join(repo, "services.py"))
        staleness.record_artifact("mirror:services.py", "mirror", {"services.py": h})
        staleness.save()

        # Modify services.py
        with open(os.path.join(repo, "services.py"), "a") as f:
            f.write("\n# changed\n")

        # Mark stale
        staleness2 = StalenessTracker(rg_dir)
        staled = staleness2.mark_stale_for_file("services.py")
        assert "mirror:services.py" in staled
