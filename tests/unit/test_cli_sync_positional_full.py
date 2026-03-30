"""``repograph sync full`` must index cwd, not a subdirectory named ``full``.

Typer binds the bare word ``full`` to the path argument unless we normalize it.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from repograph.cli import app


@pytest.fixture
def uninitialized_repo(tmp_path):
    """Minimal tree so sync can run (no graph.db — first sync forces full)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    rg = repo / ".repograph"
    rg.mkdir()
    (rg / "meta").mkdir()
    return repo


def test_sync_positional_full_uses_cwd_not_subdir_full(uninitialized_repo):
    """``repograph sync full`` from repo root must not set repo_root to .../full."""
    captured: dict = {}

    def capture(cfg):
        captured["repo_root"] = cfg.repo_root
        captured["full"] = cfg.full
        return {"files": 0}

    repo = str(uninitialized_repo)
    runner = CliRunner()
    old_cwd = os.getcwd()
    try:
        os.chdir(repo)
        with patch("repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay", side_effect=capture):
            result = runner.invoke(app, ["sync", "full"])
    finally:
        os.chdir(old_cwd)

    assert result.exit_code == 0, result.stdout + str(result.stderr)
    assert os.path.abspath(captured["repo_root"]) == os.path.abspath(repo)
    assert captured["full"] is True
