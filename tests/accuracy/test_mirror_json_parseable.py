"""Every mirror artifact must be valid JSON after sync (export pipeline health)."""
from __future__ import annotations

import json
import os

import pytest

pytestmark = [pytest.mark.accuracy, pytest.mark.integration]

_PYTHON_SIMPLE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_simple"),
)


def test_all_mirror_json_files_parse(tmp_path) -> None:
    """Walk ``mirror/**/*.json`` and ensure each file parses."""
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    rg_dir = str(tmp_path / ".repograph")
    run_full_pipeline(
        RunConfig(
            repo_root=_PYTHON_SIMPLE,
            repograph_dir=rg_dir,
            include_git=False,
            include_embeddings=False,
            full=True,
        )
    )
    mirror_dir = os.path.join(rg_dir, "mirror")
    assert os.path.isdir(mirror_dir)
    count = 0
    for root, _, files in os.walk(mirror_dir):
        for name in files:
            if not name.endswith(".json"):
                continue
            count += 1
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as f:
                json.load(f)
    assert count >= 1
