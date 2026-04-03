from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from repograph.pipeline.runner import RunConfig, run_full_pipeline
from repograph.surfaces.api import RepoGraph
from repograph.surfaces.cli import app

STRAYRATZ_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "StrayRatz"),
)


@pytest.fixture
def synced_strayratz_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "StrayRatz"
    shutil.copytree(
        STRAYRATZ_FIXTURE,
        repo,
        ignore=shutil.ignore_patterns(".repograph", "__pycache__", "*.pyc"),
    )
    run_full_pipeline(
        RunConfig(
            repo_root=str(repo),
            repograph_dir=str(repo / ".repograph"),
            include_git=False,
            include_embeddings=False,
            full=True,
        )
    )
    return repo


def test_summary_json_on_strayratz_has_real_overview_sections(synced_strayratz_repo: Path) -> None:
    result = CliRunner().invoke(app, ["summary", str(synced_strayratz_repo), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["repo"] == "StrayRatz"
    assert "supplement" in payload["purpose"].lower()
    assert payload["top_entry_points"]
    assert payload["major_risks"]
    assert payload["structural_hotspots"]


def test_entry_points_on_strayratz_prioritize_route_surfaces(synced_strayratz_repo: Path) -> None:
    rg = RepoGraph(
        str(synced_strayratz_repo),
        repograph_dir=str(synced_strayratz_repo / ".repograph"),
    )
    try:
        entry_points = rg.entry_points(limit=20)
    finally:
        rg.close()

    route_surface_names = {
        ep["qualified_name"].rsplit(".", 1)[-1]
        for ep in entry_points
        if "app/routes.py" in ep.get("file_path", "") or "app/admin.py" in ep.get("file_path", "")
    }

    assert route_surface_names, "Expected route/admin surfaces in the top StrayRatz entry points"
    assert {"login", "register", "survey"} & route_surface_names
