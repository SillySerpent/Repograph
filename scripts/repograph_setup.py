#!/usr/bin/env python3
"""Bootstrap RepoGraph dev environment: venv, editable install, doctor, CLI help.

Run from the RepoGraph checkout (or anywhere if ``scripts/`` lives under the project)::

    python scripts/repograph_setup.py
    python scripts/repograph_setup.py --repo /path/to/project/to/index

Uses :func:`repograph.diagnostics.env_doctor.collect_doctor_results` / ``repograph doctor`` and
installs the local package with pip (``-e ".[dev]"`` by default).

The venv is created with a Python that satisfies ``requires-python`` in ``pyproject.toml``
(e.g. if you launch this script with ``python3`` → 3.10 but the project needs ≥3.11, a
``python3.11``/``python3.12`` on PATH is used instead, and an old ``.venv`` is recreated).

Path shortcuts (``--repo`` or interactive mode): ``..``, ``.``, absolute paths, and
``~`` are expanded; you can move up one directory at a time in interactive mode.

On **first-time** setup (no usable ``.venv`` yet), a TTY session offers install profiles
(explains optional extras). Use ``--extras '...[...]'`` or ``--no-interactive-setup`` to
skip that prompt.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def find_distribution_root() -> Path:
    """Directory containing ``pyproject.toml`` for the RepoGraph package."""
    here = Path(__file__).resolve().parent
    for p in [here, *here.parents]:
        if (p / "pyproject.toml").is_file():
            return p
    raise RuntimeError(
        "Could not find pyproject.toml — run this script from the RepoGraph checkout "
        "(next to pyproject.toml or under scripts/)."
    )


def resolve_repo_arg(spec: str, cwd: Path) -> Path:
    """Turn user path (relative, .., ~, absolute) into an absolute directory."""
    s = spec.strip()
    if s.startswith("~"):
        return Path(s).expanduser().resolve()
    p = Path(s)
    if p.is_absolute():
        return p.resolve()
    return (cwd / p).resolve()


def interactive_pick_repo(start: Path) -> Path:
    """Minimal navigator: current dir, [u]p, [c]ustom, [q]uit with current."""
    cur = start.resolve()
    print("\nChoose repository root to use for doctor / indexing (graph = .repograph/ here):")
    while True:
        print(f"\n  → {cur}")
        if not cur.is_dir():
            print("  [warning] path is not a directory")
        try:
            choice = input(
                "  [u]p one dir  [c]ustom path  [h]ome (~)  [q]uit & use this  : "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if choice in ("q", ""):
            return cur
        if choice == "u":
            parent = cur.parent
            if parent != cur:
                cur = parent
            continue
        if choice == "h":
            cur = Path.home().resolve()
            continue
        if choice == "c":
            raw = input("  Path (relative or absolute): ").strip()
            if raw:
                cur = resolve_repo_arg(raw, Path.cwd())
            continue
        print("  Unknown choice.")


def venv_python(venv: Path) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def read_requires_python_minimum(pyproject_path: Path) -> tuple[int, int]:
    """Parse ``[project] requires-python`` (e.g. ``>=3.11``) → ``(major, minor)`` minimum."""
    text = pyproject_path.read_text(encoding="utf-8")
    m = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        return (3, 11)
    spec = m.group(1).strip()
    ge = re.search(r">=\s*(\d+)\.(\d+)", spec)
    if ge:
        return (int(ge.group(1)), int(ge.group(2)))
    loose = re.search(r"(\d+)\.(\d+)", spec)
    if loose:
        return (int(loose.group(1)), int(loose.group(2)))
    return (3, 11)


def _python_version_tuple(py: Path) -> tuple[int, int] | None:
    try:
        out = subprocess.run(
            [str(py), "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        parts = out.stdout.strip().split()
        return (int(parts[0]), int(parts[1]))
    except (OSError, ValueError, IndexError, subprocess.CalledProcessError):
        return None


def _iter_python_candidates() -> list[Path]:
    """Interpreters to try when creating a venv (deduped)."""
    seen: set[Path] = set()
    out: list[Path] = []
    for p in (Path(sys.executable).resolve(),):
        if p not in seen:
            seen.add(p)
            out.append(p)
    for name in ("python3.13", "python3.12", "python3.11", "python3"):
        w = shutil.which(name)
        if not w:
            continue
        p = Path(w).resolve()
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def find_python_for_venv(min_major: int, min_minor: int) -> Path | None:
    """First interpreter on PATH (or the one running this script) that satisfies the minimum."""
    need = (min_major, min_minor)
    for p in _iter_python_candidates():
        ver = _python_version_tuple(p)
        if ver is not None and ver >= need:
            return p
    return None


def is_venv_ready(venv_dir: Path, min_python: tuple[int, int]) -> bool:
    """True if ``venv_dir`` already has a Python at least ``min_python``."""
    py = venv_python(venv_dir)
    if not py.is_file():
        return False
    ver = _python_version_tuple(py)
    if ver is None or ver < min_python:
        return False
    return True


def interactive_pick_setup_profile() -> str:
    """Prompt for pip extras (e.g. ``[dev,mcp]``). Caller ensures stdin is a TTY."""
    print(
        """
