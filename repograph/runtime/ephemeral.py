"""Ephemeral runtime tracing helpers for one-shot dynamic syncs.

Unlike ``repograph trace install``, these helpers do not write tracked files
into the repository.

For pytest commands the tracer is injected as an ephemeral plugin module
passed via ``-p <module>``.  The plugin activates only in
``pytest_sessionstart`` (after collection) so interpreter startup and
collection noise are never traced, and subprocesses spawned by tests do not
inherit tracing because they do not pass ``-p``.

For non-pytest commands the legacy ``sitecustomize.py`` fallback is used, which
starts tracing at interpreter startup via ``PYTHONPATH`` injection.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from textwrap import dedent

from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="runtime")

# ---------------------------------------------------------------------------
# pytest plugin bootstrap (preferred path)
# ---------------------------------------------------------------------------

# Module name written to the temp dir and loaded via ``-p <name>``.
_PLUGIN_MODULE_NAME = "_repograph_ephemeral_trace"

_PYTEST_PLUGIN_TEMPLATE = """\
\"\"\"Ephemeral RepoGraph trace plugin — auto-generated, do not edit.\"\"\"
from __future__ import annotations


def pytest_configure(config):
    from repograph.runtime.tracer import SysTracer as _SysTracer

    class _RepoGraphEphemeralPlugin:
        def __init__(self):
            self._tracer = None

        def pytest_sessionstart(self, session):
            self._tracer = _SysTracer(
                repo_root={repo_root!r},
                repograph_dir={repograph_dir!r},
                session_name={session_name!r},
            )
            self._tracer.start()

        def pytest_sessionfinish(self, session, exitstatus):
            if self._tracer:
                self._tracer.stop()
                self._tracer = None

    if not config.pluginmanager.has_plugin("repograph_ephemeral"):
        config.pluginmanager.register(_RepoGraphEphemeralPlugin(), "repograph_ephemeral")
"""

# ---------------------------------------------------------------------------
# sitecustomize fallback (non-pytest commands)
# ---------------------------------------------------------------------------

_SITECUSTOMIZE_TEMPLATE = """\
import atexit as _atexit
from repograph.runtime.tracer import SysTracer as _SysTracer

_TRACER = _SysTracer(
    repo_root={repo_root!r},
    repograph_dir={repograph_dir!r},
    session_name={session_name!r},
)
_TRACER.start()
_atexit.register(_TRACER.stop)
"""


def _is_pytest_command(command: list[str]) -> bool:
    """Return True when *command* is recognisably a pytest invocation."""
    for i, part in enumerate(command):
        if part == "-m" and i + 1 < len(command) and command[i + 1] == "pytest":
            return True
        basename = os.path.basename(part)
        if basename in ("pytest", "py.test"):
            return True
    return False


def run_command_under_trace(
    command: list[str],
    *,
    repo_root: str,
    repograph_dir: str,
    session_name: str = "pytest",
) -> subprocess.CompletedProcess[bytes]:
    """Run *command* with ephemeral tracing enabled.

    For pytest commands an ephemeral plugin module is injected via
    ``-p <module>`` so that:

    * Tracing starts in ``pytest_sessionstart`` (after collection), avoiding
      interpreter-startup and bootstrap noise.
    * Subprocess Python processes spawned by tests do not inherit tracing
      because they are not invoked with ``-p``.

    For other commands the legacy ``sitecustomize.py`` approach is used.
    """
    root = Path(repo_root).resolve()
    rg_dir = Path(repograph_dir).resolve()
    with tempfile.TemporaryDirectory(prefix="repograph-trace-") as td:
        bootstrap_dir = Path(td)
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{bootstrap_dir}{os.pathsep}{existing}" if existing else str(bootstrap_dir)
        )

        if _is_pytest_command(command):
            (bootstrap_dir / f"{_PLUGIN_MODULE_NAME}.py").write_text(
                dedent(
                    _PYTEST_PLUGIN_TEMPLATE.format(
                        repo_root=str(root),
                        repograph_dir=str(rg_dir),
                        session_name=session_name,
                    )
                ),
                encoding="utf-8",
            )
            cmd = list(command) + ["-p", _PLUGIN_MODULE_NAME]
        else:
            (bootstrap_dir / "sitecustomize.py").write_text(
                dedent(
                    _SITECUSTOMIZE_TEMPLATE.format(
                        repo_root=str(root),
                        repograph_dir=str(rg_dir),
                        session_name=session_name,
                    )
                ),
                encoding="utf-8",
            )
            cmd = list(command)

        _logger.info(
            "ephemeral trace subprocess starting",
            command=" ".join(cmd),
            repo_root=str(root),
            repograph_dir=str(rg_dir),
        )
        result = subprocess.run(cmd, cwd=str(root), env=env)
        _logger.info(
            "ephemeral trace subprocess finished",
            command=" ".join(cmd),
            returncode=int(result.returncode),
        )
        return result
