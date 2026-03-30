"""CLI ``--help`` exits zero (Typer wiring regression)."""
from __future__ import annotations

import re

from typer.testing import CliRunner

from repograph.cli import app

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _invoke_help(*args: str):
    return CliRunner().invoke(app, list(args), color=False)


def _plain_stdout(*args: str) -> tuple[int, str]:
    result = _invoke_help(*args)
    return result.exit_code, _ANSI_RE.sub("", result.stdout)


def test_root_help() -> None:
    r = _invoke_help("--help")
    assert r.exit_code == 0


def test_sync_help_hides_deprecated_alias() -> None:
    exit_code, stdout = _plain_stdout("sync", "--help")
    assert exit_code == 0
    assert "--full-with-tests" not in stdout
    assert "--static-only" in stdout


def test_trace_subapp_help() -> None:
    exit_code, stdout = _plain_stdout("trace", "--help")
    assert exit_code == 0
    assert "repograph sync --full" in stdout
