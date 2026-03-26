"""Structural invariant checks Q1–Q6 on a real GraphStore."""
from __future__ import annotations

import pytest

from repograph.quality import run_sync_invariants

pytestmark = [pytest.mark.quality, pytest.mark.integration]


def test_sync_invariants_pass_on_python_simple(simple_store) -> None:
    """After full pipeline on python_simple, Q1–Q6 must report no violations."""
    result = run_sync_invariants(simple_store)
    assert result.ok, [f"{v.code}: {v.message} {v.detail}" for v in result.violations]


def test_sync_invariants_pass_on_python_flask(flask_store) -> None:
    """Flask-style fixture: structural invariants must hold on a larger graph."""
    result = run_sync_invariants(flask_store)
    assert result.ok, [f"{v.code}: {v.message} {v.detail}" for v in result.violations]
