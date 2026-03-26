from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Any
import json

DEFAULT_RULE_PACKS: dict[str, dict[str, Any]] = {
    "private_surface_access": {"enabled": True, "family": "contract_rules", "description": "Detects imports that bypass public/private module boundaries directly."},
    "config_boundary_reads": {"enabled": True, "family": "contract_rules", "description": "Detects UI-facing files reading environment/config directly."},
    "db_shortcuts": {"enabled": True, "family": "boundary_shortcuts", "description": "Detects direct UI/API/route access to DB/ORM layers."},
    "ui_boundary_paths": {"enabled": True, "family": "boundary_shortcuts", "description": "Detects UI imports that jump directly into domain/service layers."},
}
RULE_PACK_CONFIG_CANDIDATES = (
    '.repograph/rule_packs.json',
    'repograph.rule_packs.json',
)

@dataclass(frozen=True)
class RulePackConfig:
    packs: dict[str, dict[str, Any]]
    source: str | None = None

    def enabled_for_family(self, family: str) -> list[str]:
        return [name for name, meta in self.packs.items() if meta.get("enabled", True) and meta.get("family") == family]

    def override_for(self, pack: str) -> dict[str, Any]:
        return dict(self.packs.get(pack, {}))

    def as_dict(self) -> dict[str, Any]:
        families = {family: self.enabled_for_family(family) for family in sorted({meta.get("family", "analysis") for meta in self.packs.values()})}
        severity_overrides = {name: str(meta.get('severity_override')) for name, meta in self.packs.items() if meta.get('severity_override')}
        return {"packs": self.packs, "families": families, "source": self.source, "severity_overrides": severity_overrides}


def _load_repo_rule_pack_overrides(service: Any | None = None) -> tuple[dict[str, dict[str, Any]], str | None]:
    repo_root = Path(getattr(service, 'repo_path', '.') if service else '.').resolve()
    for rel in RULE_PACK_CONFIG_CANDIDATES:
        candidate = repo_root / rel
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text())
        except Exception:
            continue
        packs = data.get('packs') if isinstance(data, dict) else None
        if isinstance(packs, dict):
            clean: dict[str, dict[str, Any]] = {}
            for name, meta in packs.items():
                if isinstance(name, str) and isinstance(meta, dict):
                    clean[name] = dict(meta)
            return clean, str(candidate)
    return {}, None


def get_rule_pack_config(service: Any | None = None) -> RulePackConfig:
    merged = {name: dict(meta) for name, meta in DEFAULT_RULE_PACKS.items()}
    overrides, source = _load_repo_rule_pack_overrides(service)
    for name, meta in overrides.items():
        merged[name] = {**merged.get(name, {}), **meta}
    return RulePackConfig(packs=merged, source=source)


def apply_rule_pack_policy(finding: dict[str, Any], *, config: RulePackConfig | None = None) -> dict[str, Any]:
    config = config or get_rule_pack_config()
    out = dict(finding)
    pack = str(out.get('rule_pack') or '')
    if not pack:
        return out
    override = config.override_for(pack)
    if 'severity_override' in override and override['severity_override']:
        out['severity'] = str(override['severity_override'])
        pol = dict(out.get('policy') or {})
        pol['overridden_by_rule_pack'] = True
        out['policy'] = pol
    out['rule_pack_enabled'] = bool(override.get('enabled', True))
    return out


def summarize_rule_packs(findings: Iterable[dict[str, Any]], *, config: RulePackConfig | None = None) -> dict[str, Any]:
    config = config or get_rule_pack_config()
    counts: dict[str, int] = {name: 0 for name in config.packs}
    severity_overrides: dict[str, str] = {}
    for name, meta in config.packs.items():
        if meta.get('severity_override'):
            severity_overrides[name] = str(meta['severity_override'])
    for item in findings:
        pack = str(item.get("rule_pack") or "")
        if pack:
            counts[pack] = counts.get(pack, 0) + 1
    return {
        "packs": {name: {**meta, "count": counts.get(name, 0)} for name, meta in config.packs.items()},
        "families": config.as_dict()["families"],
        "source": config.source,
        "severity_overrides": severity_overrides,
    }



def save_rule_pack_overrides(service: Any | None, packs: dict[str, dict[str, Any]]) -> RulePackConfig:
    repo_root = Path(getattr(service, 'repo_path', '.') if service else '.').resolve()
    target = repo_root / '.repograph' / 'rule_packs.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    clean: dict[str, dict[str, Any]] = {}
    for name, meta in (packs or {}).items():
        if isinstance(name, str) and isinstance(meta, dict):
            keep: dict[str, Any] = {}
            if 'enabled' in meta:
                keep['enabled'] = bool(meta['enabled'])
            sev = meta.get('severity_override')
            if sev:
                keep['severity_override'] = str(sev)
            clean[name] = keep
    payload = {'packs': clean}
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return get_rule_pack_config(service)
