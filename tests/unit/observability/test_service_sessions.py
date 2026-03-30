from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from repograph.cli import app
from repograph.core.models import FileRecord, ParsedFile
from repograph.graph_store.store import GraphStore
from repograph.observability import (
    ObservabilityConfig,
    get_logger,
    init_observability,
    new_run_id,
    set_obs_context,
    shutdown_observability,
)
from repograph.pipeline.phases import p03_parse
from repograph.services import RepoGraphService


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _make_file_record(path: str) -> FileRecord:
    abs_path = f"/tmp/{path}"
    return FileRecord(
        path=path,
        abs_path=abs_path,
        name=Path(path).name,
        extension=".py",
        language="python",
        size_bytes=1,
        line_count=1,
        source_hash=f"h:{path}",
        is_test=False,
        is_config=False,
        mtime=0.0,
    )


def test_service_read_methods_start_one_observability_session(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    rg_dir = repo / ".repograph"
    rg_dir.mkdir()

    store = GraphStore(str(rg_dir / "graph.db"))
    store.initialize_schema()
    store.close()

    svc = RepoGraphService(repo_path=str(repo), repograph_dir=str(rg_dir), include_git=False)
    try:
        status = svc.status()
        entry_points = svc.entry_points(limit=5)
        assert status["initialized"] is True
        assert entry_points == []
    finally:
        svc.close()

    latest = rg_dir / "logs" / "latest"
    assert latest.exists()
    records = _read_jsonl(latest.resolve() / "all.jsonl")
    assert any(r.get("msg") == "service observability session started" for r in records)
    ops = [r.get("operation") for r in records if r.get("operation")]
    assert "service_status" in ops
    assert "service_entry_points" in ops
    run_ids = {r.get("run_id") for r in records if r.get("operation") in {"service_status", "service_entry_points"}}
    assert len(run_ids) == 1


def test_parallel_parse_workers_inherit_observability_context(tmp_path: Path, monkeypatch) -> None:
    config = ObservabilityConfig(log_dir=tmp_path / "logs", run_id=new_run_id())
    init_observability(config)
    try:
        set_obs_context(command_id="cmd-parse", phase="p03_parse")
        worker_logger = get_logger("repograph.test.worker", subsystem="pipeline")

        def _fake_parse_one_file(fr: FileRecord) -> ParsedFile:
            worker_logger.info("worker parse invoked", path=fr.path)
            return ParsedFile(file_record=fr)

        monkeypatch.setattr(p03_parse, "_parse_one_file", _fake_parse_one_file)
        files = [_make_file_record(f"f{i}.py") for i in range(6)]
        parsed = p03_parse._parse_files_parallel(files)
        assert len(parsed) == 6
    finally:
        shutdown_observability()

    records = _read_jsonl(config.run_dir / "all.jsonl")
    worker_records = [r for r in records if r.get("msg") == "worker parse invoked"]
    assert len(worker_records) == 6
    assert all(r.get("run_id") == config.run_id for r in worker_records)
    assert all(r.get("command_id") == "cmd-parse" for r in worker_records)
    assert all(r.get("phase") == "p03_parse" for r in worker_records)


def test_cli_status_creates_a_command_observability_session(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    rg_dir = repo / ".repograph"
    rg_dir.mkdir()

    store = GraphStore(str(rg_dir / "graph.db"))
    store.initialize_schema()
    store.close()

    result = CliRunner().invoke(app, ["status", str(repo)])
    assert result.exit_code == 0, result.stdout

    latest = rg_dir / "logs" / "latest"
    assert latest.exists()
    records = _read_jsonl(latest.resolve() / "all.jsonl")
    assert any(r.get("msg") == "cli command started" and r.get("command") == "status" for r in records)
    assert any(r.get("msg") == "cli command finished" and r.get("command") == "status" for r in records)
