from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

SEVERITY_SCORE = {"critical": 100, "high": 85, "medium": 55, "low": 25}
DEFAULT_POLICY_BY_SEVERITY = {
    "critical": {"action": "block_and_review", "blocks_autofix": True},
    "high": {"action": "review_required", "blocks_autofix": True},
    "medium": {"action": "warn_and_review", "blocks_autofix": False},
    "low": {"action": "warn_only", "blocks_autofix": False},
}
CATEGORY_BY_KIND = {
    "ui_to_db_shortcut": "boundary",
    "api_to_db_shortcut": "boundary",
    "route_to_db_shortcut": "boundary",
    "repository_bypass": "boundary",
    "ui_direct_config_read": "config_boundary",
    "private_surface_bypass": "private_surface",
    "ui_cross_layer_shortcut": "boundary",
    "ui_domain_bypass": "boundary",
}
FAMILY_BY_KIND = {
    "ui_to_db_shortcut": "boundary_shortcuts",
    "api_to_db_shortcut": "boundary_shortcuts",
    "route_to_db_shortcut": "boundary_shortcuts",
    "repository_bypass": "boundary_shortcuts",
    "ui_cross_layer_shortcut": "boundary_shortcuts",
    "ui_domain_bypass": "boundary_shortcuts",
    "ui_direct_config_read": "contract_rules",
    "private_surface_bypass": "contract_rules",
}

@dataclass(frozen=True)
class SeverityPolicy:
    severity: str
    severity_score: int
    action: str
    blocks_autofix: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "severity_score": self.severity_score,
            "action": self.action,
            "blocks_autofix": self.blocks_autofix,
        }


def policy_for(severity: str) -> SeverityPolicy:
    sev = severity if severity in SEVERITY_SCORE else "low"
    base = DEFAULT_POLICY_BY_SEVERITY[sev]
    return SeverityPolicy(severity=sev, severity_score=SEVERITY_SCORE[sev], action=base["action"], blocks_autofix=base["blocks_autofix"])


def annotate_finding(finding: dict[str, Any], *, family: str | None = None) -> dict[str, Any]:
    severity = str(finding.get("severity") or "low")
    kind = str(finding.get("kind") or "unknown")
    policy = policy_for(severity)
    out = dict(finding)
    out.setdefault("category", CATEGORY_BY_KIND.get(kind, "analysis"))
    out.setdefault("family", family or FAMILY_BY_KIND.get(kind, "analysis"))
    out.setdefault("severity_score", policy.severity_score)
    out.setdefault("policy", policy.as_dict())
    return out


def summarize_findings(findings: Iterable[dict[str, Any]]) -> dict[str, Any]:
    severity_summary: dict[str, int] = {k: 0 for k in SEVERITY_SCORE}
    category_summary: dict[str, int] = {}
    family_summary: dict[str, int] = {}
    policy_actions: dict[str, int] = {}
    total = 0
    for finding in findings:
        total += 1
        sev = str(finding.get("severity") or "low")
        severity_summary[sev] = severity_summary.get(sev, 0) + 1
        category = str(finding.get("category") or "analysis")
        category_summary[category] = category_summary.get(category, 0) + 1
        family = str(finding.get("family") or "analysis")
        family_summary[family] = family_summary.get(family, 0) + 1
        action = str((finding.get("policy") or {}).get("action") or policy_for(sev).action)
        policy_actions[action] = policy_actions.get(action, 0) + 1
    return {
        "total": total,
        "severity_summary": severity_summary,
        "category_summary": category_summary,
        "family_summary": family_summary,
        "policy_actions": policy_actions,
    }
