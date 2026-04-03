"""Run pinned Pyright on ``repograph/`` and ``tests``.

The project-level ``[tool.pyright]`` configuration in ``pyproject.toml`` is the
checked-in type-checking contract. This test pins the CLI version so local runs
and CI use the same Pyright release.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYRIGHT_VERSION = "1.1.408"


def _run_pyright() -> subprocess.CompletedProcess[str]:
    cmd = [
        "npx",
        "--yes",
        f"pyright@{_PYRIGHT_VERSION}",
        "--project",
        str(_REPO_ROOT / "pyproject.toml"),
        str(_REPO_ROOT / "repograph"),
        str(_REPO_ROOT / "tests"),
    ]
    return subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "FORCE_COLOR": "0"},
        timeout=600,
    )


@pytest.mark.pyright
def test_pyright_clean_on_repograph_and_tests() -> None:
    if shutil.which("npx") is None:
        pytest.skip("npx not found; install Node.js to run Pyright in this test")

    proc = _run_pyright()
    out = proc.stdout or ""
    err = proc.stderr or ""
    if proc.returncode == 0:
        return

    # Full reports to the terminal (pytest may truncate long messages otherwise).
    print("\n--- pyright stdout ---\n", out, file=sys.stderr, sep="")
    print("\n--- pyright stderr ---\n", err, file=sys.stderr, sep="")
    combined = f"{out}\n{err}".strip()
    pytest.fail(
        f"pyright {_PYRIGHT_VERSION} exited {proc.returncode}. Full output below.\n\n{combined}",
    )
