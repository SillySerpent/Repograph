"""CLI ``--help`` exits zero (Typer wiring regression)."""
from __future__ import annotations

from typer.testing import CliRunner

from repograph.cli import app


def _invoke_help(*args: str):
    return CliRunner().invoke(app, list(args), color=False)


def test_root_help() -> None:
    r = _invoke_help("--help")
    assert r.exit_code == 0


def test_sync_help_hides_deprecated_alias() -> None:
    r = _invoke_help("sync", "--help")
    assert r.exit_code == 0
    assert "--full-with-tests" not in r.stdout
    assert "--static-only" in r.stdout


def test_trace_subapp_help() -> None:
    r = _invoke_help("trace", "--help")
    assert r.exit_code == 0
    assert "repograph sync --full" in r.stdout