--------------------------------------------------------------------------------
  Install profile  (pip extras — what gets installed besides core repograph)
--------------------------------------------------------------------------------

  Core repograph (indexing, sync, CLI, parsers, Kuzu) is always included.

  Optional *extras* add features and dependencies. Pick one profile:

  1) Core dev  —  [dev]
     • pytest + pytest-cov — run the test suite
     • Smallest install; enough to develop and run tests
     • Best for: most contributors, bugfixes, day-to-day development

  2) Dev + MCP  —  [dev,mcp]
     • MCP server (stdio/HTTP) so editors / AI agents can call repograph as tools
     • Best for: Cursor, Claude Desktop, or custom agent integrations

  3) Dev + community  —  [dev,community]
     • Leiden clustering (leidenalg, igraph) for “communities” in the graph
     • Best for: exploring module boundaries / architecture (extra native libs)

  4) Dev + embeddings  —  [dev,embeddings]
     • sentence-transformers for vector / semantic workflows
     • Large download; GPU optional
     • Best for: semantic search pipelines and embedding-heavy experiments

  5) Dev + templates  —  [dev,templates]
     • Jinja2 for template / markdown experiments (lighter than embeddings)
     • Best for: doc or template-related work if you use this extra

  6) Full optional stack  —  [dev,community,mcp,embeddings,templates]
     • Installs every optional group at once — largest disk/time cost
     • Best for: maintainers, demos, or trying everything without reinstalling

  7) Custom  —  you type a comma-separated list (e.g. dev,mcp or dev,community,mcp)
     • Must include dev if you want pytest (e.g. dev,mcp)

