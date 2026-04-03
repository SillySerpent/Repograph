from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import pytest

from tests.support import (
    ArtifactRegistry,
    allocate_free_port,
    assert_no_child_processes_left,
    spawn_repo_process,
    stop_process_tree,
    wait_for_http_ready,
)


def test_spawn_wait_and_stop_http_server(tmp_path: Path) -> None:
    port = allocate_free_port()
    (tmp_path / "index.html").write_text("runtime harness", encoding="utf-8")
    managed = spawn_repo_process(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=tmp_path,
    )

    try:
        wait_for_http_ready(f"http://127.0.0.1:{port}/", timeout_seconds=10.0)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2.0) as response:
            body = response.read().decode("utf-8")
        assert "runtime harness" in body
    finally:
        stop_process_tree(managed)

    assert_no_child_processes_left(managed)


def test_stop_process_tree_is_safe_for_already_exited_process(tmp_path: Path) -> None:
    managed = spawn_repo_process(
        [sys.executable, "-c", "print('done')"],
        cwd=tmp_path,
    )
    managed.process.wait(timeout=5.0)

    assert stop_process_tree(managed) == 0
    assert_no_child_processes_left(managed)
    assert "done" in managed.read_stdout()


def test_wait_for_http_ready_times_out_cleanly() -> None:
    port = allocate_free_port()
    with pytest.raises(TimeoutError):
        wait_for_http_ready(
            f"http://127.0.0.1:{port}/",
            timeout_seconds=0.2,
            interval_seconds=0.05,
        )


def test_artifact_registry_cleans_files_and_directories(tmp_path: Path) -> None:
    registry = ArtifactRegistry()
    file_path = registry.register(tmp_path / "artifact.txt")
    dir_path = registry.register(tmp_path / "artifact-dir")
    nested_path = dir_path / "nested.txt"

    file_path.write_text("artifact", encoding="utf-8")
    dir_path.mkdir()
    nested_path.write_text("nested", encoding="utf-8")

    registry.cleanup()

    assert not file_path.exists()
    assert not dir_path.exists()
