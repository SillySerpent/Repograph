
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Iterable
import json

STATUS_CONFIG_REL = '.repograph/finding_statuses.json'
ALLOWED_STATUSES = {'open', 'approved_exception', 'planned_refactor', 'ignored'}


def _repo_root(service: Any | None = None) -> Path:
    return Path(getattr(service, 'repo_path', '.') if service else '.').resolve()


def _status_path(service: Any | None = None) -> Path:
    return _repo_root(service) / STATUS_CONFIG_REL


@dataclass(frozen=True)
class FindingStatusStore:
    statuses: dict[str, dict[str, Any]]
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {'statuses': self.statuses, 'source': self.source}


def finding_key(finding: dict[str, Any]) -> str:
    raw = '|'.join([
        str(finding.get('kind') or ''),
        str(finding.get('file_path') or ''),
        str(finding.get('reason') or ''),
        str(finding.get('rule_pack') or ''),
    ])
    return sha1(raw.encode('utf-8')).hexdigest()[:16]


def get_finding_status_store(service: Any | None = None) -> FindingStatusStore:
    path = _status_path(service)
    if not path.exists():
        return FindingStatusStore(statuses={}, source=None)
    try:
        data = json.loads(path.read_text())
        statuses = data.get('statuses') if isinstance(data, dict) else None
        if not isinstance(statuses, dict):
            statuses = {}
    except Exception:
        statuses = {}
    clean: dict[str, dict[str, Any]] = {}
    for key, value in statuses.items():
        if isinstance(key, str) and isinstance(value, dict):
            clean[key] = dict(value)
    return FindingStatusStore(statuses=clean, source=str(path))


def save_finding_status_store(service: Any | None, statuses: dict[str, dict[str, Any]]) -> FindingStatusStore:
    path = _status_path(service)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'statuses': statuses}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return FindingStatusStore(statuses=statuses, source=str(path))


def update_finding_status(service: Any | None, finding_id: str, status: str, note: str | None = None) -> dict[str, Any]:
    norm = status if status in ALLOWED_STATUSES else 'open'
    store = get_finding_status_store(service)
    statuses = dict(store.statuses)
    statuses[finding_id] = {
        'status': norm,
        'note': (note or '').strip(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    save_finding_status_store(service, statuses)
    return statuses[finding_id]


def annotate_finding_statuses(findings: Iterable[dict[str, Any]], *, store: FindingStatusStore | None = None) -> list[dict[str, Any]]:
    store = store or get_finding_status_store()
    out = []
    for finding in findings:
        item = dict(finding)
        fid = finding_key(item)
        item['finding_id'] = fid
        item['status'] = store.statuses.get(fid, {}).get('status', 'open')
        item['status_note'] = store.statuses.get(fid, {}).get('note', '')
        item['status_updated_at'] = store.statuses.get(fid, {}).get('updated_at')
        out.append(item)
    return out


def summarize_finding_statuses(findings: Iterable[dict[str, Any]]) -> dict[str, Any]:
    summary = {'open': 0, 'approved_exception': 0, 'planned_refactor': 0, 'ignored': 0}
    total = 0
    for finding in findings:
        total += 1
        status = str(finding.get('status') or 'open')
        summary[status] = summary.get(status, 0) + 1
    return {'total': total, 'status_summary': summary}
