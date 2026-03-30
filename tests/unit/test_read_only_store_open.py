from __future__ import annotations

from pathlib import Path

from repograph.cli import _get_root_and_store
from repograph.services.repo_graph_service import RepoGraphService


class _ProbeStore:
    def __init__(self, _db_path: str) -> None:
        self.prepared = False
        self.initialized = False

    def prepare_read_state(self) -> None:
        self.prepared = True

    def initialize_schema(self) -> None:
        self.initialized = True
        raise AssertionError("read-only helper must not run initialize_schema()")


def test_cli_read_helper_uses_prepare_read_state(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "graph.db").write_text("", encoding="utf-8")
    monkeypatch.setattr("repograph.graph_store.store.GraphStore", _ProbeStore)

    root, store = _get_root_and_store(str(repo))

    assert Path(root) == repo
    assert store.prepared is True  # type: ignore[attr-defined]


def test_service_get_store_uses_prepare_read_state(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    rg_dir = repo / ".repograph"
    rg_dir.mkdir()
    (rg_dir / "graph.db").write_text("", encoding="utf-8")
    monkeypatch.setattr("repograph.graph_store.store.GraphStore", _ProbeStore)

    service = RepoGraphService(str(repo), repograph_dir=str(rg_dir), include_git=False)
    store = service._get_store()

    assert store.prepared is True  # type: ignore[attr-defined]
