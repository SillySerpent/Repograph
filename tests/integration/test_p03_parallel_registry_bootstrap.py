"""Regression: parallel phase-3 parse must not race parser registration."""
from __future__ import annotations

from pathlib import Path

import pytest

from repograph.pipeline.runner import RunConfig, run_full_pipeline


pytestmark = pytest.mark.integration


def _write_many_python_files(repo_root: Path, *, count: int = 8) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    for idx in range(count):
        fp = repo_root / f"mod_{idx}.py"
        fp.write_text(
            (
                f"def f_{idx}() -> int:\n"
                f"    return {idx}\n"
            ),
            encoding="utf-8",
        )


def test_parallel_p03_no_duplicate_parser_registration(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repograph_dir = tmp_path / ".repograph"
    _write_many_python_files(repo_root, count=10)  # Above p03 parallel threshold.

    stats = run_full_pipeline(
        RunConfig(
            repo_root=str(repo_root),
            repograph_dir=str(repograph_dir),
            include_git=False,
            include_embeddings=False,
            full=True,
            continue_on_error=False,
            strict=True,
        )
    )
    assert stats.get("files", 0) >= 10

    logs_path = repograph_dir / "logs" / "latest" / "all.jsonl"
    assert logs_path.exists(), "Expected structured logs file to exist"
    logs_text = logs_path.read_text(encoding="utf-8")
    assert "parser plugin 'parser.python' already registered" not in logs_text
