from __future__ import annotations

from typer.testing import CliRunner

from repograph.services.repo_graph_service import RepoGraphService
from repograph.services.symbol_resolution import resolve_identifier
from repograph.surfaces.cli import app


class _FakeStore:
    def __init__(self) -> None:
        self._files = {
            "pkg/cli.py": {
                "id": "file:pkg/cli.py",
                "path": "pkg/cli.py",
                "abs_path": "/tmp/pkg/cli.py",
                "source_hash": "h1",
                "language": "python",
            }
        }
        self._functions = [
            {
                "id": "fn:pkg.cli.run",
                "name": "run",
                "qualified_name": "pkg.cli.run",
                "file_path": "pkg/cli.py",
                "signature": "def run()",
            },
            {
                "id": "fn:pkg.worker.run",
                "name": "run",
                "qualified_name": "pkg.worker.run",
                "file_path": "pkg/worker.py",
                "signature": "def run()",
            },
            {
                "id": "fn:pkg.build.execute",
                "name": "execute",
                "qualified_name": "pkg.build.execute",
                "file_path": "pkg/build.py",
                "signature": "def execute()",
            },
        ]

    def get_file(self, file_path: str):
        return self._files.get(file_path)

    def query(self, cypher: str, params=None):
        params = params or {}
        identifier = params.get("identifier", "")
        limit = int(params.get("limit", 10))
        if "f.qualified_name = $identifier" in cypher:
            matches = [fn for fn in self._functions if fn["qualified_name"] == identifier]
        elif "f.name = $identifier" in cypher:
            matches = [fn for fn in self._functions if fn["name"] == identifier]
        else:
            return []
        return [
            (fn["id"], fn["name"], fn["qualified_name"], fn["file_path"], fn["signature"])
            for fn in matches[:limit]
        ]

    def search_functions_by_name(self, name: str, limit: int = 10):
        lowered = name.lower()
        matches = [
            fn for fn in self._functions
            if lowered in fn["name"].lower() or lowered in fn["qualified_name"].lower()
        ]
        return matches[:limit]

    def get_function_by_id(self, function_id: str):
        for fn in self._functions:
            if fn["id"] == function_id:
                return {
                    **fn,
                    "line_start": 1,
                    "line_end": 5,
                    "is_entry_point": False,
                    "is_dead": False,
                    "decorators": [],
                    "param_names": [],
                    "docstring": None,
                    "return_type": None,
                    "entry_score": 0.0,
                    "community_id": None,
                    "is_test": False,
                }
        return None

    def get_functions_in_file(self, file_path: str):
        return [
            {
                **fn,
                "line_start": 1,
                "line_end": 5,
                "is_entry_point": False,
                "is_dead": False,
            }
            for fn in self._functions
            if fn["file_path"] == file_path
        ]

    def get_classes_in_file(self, _file_path: str):
        return []

    def get_callers(self, _function_id: str):
        return []

    def get_callees(self, _function_id: str):
        return []

    def get_interface_callers(self, _function_id: str):
        return []


def test_resolve_identifier_prefers_exact_qualified_name() -> None:
    store = _FakeStore()

    result = resolve_identifier(store, "pkg.cli.run")

    assert result["kind"] == "function"
    assert result["strategy"] == "exact_qualified_name"
    assert result["match"]["qualified_name"] == "pkg.cli.run"


def test_resolve_identifier_returns_ambiguous_for_duplicate_simple_name() -> None:
    store = _FakeStore()

    result = resolve_identifier(store, "run")

    assert result["kind"] == "ambiguous"
    assert result["strategy"] == "exact_simple_name"
    assert len(result["matches"]) == 2


def test_resolve_identifier_uses_normalized_candidate() -> None:
    store = _FakeStore()

    result = resolve_identifier(store, "pkg::cli.run")

    assert result["kind"] == "function"
    assert result["strategy"] == "normalized_qualified_name"
    assert result["match"]["qualified_name"] == "pkg.cli.run"


def test_service_impact_returns_structured_ambiguity(tmp_path) -> None:
    service = RepoGraphService(repo_path=str(tmp_path), repograph_dir=str(tmp_path / ".repograph"))
    service._store = _FakeStore()

    result = service.impact("run")

    assert result["ambiguous"] is True
    assert result["strategy"] == "exact_simple_name"
    assert len(result["matches"]) == 2
    assert result["matches"][0]["qualified_name"].startswith("pkg.")


def test_cli_impact_prints_ambiguity_and_exits_nonzero(monkeypatch) -> None:
    fake_store = _FakeStore()
    monkeypatch.setattr(
        "repograph.surfaces.cli.commands.query._get_root_and_store",
        lambda _path=None: ("repo", fake_store),
    )

    result = CliRunner().invoke(app, ["impact", "run"])

    assert result.exit_code == 2
    assert "Ambiguous match" in result.stdout
    assert "pkg.cli.run" in result.stdout
    assert "pkg.worker.run" in result.stdout
