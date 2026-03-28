"""Helpers for StrayRatz-backed runtime workflow tests.

These helpers keep the heavyweight StrayRatz fixture isolated in temporary
space, strip generated artifacts before each run, and own the ephemeral
runtime workspace contract used by managed/live workflow tests.

The heavy StrayRatz runtime tests should not depend on whatever happens to be
installed in the developer's main RepoGraph environment. Instead, they copy the
fixture into a temp workspace, provision a dedicated virtual environment from
the fixture's ``requirements.txt``, and remove that entire workspace on test
cleanup.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from typer.testing import CliRunner

from repograph.settings import ensure_settings_file, set_setting
from repograph.surfaces.cli import app

__all__ = [
    "build_live_sitecustomize_env",
    "create_strayratz_runtime_workspace",
    "configure_strayratz_managed_runtime",
    "copy_strayratz_repo",
    "install_live_attach_bootstrap",
    "StrayRatzRuntimeWorkspace",
    "write_strayratz_launcher",
]

_STRAYRATZ_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "StrayRatz"
_REPOGRAPH_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    ".repograph",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
)
_GENERATED_RELATIVE_PATHS = (
    ".repograph",
    "venv",
    ".venv",
    "env",
    "instance/site.db",
    "instance/live.db",
    "instance/managed.db",
)
_DEFAULT_TEST_ENV = {
    "SECRET_KEY": "repograph-strayratz-test-secret",
    "ADMIN_USERNAME": "admin",
    "ADMIN_EMAIL": "admin@example.com",
    "ADMIN_PASSWORD": "admin",
    "EMAIL_VERIFICATION_REQUIRED": "false",
    "MAIL_SUPPRESS_SEND": "true",
}
_BOOTSTRAP_ENV = {
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
}


@dataclass(frozen=True)
class StrayRatzRuntimeWorkspace:
    """Ephemeral StrayRatz runtime workspace used by heavy runtime tests."""

    repo_root: Path
    venv_dir: Path
    python_executable: Path
    pip_executable: Path

    def python_command(self, *args: str | os.PathLike[str]) -> list[str]:
        """Return a command list routed through the workspace interpreter."""
        return [str(self.python_executable), *(os.fspath(arg) for arg in args)]


def _venv_executable(venv_dir: Path, executable: str) -> Path:
    """Return the platform-correct executable path inside a virtualenv."""
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv_dir / scripts_dir / f"{executable}{suffix}"


def _venv_site_packages(venv_dir: Path, *, python_version: tuple[int, int]) -> Path:
    """Return the site-packages directory inside a virtualenv."""
    if os.name == "nt":
        return venv_dir / "Lib" / "site-packages"
    major, minor = python_version
    return venv_dir / "lib" / f"python{major}.{minor}" / "site-packages"


def _ensure_repograph_source_visible(
    venv_dir: Path,
    *,
    python_version: tuple[int, int],
) -> None:
    """Expose the checked-out RepoGraph source tree to the fixture venv.

    The heavy StrayRatz tests intentionally use an isolated interpreter so they
    do not inherit Flask and friends from the developer's main environment.
    That interpreter still needs to import RepoGraph tracing modules when
    ``sitecustomize`` or the ephemeral runtime bootstrap runs. A small ``.pth``
    file keeps that dependency explicit without turning the fixture venv into a
    second editable install of the whole repo.
    """
    site_packages = _venv_site_packages(venv_dir, python_version=python_version)
    site_packages.mkdir(parents=True, exist_ok=True)
    (site_packages / "repograph_source_root.pth").write_text(
        f"{_REPOGRAPH_SOURCE_ROOT}\n",
        encoding="utf-8",
    )


def _run_checked(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
) -> None:
    """Run a workspace bootstrap command and raise a rich error on failure."""
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            env={**os.environ, **_BOOTSTRAP_ENV},
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "StrayRatz runtime workspace bootstrap timed out: "
            f"command={list(command)!r} | cwd={str(cwd)!r} | timeout_seconds={timeout_seconds}"
        ) from exc
    if completed.returncode == 0:
        return

    details = [
        f"command={list(command)!r}",
        f"cwd={str(cwd)!r}",
        f"exit_code={completed.returncode}",
    ]
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if stdout:
        details.append(f"stdout={stdout}")
    if stderr:
        details.append(f"stderr={stderr}")
    raise RuntimeError("StrayRatz runtime workspace bootstrap failed: " + " | ".join(details))


def copy_strayratz_repo(destination: Path) -> Path:
    """Copy StrayRatz into a temp location with generated artifacts stripped."""
    repo = Path(destination)
    shutil.copytree(_STRAYRATZ_FIXTURE, repo, ignore=_COPY_IGNORE)
    for relative in _GENERATED_RELATIVE_PATHS:
        target = repo / relative
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=False)
        else:
            target.unlink()
    return repo


def create_strayratz_runtime_workspace(
    destination: Path,
    *,
    python_executable: str | Path | None = None,
    install_timeout_seconds: int = 300,
) -> StrayRatzRuntimeWorkspace:
    """Create an isolated StrayRatz workspace with its own dedicated venv.

    The workspace owns a copied fixture tree plus an in-workspace virtual
    environment populated from ``requirements.txt``. Deleting ``repo_root``
    removes the entire runtime workspace, including the fixture DBs, the copied
    ``.repograph`` directory, and the temporary virtual environment.
    """
    repo_root = copy_strayratz_repo(destination)
    venv_dir = repo_root / ".venv"
    base_python = Path(python_executable) if python_executable is not None else Path(sys.executable)

    _run_checked(
        [str(base_python), "-m", "venv", str(venv_dir)],
        cwd=repo_root,
        timeout_seconds=install_timeout_seconds,
    )
    _ensure_repograph_source_visible(
        venv_dir,
        python_version=(sys.version_info.major, sys.version_info.minor),
    )

    python_bin = _venv_executable(venv_dir, "python")
    pip_bin = _venv_executable(venv_dir, "pip")
    if not python_bin.exists() or not pip_bin.exists():
        raise RuntimeError(
            "StrayRatz runtime workspace bootstrap created an incomplete virtual environment: "
            f"venv_dir={str(venv_dir)!r}"
        )
    requirements_path = repo_root / "requirements.txt"
    _run_checked(
        [str(python_bin), "-m", "pip", "install", "-r", str(requirements_path)],
        cwd=repo_root,
        timeout_seconds=install_timeout_seconds,
    )

    return StrayRatzRuntimeWorkspace(
        repo_root=repo_root,
        venv_dir=venv_dir,
        python_executable=python_bin,
        pip_executable=pip_bin,
    )


def install_live_attach_bootstrap(repo_root: Path) -> None:
    """Install the public live-attach bootstrap used by traced live servers."""
    result = CliRunner().invoke(
        app,
        ["trace", "install", str(repo_root), "--mode", "sitecustomize"],
    )
    if result.exit_code != 0:
        raise AssertionError(result.stdout or str(result.exception))


def build_live_sitecustomize_env(
    repo_root: Path,
    *,
    port: int,
    database_name: str,
) -> dict[str, str]:
    """Return the env needed to run StrayRatz as a live traced server."""
    instance_dir = repo_root / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    repograph_path = str(repo_root / ".repograph")
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath_parts = [repograph_path, str(_REPOGRAPH_SOURCE_ROOT)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    pythonpath = (
        os.pathsep.join(part for part in pythonpath_parts if part)
    )
    return {
        **_DEFAULT_TEST_ENV,
        "PYTHONPATH": pythonpath,
        "FLASK_RUN_PORT": str(port),
        "DATABASE_URL": f"sqlite:///{instance_dir / database_name}",
    }


def write_strayratz_launcher(
    repo_root: Path,
    *,
    relative_path: str,
    port: int,
    database_name: str,
) -> Path:
    """Write a small launcher that pins StrayRatz runtime env for one test."""
    launcher_path = repo_root / relative_path
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    run_path = repo_root / "run.py"
    instance_dir = repo_root / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    launcher_path.write_text(
        "\n".join(
            [
                '"""Temp StrayRatz runtime launcher for RepoGraph tests."""',
                "from __future__ import annotations",
                "",
                "import os",
                "import runpy",
                "import sys",
                "",
                f"sys.path.insert(0, {str(repo_root)!r})",
                f"os.chdir({str(repo_root)!r})",
                f'os.environ.setdefault("FLASK_RUN_PORT", "{port}")',
                (
                    'os.environ.setdefault('
                    f'"DATABASE_URL", "sqlite:///{instance_dir / database_name}"'
                    ")"
                ),
                f'os.environ.setdefault("SECRET_KEY", "{_DEFAULT_TEST_ENV["SECRET_KEY"]}")',
                f'os.environ.setdefault("ADMIN_USERNAME", "{_DEFAULT_TEST_ENV["ADMIN_USERNAME"]}")',
                f'os.environ.setdefault("ADMIN_EMAIL", "{_DEFAULT_TEST_ENV["ADMIN_EMAIL"]}")',
                f'os.environ.setdefault("ADMIN_PASSWORD", "{_DEFAULT_TEST_ENV["ADMIN_PASSWORD"]}")',
                (
                    'os.environ.setdefault('
                    f'"EMAIL_VERIFICATION_REQUIRED", "{_DEFAULT_TEST_ENV["EMAIL_VERIFICATION_REQUIRED"]}"'
                    ")"
                ),
                f'os.environ.setdefault("MAIL_SUPPRESS_SEND", "{_DEFAULT_TEST_ENV["MAIL_SUPPRESS_SEND"]}")',
                f'runpy.run_path({str(run_path)!r}, run_name="__main__")',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return launcher_path


def configure_strayratz_managed_runtime(
    repo_root: Path,
    *,
    command: list[str],
    probe_url: str,
    scenario_urls: tuple[str, ...] = ("/",),
    ready_timeout: int = 20,
) -> None:
    """Persist managed-runtime settings for a temp StrayRatz repo copy."""
    repo_path = str(repo_root)
    ensure_settings_file(repo_path)
    set_setting(repo_path, "sync_runtime_server_command", command)
    set_setting(repo_path, "sync_runtime_probe_url", probe_url)
    set_setting(repo_path, "sync_runtime_scenario_urls", list(scenario_urls))
    set_setting(repo_path, "sync_runtime_ready_timeout", ready_timeout)
