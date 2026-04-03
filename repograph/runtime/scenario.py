"""HTTP scenario helpers for managed runtime analysis."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

_OUTPUT_PREVIEW_LIMIT = 400


def wait_for_http_ready(
    url: str,
    *,
    timeout_seconds: float,
    interval_seconds: float = 0.2,
) -> None:
    """Wait until an HTTP endpoint responds or raise ``TimeoutError``."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=min(timeout_seconds, 1.0)):
                return
        except urllib.error.HTTPError:
            return
        except Exception as exc:
            last_error = exc
            time.sleep(interval_seconds)

    message = f"Timed out waiting for HTTP readiness at {url}"
    if last_error is not None:
        raise TimeoutError(f"{message}: {last_error}") from last_error
    raise TimeoutError(message)


def _resolve_scenario_url(probe_url: str, scenario_url: str) -> str:
    cleaned = (scenario_url or "").strip()
    if not cleaned:
        raise ValueError("scenario URL entries must not be empty")
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    return urljoin(probe_url, cleaned)


def _base_url_from_probe(probe_url: str) -> str:
    parsed = urlsplit(probe_url)
    if not parsed.scheme or not parsed.netloc:
        return probe_url
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


def drive_http_scenarios(
    *,
    probe_url: str,
    scenario_urls: list[str] | tuple[str, ...],
    request_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Drive simple HTTP GET scenarios against a ready server."""
    planned = list(scenario_urls)
    executed: list[dict[str, Any]] = []

    for scenario_url in planned:
        url = _resolve_scenario_url(probe_url, scenario_url)
        try:
            with urllib.request.urlopen(url, timeout=request_timeout_seconds) as response:
                executed.append(
                    {
                        "url": url,
                        "ok": True,
                        "status_code": int(response.getcode() or 200),
                    }
                )
        except urllib.error.HTTPError as exc:
            executed.append(
                {
                    "url": url,
                    "ok": False,
                    "status_code": int(exc.code),
                    "error": str(exc),
                }
            )
        except Exception as exc:
            executed.append(
                {
                    "url": url,
                    "ok": False,
                    "status_code": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    return {
        "planned_count": len(planned),
        "executed_count": len(executed),
        "successful_count": sum(1 for item in executed if item.get("ok")),
        "failed_count": sum(1 for item in executed if not item.get("ok")),
        "requests": executed,
    }


def _truncate_output(text: Any) -> str:
    if isinstance(text, bytes):
        normalized = text.decode("utf-8", errors="replace").strip()
    else:
        normalized = str(text or "").strip()
    if len(normalized) <= _OUTPUT_PREVIEW_LIMIT:
        return normalized
    return normalized[: _OUTPUT_PREVIEW_LIMIT - 1].rstrip() + "…"


def run_scenario_driver(
    command: list[str] | tuple[str, ...],
    *,
    repo_root: str,
    probe_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run a repo-provided scenario driver against a managed runtime server.

    The driver executes outside RepoGraph tracing and is expected to exercise
    the already-traced server through HTTP or browser automation. The base URL
    is exposed via ``REPOGRAPH_BASE_URL`` and ``REPOGRAPH_PROBE_URL``.
    """
    if not command:
        raise ValueError("scenario driver command must not be empty")

    env = os.environ.copy()
    env["REPOGRAPH_BASE_URL"] = _base_url_from_probe(probe_url)
    env["REPOGRAPH_PROBE_URL"] = probe_url
    env["REPOGRAPH_REPO_ROOT"] = repo_root

    try:
        result = subprocess.run(
            list(command),
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": list(command),
            "ok": False,
            "exit_code": None,
            "timeout_seconds": timeout_seconds,
            "stdout_preview": _truncate_output(exc.stdout or ""),
            "stderr_preview": _truncate_output(exc.stderr or ""),
            "error": f"TimeoutExpired: {exc}",
        }
    except OSError as exc:
        return {
            "command": list(command),
            "ok": False,
            "exit_code": None,
            "timeout_seconds": timeout_seconds,
            "stdout_preview": "",
            "stderr_preview": "",
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "command": list(command),
        "ok": result.returncode == 0,
        "exit_code": int(result.returncode),
        "timeout_seconds": timeout_seconds,
        "stdout_preview": _truncate_output(result.stdout),
        "stderr_preview": _truncate_output(result.stderr),
        "python_driver": Path(command[0]).name.lower().startswith("python")
        or command[0] == sys.executable,
    }
