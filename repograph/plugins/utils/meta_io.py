from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repograph.utils import logging as rg_log


def meta_dir(repograph_dir: str | Path) -> Path:
    base = Path(repograph_dir)
    target = base / "meta"
    target.mkdir(parents=True, exist_ok=True)
    return target


def meta_path(repograph_dir: str | Path, name: str) -> Path:
    return meta_dir(repograph_dir) / name


def read_meta_json(repograph_dir: str | Path, name: str, default: Any = None) -> Any:
    if not repograph_dir:
        return default
    path = Path(repograph_dir) / "meta" / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        rg_log.warn_once(f"meta_io: failed reading {path.name}: {exc}")
        return default


def write_meta_json(repograph_dir: str | Path, name: str, payload: Any) -> Path:
    path = meta_path(repograph_dir, name)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path
