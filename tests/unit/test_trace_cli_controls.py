from __future__ import annotations

import json

from typer.testing import CliRunner

from repograph.surfaces.cli import app


def test_trace_install_writes_policy_into_generated_conftest(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "trace",
            "install",
            str(repo),
            "--max-records",
            "123",
            "--max-mb",
            "2",
            "--rotate-files",
            "3",
            "--sample-rate",
            "0.25",
            "--include",
            "repograph/",
            "--exclude",
            "tests/",
        ],
    )
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    conftest = repo / ".repograph" / "conftest.py"
    assert conftest.exists()
    text = conftest.read_text(encoding="utf-8")
    assert "TracePolicy.from_kwargs(" in text
    assert "max_records=123" in text
    assert "max_file_bytes=2097152" in text
    assert "rotate_files=3" in text
    assert "sample_rate=0.25" in text


def test_trace_install_sitecustomize_enables_live_attach_bootstrap(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["trace", "install", str(repo), "--mode", "sitecustomize"],
    )
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    sitecustomize = repo / ".repograph" / "sitecustomize.py"
    assert sitecustomize.exists()
    text = sitecustomize.read_text(encoding="utf-8")
    assert 'trace_subdir="live"' in text
    assert "publish_live_session=True" in text


def test_trace_collect_json_reports_sizes_and_counts(tmp_path) -> None:
    repo = tmp_path / "repo"
    runtime = repo / ".repograph" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "a.jsonl").write_text('{"kind":"session"}\n{"kind":"call"}\n', encoding="utf-8")
    (runtime / "b.jsonl").write_text('{"kind":"session"}\n', encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["trace", "collect", "--json", str(repo)])
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    payload = json.loads(result.stdout)
    assert payload["trace_file_count"] == 2
    assert payload["total_records"] == 3
    assert payload["total_size_bytes"] >= 3
    names = {row["name"] for row in payload["trace_files"]}
    assert names == {"a.jsonl", "b.jsonl"}


def test_trace_collect_json_reports_live_session_traces_separately(tmp_path) -> None:
    repo = tmp_path / "repo"
    live_runtime = repo / ".repograph" / "runtime" / "live"
    live_runtime.mkdir(parents=True)
    (live_runtime / "live.jsonl").write_text(
        '{"kind":"session"}\n{"kind":"call"}\n',
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["trace", "collect", "--json", str(repo)])
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    payload = json.loads(result.stdout)
    assert payload["trace_file_count"] == 0
    assert payload["live_trace_file_count"] == 1
    assert payload["live_total_records"] == 2
