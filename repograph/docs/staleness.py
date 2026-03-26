"""StalenessTracker — hash-based stale detection for generated artifacts."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from repograph.core.models import ArtifactMeta, StaleResult
from repograph.utils.hashing import hash_file, hash_string


class StalenessTracker:
    """
    Tracks source hashes for every generated artifact.
    Persisted as a JSON file in .repograph/meta/staleness.json.
    """

    def __init__(self, repograph_dir: str) -> None:
        self._meta_path = os.path.join(repograph_dir, "meta", "staleness.json")
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if os.path.exists(self._meta_path):
            try:
                with open(self._meta_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._meta_path), exist_ok=True)
        with open(self._meta_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def record_artifact(
        self,
        artifact_id: str,
        artifact_type: str,
        source_hashes: dict[str, str],
    ) -> None:
        """Record an artifact and its source file hashes."""
        self._data[artifact_id] = {
            "artifact_type": artifact_type,
            "source_hashes": source_hashes,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "is_stale": False,
            "stale_reason": None,
        }

    def check_artifact(self, artifact_id: str, repo_root: str) -> StaleResult:
        """Check if an artifact is stale by comparing current file hashes."""
        if artifact_id not in self._data:
            return StaleResult(is_stale=True, stale_reason="artifact not recorded")

        meta = self._data[artifact_id]
        for file_path, stored_hash in meta.get("source_hashes", {}).items():
            abs_path = os.path.join(repo_root, file_path)
            current_hash = hash_file(abs_path)
            if current_hash != stored_hash:
                return StaleResult(
                    is_stale=True,
                    stale_reason=f"{file_path} changed since last sync",
                )
        return StaleResult(is_stale=False)

    def mark_stale_for_file(self, file_path: str) -> list[str]:
        """Mark all artifacts whose source hashes include this file as stale."""
        staled: list[str] = []
        for artifact_id, meta in self._data.items():
            if file_path in meta.get("source_hashes", {}):
                meta["is_stale"] = True
                meta["stale_reason"] = f"{file_path} changed"
                staled.append(artifact_id)
        return staled

    def clear_stale(self, artifact_id: str) -> None:
        if artifact_id in self._data:
            self._data[artifact_id]["is_stale"] = False
            self._data[artifact_id]["stale_reason"] = None

    def is_stale(self, artifact_id: str) -> bool:
        return self._data.get(artifact_id, {}).get("is_stale", True)

    def get_all_stale(self) -> list[str]:
        return [aid for aid, m in self._data.items() if m.get("is_stale")]
