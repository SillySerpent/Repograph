"""Unit tests for staleness tracking."""
from __future__ import annotations

import os
import tempfile
import pytest
from repograph.docs.staleness import StalenessTracker


@pytest.fixture
def tracker(tmp_path):
    rg_dir = str(tmp_path / ".repograph")
    os.makedirs(rg_dir, exist_ok=True)
    return StalenessTracker(rg_dir)


class TestStalenessTracker:
    def test_new_artifact_not_stale(self, tracker, tmp_path):
        # Create a real file
        src = tmp_path / "src.py"
        src.write_text("def foo(): pass")
        from repograph.utils.hashing import hash_file
        h = hash_file(str(src))

        tracker.record_artifact(
            "mirror:src.py", "mirror", {"src.py": h}
        )
        result = tracker.check_artifact("mirror:src.py", str(tmp_path))
        assert result.is_stale is False

    def test_stale_when_file_changes(self, tracker, tmp_path):
        src = tmp_path / "src.py"
        src.write_text("def foo(): pass")
        from repograph.utils.hashing import hash_file
        old_hash = hash_file(str(src))

        tracker.record_artifact("mirror:src.py", "mirror", {"src.py": old_hash})

        # Now change the file
        src.write_text("def foo(): return 1  # changed")

        result = tracker.check_artifact("mirror:src.py", str(tmp_path))
        assert result.is_stale is True
        assert "src.py" in result.stale_reason

    def test_unrelated_file_change_does_not_stale(self, tracker, tmp_path):
        src = tmp_path / "src.py"
        other = tmp_path / "other.py"
        src.write_text("def foo(): pass")
        other.write_text("x = 1")
        from repograph.utils.hashing import hash_file
        h = hash_file(str(src))

        tracker.record_artifact("mirror:src.py", "mirror", {"src.py": h})
        # Change other.py, not src.py
        other.write_text("x = 999")

        result = tracker.check_artifact("mirror:src.py", str(tmp_path))
        assert result.is_stale is False

    def test_mark_stale_for_file(self, tracker, tmp_path):
        src = tmp_path / "a.py"
        src.write_text("x = 1")
        from repograph.utils.hashing import hash_file
        h = hash_file(str(src))

        tracker.record_artifact("mirror:a.py", "mirror", {"a.py": h})
        tracker.record_artifact("context:a.py", "context_doc", {"a.py": h})

        staled = tracker.mark_stale_for_file("a.py")
        assert "mirror:a.py" in staled
        assert "context:a.py" in staled
        assert tracker.is_stale("mirror:a.py")

    def test_clear_stale(self, tracker, tmp_path):
        tracker.record_artifact("mirror:x.py", "mirror", {})
        tracker.mark_stale_for_file("x.py")  # won't match but sets stale
        # Manually mark then clear
        tracker._data["mirror:x.py"]["is_stale"] = True
        tracker.clear_stale("mirror:x.py")
        assert not tracker.is_stale("mirror:x.py")

    def test_unknown_artifact_is_stale(self, tracker, tmp_path):
        result = tracker.check_artifact("nonexistent", str(tmp_path))
        assert result.is_stale is True

    def test_persistence(self, tmp_path):
        rg_dir = str(tmp_path / ".repograph")
        os.makedirs(rg_dir, exist_ok=True)
        t1 = StalenessTracker(rg_dir)
        t1.record_artifact("x", "mirror", {"f.py": "abc123"})
        t1.save()

        t2 = StalenessTracker(rg_dir)
        assert "x" in t2._data
