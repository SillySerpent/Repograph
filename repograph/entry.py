"""Console entrypoint for the ``repograph`` setuptools script.

Resolves to:

* ``setup-verify`` — fix editable-install ``.pth`` on macOS (see :func:`fix_editable_pth`)
  and verify :mod:`repograph.surfaces.cli` imports from a clean working directory.
* ``menu`` — launch the interactive TUI (:mod:`repograph.interactive.main`).
* anything else — Typer CLI in :mod:`repograph.surfaces.cli` (``cli`` subcommand strips prefix).

Install: ``pip install -e .`` → console script ``repograph = repograph.entry:main``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _distribution_root() -> Path:
    """Directory containing ``pyproject.toml`` for this package."""
    return Path(__file__).resolve().parent.parent


def _site_packages_under_prefix(prefix: Path) -> list[Path]:
    lib = prefix / "lib"
    if not lib.is_dir():
        return []
    return [p for p in lib.glob("python*/site-packages") if p.is_dir()]


def fix_editable_pth() -> None:
    """Ensure the editable checkout is on sys.path (macOS may hide ``_*.pth``)."""
    root = str(_distribution_root())
    prefix = Path(sys.prefix)
    for sp in _site_packages_under_prefix(prefix):
        hidden = sp / "_repograph.pth"
        if hidden.is_file():
            try:
                subprocess.run(
                    ["xattr", "-c", str(hidden)],
                    check=False,
                    capture_output=True,
                )
            except OSError:
                pass
        marker = sp / "repograph_editable.pth"
        try:
            marker.write_text(root + "\n", encoding="utf-8")
        except OSError:
            pass


def verify_import_from_clean_cwd() -> None:
    """Fail loudly if ``repograph.surfaces.cli`` is not importable unless cwd helps."""
    env = os.environ.copy()
    cwd = os.getcwd()
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # Ensure the *tool* package is used, not a sibling folder named repograph.
            code = (
                "import importlib.util as u, sys; "
                "a=u.find_spec('repograph'); "
                "assert a and a.origin, 'repograph not found'; "
                "import repograph.surfaces.cli; "
                "print('import_ok', a.origin)"
            )
            r = subprocess.run(
                [sys.executable, "-c", code],
                cwd=td,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip()
                print(
                    "[repograph] FATAL: repograph.surfaces.cli is not importable from an isolated cwd.\n"
                    f"  This usually means the editable install path is skipped (e.g. macOS hidden .pth).\n"
                    f"  Run:  python -m repograph.entry setup-verify\n"
                    f"  Details: {err}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
    finally:
        os.chdir(cwd)


def setup_verify() -> None:
    fix_editable_pth()
    verify_import_from_clean_cwd()
    print("RepoGraph environment OK (editable path + import check).", file=sys.stderr)


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "setup-verify":
        setup_verify()
        return
    if args and args[0] == "menu":
        sys.argv = [sys.argv[0]] + args[1:]
        from repograph.interactive.main import main as menu_main

        menu_main()
        return
    if args and args[0] == "cli":
        args = args[1:]
    sys.argv = [sys.argv[0]] + args
    from repograph.surfaces.cli import app

    raise SystemExit(app())


if __name__ == "__main__":
    main()
