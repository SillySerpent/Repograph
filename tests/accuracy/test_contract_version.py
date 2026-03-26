"""Accuracy: CONTRACT_VERSION matches trust/contract.py."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from repograph.trust.contract import CONTRACT_VERSION

pytestmark = pytest.mark.accuracy


def test_contract_version_semver_like() -> None:
    assert re.match(r"^\d{4}\.\d{2}\.\d{2}$", CONTRACT_VERSION), CONTRACT_VERSION


def test_contract_version_matches_source_file() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "repograph" / "trust" / "contract.py").read_text(encoding="utf-8")
    m = re.search(r'^CONTRACT_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    assert m is not None
    assert m.group(1) == CONTRACT_VERSION
