"""Behavior/docs alignment checks for high-drift user-facing surfaces."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from repograph.settings import list_setting_metadata
from repograph.surfaces.cli.summary_helpers import (
    SUMMARY_ENTRY_POINT_KEYS,
    SUMMARY_HOTSPOT_KEYS,
    SUMMARY_PATHWAY_KEYS,
    SUMMARY_RISK_KEYS,
    SUMMARY_TOP_LEVEL_KEYS,
    SUMMARY_TRUST_KEYS,
    build_summary_payload,
)

pytestmark = [pytest.mark.quality]

_BACKTICK_RE = re.compile(r"`([^`]+)`")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_REFERENCE = _REPO_ROOT / "docs" / "CLI_REFERENCE.md"
_AGENT_USAGE = _REPO_ROOT / "docs" / "AGENT_USAGE.md"
_CONFIG_HYGIENE = _REPO_ROOT / "docs" / "CONFIG_HYGIENE.md"


def _extract_doc_keys(doc_path: Path, label: str) -> list[str]:
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line.startswith(label):
            continue
        _, _, tail = line.partition(":")
        block = [tail]
        for continuation in lines[index + 1 :]:
            stripped = continuation.strip()
            if not stripped:
                break
            if stripped.startswith("#") or stripped.startswith("- "):
                break
            block.append(stripped)
        return _BACKTICK_RE.findall(" ".join(block))
    raise AssertionError(f"Could not find line starting with {label!r} in {doc_path}")


def _sample_summary_payload() -> dict[str, Any]:
    return build_summary_payload(
        "/tmp/example-repo",
        {
            "purpose": "Example repo for summary contract alignment tests.",
            "stats": {
                "repo": "example-repo",
                "files": 7,
                "functions": 11,
                "classes": 2,
                "calls": 14,
            },
            "health": {
                "status": "healthy",
                "sync_mode": "full",
                "analysis_readiness": {
                    "runtime_overlay_applied": True,
                    "coverage_overlay_applied": False,
                },
                "dynamic_analysis": {
                    "requested": True,
                    "executed": True,
                },
            },
            "entry_points": [
                {
                    "qualified_name": "app.main",
                    "file_path": "app.py",
                    "entry_score": 12.5,
                    "entry_caller_count": 0,
                    "entry_callee_count": 4,
                    "entry_score_base": 2.5,
                    "entry_score_multipliers": {"cli_surface": 1.4},
                }
            ],
            "pathways": [
                {
                    "name": "main flow",
                    "entry_function": "app.main",
                    "step_count": 4,
                    "importance_score": 0.9,
                    "confidence": 0.95,
                    "source": "static",
                }
            ],
            "modules": [
                {
                    "display": "app",
                    "category": "production",
                    "summary": "Core application module.",
                    "function_count": 7,
                    "class_count": 2,
                    "test_function_count": 1,
                    "dead_code_count": 1,
                    "duplicate_count": 0,
                }
            ],
            "dead_code": {
                "definitely_dead": [{"qualified_name": "app.unused"}],
                "probably_dead": [],
                "definitely_dead_tooling": [],
                "probably_dead_tooling": [],
            },
            "duplicates": [{"name": "duplicate_helper", "severity": "high"}],
            "doc_warnings": [{"severity": "high"}],
            "report_warnings": ["Example warning for contract coverage."],
        },
    )


def test_summary_contract_metadata_matches_payload_shape() -> None:
    payload = _sample_summary_payload()

    assert tuple(payload.keys()) == SUMMARY_TOP_LEVEL_KEYS
    assert tuple(payload["trust"].keys()) == SUMMARY_TRUST_KEYS
    assert tuple(payload["top_entry_points"][0].keys()) == SUMMARY_ENTRY_POINT_KEYS
    assert tuple(payload["top_pathways"][0].keys()) == SUMMARY_PATHWAY_KEYS
    assert tuple(payload["major_risks"][0].keys()) == SUMMARY_RISK_KEYS
    assert tuple(payload["structural_hotspots"][0].keys()) == SUMMARY_HOTSPOT_KEYS


def test_cli_reference_documents_summary_contract_keys() -> None:
    assert _extract_doc_keys(_CLI_REFERENCE, "- Top-level keys") == list(SUMMARY_TOP_LEVEL_KEYS)
    assert _extract_doc_keys(_CLI_REFERENCE, "- `trust`") == list(SUMMARY_TRUST_KEYS)
    assert _extract_doc_keys(_CLI_REFERENCE, "- `top_entry_points[]`") == list(SUMMARY_ENTRY_POINT_KEYS)
    assert _extract_doc_keys(_CLI_REFERENCE, "- `top_pathways[]`") == list(SUMMARY_PATHWAY_KEYS)
    assert _extract_doc_keys(_CLI_REFERENCE, "- `major_risks[]`") == list(SUMMARY_RISK_KEYS)
    assert _extract_doc_keys(_CLI_REFERENCE, "- `structural_hotspots[]`") == list(SUMMARY_HOTSPOT_KEYS)


def test_cli_reference_documents_all_known_settings_keys() -> None:
    documented = set(_extract_doc_keys(_CLI_REFERENCE, "Known settings keys"))
    metadata_keys = {item["key"] for item in list_setting_metadata()}
    assert documented == metadata_keys


def test_config_hygiene_matches_settings_scaffold_behavior() -> None:
    text = _CONFIG_HYGIENE.read_text(encoding="utf-8")
    assert "clears overrides, keeps the settings document" in text
    assert "removes settings.json" not in text


def test_agent_usage_summary_step_mentions_trust_and_risks() -> None:
    text = _AGENT_USAGE.read_text(encoding="utf-8")
    assert "trust status" in text
    assert "Major risks plus structural hotspots" in text
    assert "Dynamic-analysis status and warnings" in text
