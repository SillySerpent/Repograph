"""Environment diagnostics for the ``repograph doctor`` CLI command."""
from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console

console = Console()

PARSER_IMPORTS = {
    "tree_sitter": "tree-sitter core",
    "tree_sitter_python": "tree-sitter python",
    "tree_sitter_javascript": "tree-sitter javascript",
    "tree_sitter_typescript": "tree-sitter typescript",
    "tree_sitter_bash": "tree-sitter bash",
    "tree_sitter_html": "tree-sitter html",
    "tree_sitter_css": "tree-sitter css",
}

OPTIONAL_IMPORTS = {
    "leidenalg": "community detection",
    "igraph": "community detection",
    "mcp": "MCP server",
    "sentence_transformers": "embeddings",
    "jinja2": "templates",
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _probe_import(module_name: str) -> CheckResult:
    label = PARSER_IMPORTS.get(module_name) or OPTIONAL_IMPORTS.get(module_name) or module_name
    required = module_name in PARSER_IMPORTS
    try:
        mod = importlib.import_module(module_name)
        version = getattr(mod, "__version__", "unknown")
        return CheckResult(module_name, True, f"{label} importable ({version})", required=required)
    except Exception as exc:  # pragma: no cover - defensive path
        return CheckResult(module_name, False, f"{label} import failed: {exc}", required=required)


def _isolated_import_probe() -> CheckResult:
    try:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(
                [sys.executable, "-c", "import repograph.cli as c; print('import_ok')"],
                cwd=td,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0:
                return CheckResult(
                    "isolated_import", True, "repograph.cli imports from isolated cwd"
                )
            detail = (r.stderr or r.stdout or "").strip()
            return CheckResult(
                "isolated_import",
                False,
                f"repograph.cli import from isolated cwd failed: {detail}",
            )
    except Exception as exc:  # pragma: no cover - defensive path
        return CheckResult("isolated_import", False, f"isolated import probe skipped: {exc}")


def _writable_index_dir(root: str) -> CheckResult:
    from repograph.config import repograph_dir

    rg_dir = Path(repograph_dir(root))
    try:
        rg_dir.mkdir(parents=True, exist_ok=True)
        probe = rg_dir / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return CheckResult("index_dir", True, f"index dir writable: {rg_dir}")
    except Exception as exc:
        return CheckResult("index_dir", False, f"index dir not writable ({rg_dir}): {exc}")


def collect_doctor_results(repo_path: str | None = None, verbose: bool = False) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(
        CheckResult(
            "python",
            sys.version_info >= (3, 11),
            f"Python {sys.version.split()[0]} executable={sys.executable}",
        )
    )

    spec = importlib.util.find_spec("repograph")
    if spec is None or not spec.origin:
        results.append(
            CheckResult(
                "repograph_import",
                False,
                "Package 'repograph' is not importable. Install editable from the RepoGraph checkout.",
            )
        )
        return results

    results.append(
        CheckResult("repograph_import", True, f"repograph importable from {spec.origin}")
    )

    try:
        import kuzu  # noqa: F401

        kv = getattr(importlib.import_module("kuzu"), "__version__", "unknown")
        results.append(CheckResult("kuzu", True, f"kuzu importable ({kv})"))
    except Exception as exc:
        results.append(CheckResult("kuzu", False, f"kuzu import failed: {exc}"))

    for module_name in PARSER_IMPORTS:
        results.append(_probe_import(module_name))

    for module_name in OPTIONAL_IMPORTS:
        probe = _probe_import(module_name)
        probe.required = False
        results.append(probe)

    root = os.path.abspath(repo_path or os.getcwd())
    results.append(CheckResult("repo_root", True, f"repo root: {root}"))
    results.append(_writable_index_dir(root))

    from repograph.config import db_path, is_initialized, repograph_dir

    rg = repograph_dir(root)
    if is_initialized(root):
        dbp = db_path(root)
        try:
            from repograph.graph_store.store import GraphStore

            st = GraphStore(dbp)
            st.prepare_read_state()
            rows = st.query("MATCH (f:File) RETURN count(f)")
            results.append(
                CheckResult(
                    "graph_open",
                    True,
                    f"database opens; File count = {rows[0][0] if rows else 0}",
                )
            )
            st.close()
        except Exception as exc:
            results.append(CheckResult("graph_open", False, f"could not open graph: {exc}"))
    else:
        results.append(
            CheckResult(
                "graph_open",
                True,
                "index not initialized yet — run `repograph sync` to bootstrap the index (`repograph init` is optional).",
                required=False,
            )
        )

    results.append(_isolated_import_probe())

    if is_initialized(root):
        from repograph.pipeline.sync_state import lock_status
        from repograph.pipeline.health import read_health_json

        ls, li = lock_status(rg)
        if ls == "active" and li:
            results.append(
                CheckResult(
                    "sync_lock",
                    True,
                    f"sync.lock active (pid={li.pid}, mode={li.mode}) — index may be building.",
                    required=False,
                )
            )
        elif ls == "stale":
            results.append(
                CheckResult(
                    "sync_lock",
                    False,
                    "stale sync.lock — remove if no process is indexing.",
                    required=False,
                )
            )

        h = read_health_json(rg)
        if h and h.get("status") == "failed":
            results.append(
                CheckResult(
                    "health",
                    False,
                    f"health.json status=failed ({h.get('error_phase')}): {(h.get('error_message') or '')[:200]}",
                    required=False,
                )
            )

    if verbose:
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "show", "repograph"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                results.append(CheckResult("pip_show", True, r.stdout.strip(), required=False))
        except Exception:
            pass

    return results


def run_doctor(repo_path: str | None = None, verbose: bool = False) -> None:
    """Verify Python, imports, parser packages, and optional graph open."""
    console.print("[bold]RepoGraph doctor[/]\n")
    results = collect_doctor_results(repo_path=repo_path, verbose=verbose)

    failures = 0
    for res in results:
        if res.ok:
            marker = "[green]✓[/]"
        elif res.required:
            marker = "[red]✗[/]"
            failures += 1
        else:
            marker = "[yellow]○[/]"
        console.print(f"{marker} {res.detail}")

    if failures:
        console.print("\n[red]Doctor found required failures.[/]")
        raise typer.Exit(1)

    console.print("\n[green]Doctor complete.[/]")