--------------------------------------------------------------------------------"""
    )
    mapping = {
        "1": "[dev]",
        "": "[dev]",
        "2": "[dev,mcp]",
        "3": "[dev,community]",
        "4": "[dev,embeddings]",
        "5": "[dev,templates]",
        "6": "[dev,community,mcp,embeddings,templates]",
    }
    while True:
        try:
            raw = input("Enter 1–7 [default=1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if raw in mapping:
            chosen = mapping[raw]
            print(f"  → Using extras {chosen}\n")
            return chosen
        if raw == "7":
            custom = input(
                "  Comma-separated extras (no brackets), e.g. dev,mcp: "
            ).strip()
            if not custom:
                print("  [empty] defaulting to dev")
                return "[dev]"
            parts = [p.strip() for p in custom.split(",") if p.strip()]
            inner = ",".join(parts)
            chosen = f"[{inner}]"
            print(f"  → Using extras {chosen}\n")
            return chosen
        print("  Please enter a number 1–7.")


def ensure_venv(
    distribution_root: Path,
    venv_dir: Path,
    *,
    upgrade_pip: bool,
    min_python: tuple[int, int],
) -> Path:
    """Create ``venv_dir`` if missing; return path to venv python.

    Uses an interpreter that satisfies ``min_python`` (from ``pyproject.toml``). If an
    existing ``.venv`` was built with an older Python (e.g. you ran this script once
    with ``python3`` → 3.10), that environment is removed and recreated so ``pip install``
    does not fail on ``requires-python``.
    """
    min_major, min_minor = min_python
    py = venv_python(venv_dir)
    if py.is_file():
        ver = _python_version_tuple(py)
        if ver is not None and ver < (min_major, min_minor):
            print(
                f"Existing virtualenv uses Python {ver[0]}.{ver[1]}, but this project "
                f"requires Python >= {min_major}.{min_minor} (see pyproject.toml). "
                f"Removing {venv_dir} so it can be recreated."
            )
            shutil.rmtree(venv_dir)
            py = venv_python(venv_dir)

    if not py.is_file():
        creator = find_python_for_venv(min_major, min_minor)
        if creator is None:
            raise RuntimeError(
                f"No Python >= {min_major}.{min_minor} found on PATH. Install Python "
                f"{min_major}.{min_minor}+ (e.g. from python.org or Homebrew), then run "
                "this script again or use that interpreter explicitly, e.g. "
                f"python{min_major}.{min_minor} scripts/repograph_setup.py"
            )
        if creator.resolve() != Path(sys.executable).resolve():
            print(
                f"Note: using {creator} to create the venv (not {sys.executable}), "
                f"so the environment matches requires-python >= {min_major}.{min_minor}."
            )
        print(f"Creating virtualenv at {venv_dir} …")
        subprocess.run(
            [str(creator), "-m", "venv", str(venv_dir)],
            cwd=distribution_root,
            check=True,
        )
        py = venv_python(venv_dir)
    if not py.is_file():
        raise RuntimeError(f"venv python not found at {py}")

    if upgrade_pip:
        subprocess.run(
            [str(py), "-m", "pip", "install", "-U", "pip"],
            cwd=distribution_root,
            check=False,
        )
    return py


def pip_install_editable(py: Path, distribution_root: Path, extras: str) -> None:
    """``pip install -e .[extras]`` from distribution root."""
    editable = f".{extras}" if extras.startswith("[") else extras
    print(f"Installing editable package ({editable}) …")
    subprocess.run(
        [str(py), "-m", "pip", "install", "-e", editable],
        cwd=distribution_root,
        check=True,
    )


def run_doctor(py: Path, repo_root: Path, verbose: bool) -> int:
    cmd = [str(py), "-m", "repograph", "doctor", str(repo_root)]
    if verbose:
        cmd.append("--verbose")
    print("\n--- repograph doctor ---\n")
    return subprocess.run(cmd, cwd=repo_root).returncode


def run_help(py: Path, cwd: Path) -> None:
    print("\n--- repograph --help ---\n")
    subprocess.run([str(py), "-m", "repograph", "--help"], cwd=cwd)


def preflight_checks(distribution_root: Path, repo_root: Path) -> list[str]:
    """Return list of warning strings (empty if OK)."""
    warnings: list[str] = []
    if not distribution_root.is_dir():
        warnings.append(f"distribution root missing: {distribution_root}")
    if not (distribution_root / "pyproject.toml").is_file():
        warnings.append(f"no pyproject.toml at {distribution_root}")
    if not repo_root.is_dir():
        warnings.append(f"repo root is not a directory: {repo_root}")
    lock = repo_root / ".repograph" / "meta" / "sync.lock"
    if lock.is_file():
        warnings.append(
            f"sync.lock present ({lock}) — another sync may be running; doctor may still run."
        )
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create/ use .venv, pip install -e RepoGraph, run doctor and --help.",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Repository to index / run doctor against (default: cwd). Use .. or absolute paths.",
    )
    parser.add_argument(
        "--venv",
        type=str,
        default=".venv",
        help="Virtualenv directory (relative to distribution root, default: .venv).",
    )
    parser.add_argument(
        "--extras",
        type=str,
        default=None,
        metavar="SPEC",
        help=(
            "Pip extras for install -e, e.g. [dev] or [dev,mcp]. "
            "If omitted on first-time setup (no usable .venv yet) and stdin is a TTY, "
            "you’ll be prompted to choose a profile; otherwise defaults to [dev]."
        ),
    )
    parser.add_argument(
        "--skip-doctor",
        action="store_true",
        help="Skip repograph doctor.",
    )
    parser.add_argument(
        "--skip-help",
        action="store_true",
        help="Skip repograph --help.",
    )
    parser.add_argument(
        "--no-pip-upgrade",
        action="store_true",
        help="Do not run pip install -U pip before editable install.",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactive repo path navigator (ignored if --repo is set).",
    )
    parser.add_argument(
        "--verbose-doctor",
        "-v",
        action="store_true",
        help="Pass --verbose to repograph doctor.",
    )
    parser.add_argument(
        "--no-interactive-setup",
        action="store_true",
        help=(
            "Do not show the first-time install profile menu; use default [dev] when "
            "--extras is omitted (for scripts/CI)."
        ),
    )
    args = parser.parse_args()

    distribution_root = find_distribution_root()
    cwd = Path.cwd()

    if args.repo:
        repo_root = resolve_repo_arg(args.repo, cwd)
    elif args.interactive:
        repo_root = interactive_pick_repo(cwd)
    else:
        repo_root = cwd.resolve()

    venv_path = Path(args.venv)
    if not venv_path.is_absolute():
        venv_path = (distribution_root / venv_path).resolve()

    print(f"Distribution (editable install): {distribution_root}")
    print(f"Target repo (doctor / index):   {repo_root}")
    print(f"Virtualenv:                     {venv_path}")

    for w in preflight_checks(distribution_root, repo_root):
        print(f"[warn] {w}")

    min_py = read_requires_python_minimum(distribution_root / "pyproject.toml")
    venv_ready = is_venv_ready(venv_path, min_py)

    extras: str | None = args.extras
    if extras is not None:
        extras = extras.strip()
    if not extras:
        extras = None

    if extras is None:
        if (
            not venv_ready
            and sys.stdin.isatty()
            and not args.no_interactive_setup
        ):
            extras = interactive_pick_setup_profile()
        else:
            extras = "[dev]"
            if not venv_ready and not sys.stdin.isatty():
                print(
                    "Note: non-interactive session — using default extras [dev]. "
                    "Pass --extras '[dev,mcp]' etc. to customize."
                )

    if not extras.startswith("["):
        extras = f"[{extras}]"

    py = ensure_venv(
        distribution_root,
        venv_path,
        upgrade_pip=not args.no_pip_upgrade,
        min_python=min_py,
    )
    print(f"Using Python: {py}")

    pip_install_editable(py, distribution_root, extras)

    if not args.skip_doctor:
        rc = run_doctor(py, repo_root, args.verbose_doctor)
        if rc != 0:
            print("[warn] doctor reported failures — fix environment before syncing.")

    if not args.skip_help:
        run_help(py, repo_root)

    # Activation hint (non-fatal). `./setup.sh` can auto-enter a venv-backed
    # shell in interactive sessions, but direct Python invocation still needs a
    # manual activation path.
    if sys.platform == "win32":
        act = venv_path / "Scripts" / "activate.bat"
        print(f"\nManual activation:  {act}")
    else:
        act = venv_path / "bin" / "activate"
        print(f"\nManual activation:  source {act}")
    print(
        "Interactive `./setup.sh` runs now open a venv-backed shell automatically "
        "after setup succeeds."
    )
    print(
        "\nQuick run options:\n"
        "  ./run.sh sync                  # incremental (always prefers repo .venv)\n"
        "  ./run.sh sync --full           # full rebuild\n"
        "  ./run.sh sync --static-only    # full rebuild without automatic runtime analysis\n"
        "  repograph sync --full          # safe once the repo venv shell is active\n"
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"[error] subprocess failed with code {e.returncode}", file=sys.stderr)
        sys.exit(e.returncode)
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)
