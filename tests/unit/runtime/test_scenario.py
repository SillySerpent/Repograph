from __future__ import annotations

import sys
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from repograph.runtime import scenario as scenario_module


def test_drive_http_scenarios_records_success_and_failure(monkeypatch) -> None:
    responses = {
        "http://127.0.0.1:8000/": 200,
        "http://127.0.0.1:8000/health": urllib.error.HTTPError(
            "http://127.0.0.1:8000/health",
            503,
            "down",
            hdrs=Message(),
            fp=None,
        ),
    }

    class _Response:
        def __init__(self, code: int) -> None:
            self._code = code

        def getcode(self) -> int:
            return self._code

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def _fake_urlopen(url, timeout=0):
        outcome = responses[url]
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)

    monkeypatch.setattr(scenario_module.urllib.request, "urlopen", _fake_urlopen)

    result = scenario_module.drive_http_scenarios(
        probe_url="http://127.0.0.1:8000/health",
        scenario_urls=("/", "/health"),
    )

    assert result["planned_count"] == 2
    assert result["executed_count"] == 2
    assert result["successful_count"] == 1
    assert result["failed_count"] == 1
    assert result["requests"][0]["url"] == "http://127.0.0.1:8000/"
    assert result["requests"][1]["status_code"] == 503


def test_wait_for_http_ready_times_out(monkeypatch) -> None:
    def _always_fail(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(scenario_module.urllib.request, "urlopen", _always_fail)

    with pytest.raises(TimeoutError, match="Timed out waiting for HTTP readiness"):
        scenario_module.wait_for_http_ready(
            "http://127.0.0.1:9999/health",
            timeout_seconds=0.05,
            interval_seconds=0.01,
        )


def test_run_scenario_driver_passes_base_url_and_captures_output(tmp_path: Path) -> None:
    script = tmp_path / "driver.py"
    script.write_text(
        (
            "import os\n"
            "print(os.environ['REPOGRAPH_BASE_URL'])\n"
            "print(os.environ['REPOGRAPH_PROBE_URL'])\n"
            "print(os.environ['REPOGRAPH_REPO_ROOT'])\n"
        ),
        encoding="utf-8",
    )

    result = scenario_module.run_scenario_driver(
        [sys.executable, str(script)],
        repo_root=str(tmp_path),
        probe_url="http://127.0.0.1:5001/health",
        timeout_seconds=1.0,
    )

    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "http://127.0.0.1:5001/" in result["stdout_preview"]
    assert "http://127.0.0.1:5001/health" in result["stdout_preview"]
    assert str(tmp_path) in result["stdout_preview"]


def test_run_scenario_driver_records_nonzero_exit(tmp_path: Path) -> None:
    script = tmp_path / "driver.py"
    script.write_text(
        "import sys\nprint('driver failed')\nsys.stderr.write('boom\\n')\nsys.exit(3)\n",
        encoding="utf-8",
    )

    result = scenario_module.run_scenario_driver(
        [sys.executable, str(script)],
        repo_root=str(tmp_path),
        probe_url="http://127.0.0.1:5001/health",
        timeout_seconds=1.0,
    )

    assert result["ok"] is False
    assert result["exit_code"] == 3
    assert "driver failed" in result["stdout_preview"]
    assert "boom" in result["stderr_preview"]
