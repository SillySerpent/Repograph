"""Import path setup and repo / RepoGraph session helpers."""
from __future__ import annotations

import glob
import os
import sys

from repograph.interactive.ui import _ask, _b, _header, _r


def _resolve_repo_path_input(raw: str, anchor_dir: str) -> str:
    """Turn user input into an absolute path.

    * Relative segments (``..``, ``../foo``) are resolved from ``anchor_dir``
      — the path shown in [brackets] — not from the shell's cwd.
    * Shell-style ``cd ..`` is accepted (common mistake).
    """
    raw = raw.strip()
    if not raw:
        return os.path.abspath(anchor_dir)
    lower = raw.lower()
    if lower.startswith("cd ") and len(raw) > 3:
        raw = raw[3:].strip()
    if raw in ("u", "up", "^"):
        raw = ".."
    expanded = os.path.expanduser(raw)
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)
    combined = os.path.join(anchor_dir, expanded)
    return os.path.abspath(os.path.normpath(combined))


def ensure_kuzu_available() -> None:
    """Graph features need kuzu; system Python often lacks it — fail with a clear hint."""
    try:
        import kuzu  # noqa: F401
    except ImportError:
        here = os.path.dirname(os.path.abspath(__file__))
        tool_root = os.path.abspath(os.path.join(here, "..", ".."))
        print(
            _r("\n  ✗  The 'kuzu' package is not available in this Python environment.")
        )
        _pip_editable = "pip install -e '.[community]'"
        print(
            f"\n  Interactive mode needs the same deps as a full install.  From:\n"
            f"    {_b(tool_root)}\n"
            f"  run:\n"
            f"    {_b('./rg menu')}   {_r('(recommended — uses .venv automatically)')}\n"
            f"  or:\n"
            f"    {_b(_pip_editable)}\n"
            f"  using the project's venv Python, not bare `python3` from PATH.\n"
        )
        sys.exit(1)


def ensure_repograph_importable() -> None:
    """If repograph isn't on sys.path, try the project root next to this package."""
    try:
        import repograph  # noqa: F401

        return
    except ImportError:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    # repograph/repograph/interactive -> project root (folder with pyproject.toml)
    root = os.path.abspath(os.path.join(here, "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        import repograph  # noqa: F401

        return
    except ImportError:
        pass

    venv_site = os.path.join(root, ".venv", "lib")
    if os.path.isdir(venv_site):
        site_pkgs = glob.glob(os.path.join(venv_site, "python3.*", "site-packages"))
        for sp in site_pkgs:
            if sp not in sys.path:
                sys.path.insert(0, sp)

    try:
        import repograph  # noqa: F401

        return
    except ImportError:
        print(_r("\n  ✗  RepoGraph is not installed."))
        print(f"  Run {_b('./rg init')} or {_b('pip install -e .')} first.\n")
        sys.exit(1)


def get_repo(argv_path: str | None) -> str:
    if argv_path and os.path.isdir(argv_path):
        return os.path.abspath(argv_path)

    _header("RepoGraph  ·  Interactive Menu")
    print("  Welcome! Let's start by locating your repository.\n")

    default = os.getcwd()
    path_help = [
        "How to answer:",
        "  • Press Enter  → use the path in [brackets].",
        "  • Type  ..  or  u  → go up one folder from [brackets] (not shell cwd).",
        "  • Type  ../my-app  → relative to [brackets].  Shell-style  cd ..  is treated as  ..",
        "  • Type an absolute path, or ~/… for your home directory.",
        "",
        "Tip: run the menu via ./rg menu so Python uses the tool's .venv (includes kuzu).",
        "",
        "This must be the root of the codebase you want to analyse (where source lives),",
        "not the RepoGraph tool folder — unless you mean to index RepoGraph itself.",
    ]
    while True:
        raw = _ask(
            "Where is the repository you want to analyse?",
            default=default,
            help_lines=path_help,
        )
        path = _resolve_repo_path_input(raw, default)
        if os.path.isdir(path):
            return path
        print(f"  {_r('That directory does not exist:')} {path}")
        # Next prompt's [brackets] = parent of what we resolved — helps  ..  chains & valid parents
        par = os.path.dirname(path.rstrip("/\\"))
        if par:
            default = par


def open_rg(repo: str):
    from repograph.api import RepoGraph

    return RepoGraph(repo)


def needs_index(rg) -> bool:
    return not rg._is_initialized()
