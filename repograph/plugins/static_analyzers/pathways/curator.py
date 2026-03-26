# Canonical curated-pathway loader owned by the pathways plugin.
"""Pathway curator — loads and validates pathways.yml curated definitions."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

from repograph.config import repograph_dir


@dataclass
class CuratedPathwayDef:
    """A single curated pathway definition from pathways.yml."""
    name: str
    display_name: str
    description: str
    entry_file: str
    entry_function: str
    terminal_hint: str = "return"
    tags: list[str] = field(default_factory=list)


class PathwayCurator:
    """Loads curated pathway definitions from ``pathways.yml``."""

    def __init__(self, repo_root: str) -> None:
        self._defs: dict[str, CuratedPathwayDef] = {}
        self._by_entry_function: dict[str, CuratedPathwayDef] = {}
        self._load(repo_root)

    def _load(self, repo_root: str) -> None:
        candidates = (
            os.path.join(repograph_dir(repo_root), "pathways.yml"),
            os.path.join(repo_root, "pathways.yml"),
        )
        data: dict | None = None
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                break
            except Exception:
                continue
        if data is None:
            return

        for item in data.get("pathways", []) or []:
            if not item or not isinstance(item, dict):
                continue
            name = item.get("name", "")
            if not name:
                continue
            entry = item.get("entry") or {}
            defn = CuratedPathwayDef(
                name=name,
                display_name=item.get("display_name") or name.replace("_", " ").title(),
                description=item.get("description") or "",
                entry_file=entry.get("file") or "",
                entry_function=entry.get("function") or "",
                terminal_hint=item.get("terminal_hint") or "return",
                tags=item.get("tags") or [],
            )
            self._defs[name] = defn
            if defn.entry_function:
                self._by_entry_function[defn.entry_function] = defn

    def get(self, name: str) -> Optional[CuratedPathwayDef]:
        return self._defs.get(name)

    def get_by_entry_function(self, func_name: str) -> Optional[CuratedPathwayDef]:
        return self._by_entry_function.get(func_name)

    def all_defs(self) -> list[CuratedPathwayDef]:
        return list(self._defs.values())

    def has_curated(self) -> bool:
        return bool(self._defs)
