"""RepoGraph CLI — Typer-based command interface.

Entry point for the ``repograph`` console script. Commands call into
:class:`~repograph.services.repo_graph_service.RepoGraphService` (often via
``RepoGraph`` context managers). Command reference: ``docs/CLI_REFERENCE.md``;
how CLI relates to API/MCP: ``docs/SURFACES.md``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import print as rprint
from repograph.observability import get_logger, new_run_id, set_obs_context

_logger = get_logger(__name__, subsystem="cli")

app = typer.Typer(
    name="repograph",
    help="AI-oriented repository intelligence layer.",
    no_args_is_help=True,
)
pathway_app = typer.Typer(help="Pathway commands.")
app.add_typer(pathway_app, name="pathway")

trace_app = typer.Typer(
    name="trace",
    help=(
        "Dynamic analysis: instrument, collect call traces, overlay onto static graph.\n\n"
        "  1. repograph trace install   — write conftest.py instrumentation\n"
        "  2. pytest                    — run tests; traces → .repograph/runtime/\n"
        "  3. repograph sync            — overlay fires automatically\n"
        "  4. repograph trace report    — view dynamic findings"
    ),
)
app.add_typer(trace_app, name="trace")

from repograph.interactive.logs_handler import logs_app  # noqa: E402
app.add_typer(logs_app, name="logs")

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        import importlib.metadata
        try:
            version = importlib.metadata.version("repograph")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        typer.echo(f"repograph {version}")
        raise typer.Exit()


@app.callback()
def _cli_startup(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Set a stable command_id on the observability context for every CLI invocation."""
    command_id = new_run_id()
    set_obs_context(command_id=command_id)
    _logger.debug("CLI invoked", command=ctx.invoked_subcommand, command_id=command_id)


def _get_root_and_store(repo_path: str | None = None):
    """Return (repo_root, store) for the current repo."""
    from repograph.config import get_repo_root, db_path, is_initialized
    from repograph.exceptions import RepographNotFoundError
    from repograph.graph_store.store import GraphStore

    try:
        root = get_repo_root(repo_path)
    except RepographNotFoundError:
        console.print("[red]Error:[/] Not initialized. Run [bold]repograph init[/] first.")
        raise typer.Exit(1)
    if not is_initialized(root):
        console.print("[red]Error:[/] Not initialized. Run [bold]repograph init[/] first.")
        raise typer.Exit(1)

    store = GraphStore(db_path(root))
    store.initialize_schema()
    return root, store


def _get_service(path: str | None = None):
    """Return (repo_root, RepoGraph API wrapper) for initialized repos."""
    from repograph.api import RepoGraph
    from repograph.config import get_repo_root, repograph_dir, is_initialized
    from repograph.exceptions import RepographNotFoundError

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        console.print("[red]Error:[/] Not initialized. Run [bold]repograph init[/] first.")
        raise typer.Exit(1)
    if not is_initialized(root):
        console.print("[red]Error:[/] Not initialized. Run [bold]repograph init[/] first.")
        raise typer.Exit(1)
    return root, RepoGraph(root, repograph_dir=repograph_dir(root))


# ---------------------------------------------------------------------------
# repograph init
# ---------------------------------------------------------------------------

@app.command()
def init(
    path: Optional[str] = typer.Argument(None, help="Repo root (default: current dir)"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-initialize even if already done"),
):
    """Initialize RepoGraph in a repository."""
    from repograph.config import repograph_dir, is_initialized
    root = os.path.abspath(path or os.getcwd())
    rg_dir = repograph_dir(root)

    if is_initialized(root) and not force:
        console.print(f"[yellow]Already initialized at {rg_dir}[/]")
        console.print("Use [bold]--force[/] to reinitialize, or run [bold]repograph sync[/].")
        raise typer.Exit(0)

    os.makedirs(rg_dir, exist_ok=True)
    os.makedirs(os.path.join(rg_dir, "meta"), exist_ok=True)
    os.makedirs(os.path.join(rg_dir, "mirror"), exist_ok=True)
    os.makedirs(os.path.join(rg_dir, "pathways"), exist_ok=True)

    # Write .repograph/.gitignore
    gi = os.path.join(rg_dir, ".gitignore")
    with open(gi, "w") as f:
        f.write("graph.db\nmeta/\n")

    console.print(Panel(
        f"[green]✓ Initialized RepoGraph[/] at [bold]{rg_dir}[/]\n\n"
        "Run [bold]repograph sync[/] to index the repository.",
        title="repograph init",
    ))


# ---------------------------------------------------------------------------
# repograph sync
# ---------------------------------------------------------------------------

@app.command()
def sync(
    path: Optional[str] = typer.Argument(
        None,
        help="Repository root (default: current directory). Do not pass “full” here — use --full.",
    ),
    full_with_tests: bool = typer.Option(
        False,
        "--full-with-tests",
        help=(
            "Full sync, then ``repograph trace install``, ``pytest tests``, "
            "``repograph trace collect``, and incremental sync to merge JSONL traces "
            "into the graph (runtime overlay). Implies a full index first."
        ),
    ),
    full: bool = typer.Option(False, "--full", help="Force full re-index"),
    embeddings: bool = typer.Option(False, "--embeddings", help="Include vector embeddings"),
    no_git: bool = typer.Option(False, "--no-git", help="Skip git coupling phase"),
    strict: bool = typer.Option(
        False, "--strict",
        help="Fail the sync if optional phases (embeddings deps, plugin hooks, etc.) error.",
    ),
    continue_on_error: bool = typer.Option(
        True,
        "--continue-on-error/--no-continue-on-error",
        help="When off, first optional-phase failure aborts sync (core phases always abort on error).",
    ),
    include_tests_config_registry: bool = typer.Option(
        False,
        "--include-tests-config-registry",
        help="Phase 17: include test files when building the config key registry.",
    ),
):
    """Sync the repository index (incremental by default).

    Use ``repograph sync --full`` for a full rebuild. Use ``--full-with-tests`` for
    full index + pytest + runtime trace merge (see option help).

    A bare word ``full`` is not a flag — if you run ``repograph sync full``, Typer
    treats ``full`` as the repo *path* (usually wrong). We map that common mistake
    to ``--full`` on cwd.
    """
    from repograph.config import get_repo_root, repograph_dir, is_initialized, db_path
    from repograph.pipeline.runner import (
        RunConfig,
        run_full_pipeline,
        run_full_sync_with_tests,
        run_incremental_pipeline,
    )
    from repograph.pipeline.incremental import IncrementalDiff

    # ``repograph sync full`` mistakenly sets path="full" instead of --full
    if path is not None and path.strip().lower() == "full":
        path = None
        full = True
    if path is not None and path.strip().lower() == "incremental":
        path = None
        full = False

    root = os.path.abspath(path or os.getcwd())
    rg_dir = repograph_dir(root)

    if full_with_tests:
        full = True

    if not is_initialized(root) and not full:
        console.print("[yellow]Not yet indexed. Running full sync...[/]")
        full = True

    os.makedirs(rg_dir, exist_ok=True)
    os.makedirs(os.path.join(rg_dir, "meta"), exist_ok=True)

    config = RunConfig(
        repo_root=root,
        repograph_dir=rg_dir,
        include_git=not no_git,
        include_embeddings=embeddings,
        full=full,
        strict=strict,
        continue_on_error=continue_on_error,
        include_tests_config_registry=include_tests_config_registry,
    )

    from repograph.pipeline.sync_state import lock_status

    st_lock, lock_info = lock_status(rg_dir)
    if st_lock == "active" and lock_info:
        console.print(
            f"[yellow]⚠ Sync already in progress[/] (pid={lock_info.pid}, "
            f"mode={lock_info.mode}, since={lock_info.started_at}). "
            "Wait or stop that process before starting another sync."
        )
        raise typer.Exit(1)

    if full_with_tests:
        console.print("[cyan]Running full sync with tests + trace merge...[/]")
        stats = run_full_sync_with_tests(config)
        _print_stats(stats)
        return

    if full:
        console.print("[cyan]Running full pipeline...[/]")
        stats = run_full_pipeline(config)
    else:
        differ = IncrementalDiff(rg_dir)
        if differ.is_first_run():
            console.print("[cyan]First run — performing full sync...[/]")
            stats = run_full_pipeline(config)
        else:
            console.print("[cyan]Running incremental sync...[/]")
            stats = run_incremental_pipeline(config)

    _print_stats(stats)


def _print_stats(stats: dict) -> None:
    table = Table(title="Index Stats", show_header=True)
    table.add_column("Entity", style="cyan")
    table.add_column("Count", justify="right", style="green")
    for key, val in stats.items():
        table.add_row(key.replace("_", " ").title(), str(val))
    console.print(table)


# ---------------------------------------------------------------------------
# repograph test
# ---------------------------------------------------------------------------

def _test_profile_args(profile: str) -> list[str]:
    p = (profile or "unit-fast").strip().lower()
    if p == "unit-fast":
        return ["tests/unit/", "-q", "-m", "not dynamic and not integration and not requires_mcp"]
    if p == "plugin-dynamic":
        return ["tests/", "-q", "-m", "plugin or dynamic"]
    if p == "integration":
        return ["tests/integration/", "-q"]
    if p == "full":
        return ["tests/", "-q"]
    raise ValueError(
        f"Unknown profile '{profile}'. Expected one of: unit-fast, plugin-dynamic, integration, full."
    )


def _test_profiles_catalog() -> dict[str, dict[str, str]]:
    return {
        "unit-fast": {
            "selector": 'tests/unit/ -m "not dynamic and not integration and not requires_mcp"',
            "description": "Fast unit-focused guardrail.",
        },
        "plugin-dynamic": {
            "selector": 'tests/ -m "plugin or dynamic"',
            "description": "Plugin dispatch and runtime-overlay focused tests.",
        },
        "integration": {
            "selector": "tests/integration/",
            "description": "Integration suite for end-to-end behavior.",
        },
        "full": {
            "selector": "tests/",
            "description": "Complete test suite.",
        },
    }


@app.command("test")
def test_command(
    profile: str = typer.Option(
        "unit-fast",
        "--profile",
        "-p",
        help="Test matrix profile: unit-fast | plugin-dynamic | integration | full.",
    ),
    list_profiles: bool = typer.Option(
        False,
        "--list-profiles",
        help="Print available test profiles and exit.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit profile/run metadata as JSON.",
    ),
    path: Optional[str] = typer.Argument(None, help="Repository root (default: current directory)."),
    extra_args: Optional[list[str]] = typer.Argument(None, help="Extra pytest args passed through as-is."),
) -> None:
    """Run predefined test-suite matrix profiles.

    Profiles use pytest markers and test paths, so they automatically include
    new tests that match those selectors.
    """
    from repograph.config import get_repo_root
    from repograph.exceptions import RepographNotFoundError

    catalog = _test_profiles_catalog()
    if list_profiles:
        if as_json:
            typer.echo(json.dumps({"profiles": catalog}, indent=2))
            return
        t = Table(title="repograph test profiles", show_header=True)
        t.add_column("Profile", style="cyan")
        t.add_column("Selector", style="dim")
        t.add_column("Description")
        for name, meta in catalog.items():
            t.add_row(name, meta["selector"], meta["description"])
        console.print(t)
        return

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        root = os.path.abspath(path or os.getcwd())
    try:
        profile_args = _test_profile_args(profile)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)

    cmd = [sys.executable, "-m", "pytest", *profile_args, *(extra_args or [])]
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "profile": profile,
                    "selector": catalog.get(profile, {}).get("selector", ""),
                    "repo_root": root,
                    "pytest_cmd": cmd,
                },
                indent=2,
            )
        )
    else:
        console.print(f"[cyan]Running test profile:[/] {profile}")
        console.print(f"[dim]{' '.join(cmd)}[/]")
    r = subprocess.run(cmd, cwd=root)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


# ---------------------------------------------------------------------------
# repograph status
# ---------------------------------------------------------------------------

@app.command()
def status(path: Optional[str] = typer.Argument(None)):
    """Show index health: node counts, stale artifacts, last sync time."""
    root, store = _get_root_and_store(path)
    from repograph.config import repograph_dir
    from repograph.docs.staleness import StalenessTracker

    stats = store.get_stats()
    staleness = StalenessTracker(repograph_dir(root))
    stale = staleness.get_all_stale()

    table = Table(title=f"RepoGraph Status — {root}", show_header=True)
    table.add_column("Entity", style="cyan")
    table.add_column("Count", justify="right")
    for k, v in stats.items():
        table.add_row(k.replace("_", " ").title(), str(v))

    console.print(table)

    from repograph.pipeline.health import read_health_json

    health = read_health_json(repograph_dir(root))
    if health:
        ce = health.get("call_edges_total")
        ver = health.get("contract_version", "?")
        mode = health.get("sync_mode", "?")
        at = health.get("generated_at", "")
        st = health.get("strict")
        st_s = f" strict={st}" if st is not None else ""
        hstat = health.get("status", "ok")
        console.print(
            f"\n[dim]Health[/] contract={ver}  sync={mode}{st_s}  "
            f"status={hstat}  call_edges={ce}  at={at}"
        )
        if hstat == "failed":
            console.print(
                f"[red bold]Last sync failed:[/] {health.get('error_phase', '?')}: "
                f"{health.get('error_message', '')[:500]}"
            )

    from repograph.pipeline.sync_state import lock_status

    ls, li = lock_status(repograph_dir(root))
    if ls == "active" and li:
        console.print(
            f"\n[yellow bold]Indexing in progress[/] pid={li.pid} mode={li.mode} "
            f"since={li.started_at}"
        )
    elif ls == "stale":
        console.print(
            "\n[yellow]⚠ Stale sync.lock (crashed runner?); remove meta/sync.lock if no sync is running.[/]"
        )

    if stale:
        console.print(f"\n[yellow]⚠ {len(stale)} stale artifact(s). Run [bold]repograph sync[/] to refresh.[/]")
    else:
        console.print("\n[green]✓ All artifacts are current.[/]")


# ---------------------------------------------------------------------------
# repograph doctor
# ---------------------------------------------------------------------------

@app.command()
def summary(
    path: Optional[str] = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json", help="Output as machine-readable JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show entry-point score breakdowns."),
):
    """One-screen repo intelligence summary: purpose, entry points, top flows,
    dead code, duplicates, and health.

    Ideal as a first prompt injection when entering an unfamiliar codebase.
    """
    import json as _json
    from repograph.plugins.exporters.agent_guide.generator import _extract_repo_summary

    root, rg = _get_service(path)
    with rg:
        stats = rg.status()
        eps = rg.entry_points(limit=5)
        top_ps = rg.pathways(include_tests=False)[:5]
        dead = rg.dead_code()
        dups = rg.duplicates(min_severity="high")

    repo_purpose = _extract_repo_summary(root)

    if as_json:
        data = {
            "repo": stats.get("repo", os.path.basename(root)),
            "purpose": repo_purpose,
            "stats": {k: v for k, v in stats.items() if k not in ("health",)},
            "health": stats.get("health", {}),
            "top_entry_points": [
                {"name": ep["qualified_name"], "file": ep["file_path"],
                 "score": ep["entry_score"]}
                for ep in eps
            ],
            "top_pathways": [
                {"name": p["name"], "steps": p["step_count"],
                 "importance": p.get("importance_score", 0.0),
                 "confidence": p.get("confidence", 0.0)}
                for p in top_ps
            ],
            "dead_code_count": len(dead),
            "dead_code_sample": [d["qualified_name"] for d in dead[:5]],
            "high_severity_duplicates": len(dups),
            "duplicate_sample": [d["name"] for d in dups[:5]],
        }
        console.print(_json.dumps(data, indent=2))
        return

    repo_name = stats.get("repo", os.path.basename(root))
    health = stats.get("health", {})
    health_status = health.get("status", "ok")
    health_color = "green" if health_status == "ok" else "red"
    sync_mode = health.get("sync_mode", "?")
    call_edges = health.get("call_edges_total", "?")

    console.print()
    console.print(f"[bold cyan]── RepoGraph Summary: {repo_name} ──[/]")
    console.print()

    # Purpose (from README)
    if repo_purpose:
        console.print("[bold]Purpose[/]")
        console.print(f"  {repo_purpose[:300]}")
        console.print()

    # Stats row
    fn_count = stats.get("functions", 0)
    cls_count = stats.get("classes", 0)
    file_count = stats.get("files", 0)
    console.print(
        f"[bold]Index[/]  {file_count} files · {fn_count} functions · "
        f"{cls_count} classes · {call_edges} call edges  "
        f"[{health_color}]{health_status}[/] ({sync_mode})"
    )
    console.print()

    # Top entry points
    if eps:
        console.print("[bold]Top Entry Points[/]")
        ep_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        ep_table.add_column("Score", style="dim", justify="right")
        ep_table.add_column("Function", style="cyan")
        ep_table.add_column("File", style="dim")
        if verbose:
            ep_table.add_column("Score Breakdown", style="dim")
        for ep in eps:
            if verbose:
                from repograph.plugins.static_analyzers.pathways.scorer import ScoreBreakdown, score_function_verbose
                if ep.get("entry_callee_count") is not None and ep.get("entry_score_base") is not None:
                    import json as _json
                    raw_m = ep.get("entry_score_multipliers") or "[]"
                    try:
                        mults = _json.loads(raw_m)
                    except Exception:
                        mults = []
                    pairs: list[tuple[str, float]] = []
                    if isinstance(mults, list):
                        for item in mults:
                            if isinstance(item, (list, tuple)) and len(item) >= 2:
                                pairs.append((str(item[0]), float(item[1])))
                    bd = ScoreBreakdown(
                        final_score=float(ep["entry_score"]),
                        base_score=float(ep["entry_score_base"]),
                        callees_count=int(ep.get("entry_callee_count") or 0),
                        callers_count=int(ep.get("entry_caller_count") or 0),
                        multipliers=pairs,
                    )
                    explain = bd.explain()
                else:
                    bd = score_function_verbose(
                        ep,
                        callees_count=int(ep.get("entry_score", 0)),
                        callers_count=0,
                    )
                    explain = bd.explain()
                ep_table.add_row(
                    f"{ep['entry_score']:.1f}",
                    ep["qualified_name"],
                    ep["file_path"],
                    explain,
                )
            else:
                ep_table.add_row(
                    f"{ep['entry_score']:.1f}",
                    ep["qualified_name"],
                    ep["file_path"],
                )
        console.print(ep_table)
        console.print()

    # Top pathways
    if top_ps:
        console.print("[bold]Top Pathways[/]  (by importance)")
        p_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        p_table.add_column("Imp", style="dim", justify="right")
        p_table.add_column("Name", style="cyan")
        p_table.add_column("Steps", justify="right", style="dim")
        p_table.add_column("Conf", justify="right", style="dim")
        for p in top_ps:
            p_table.add_row(
                f"{p.get('importance_score', 0.0):.1f}",
                p["name"],
                str(p.get("step_count", 0)),
                f"{p.get('confidence', 0.0):.2f}",
            )
        console.print(p_table)
        console.print()

    # Dead code + duplicates
    dead_color = "red" if dead else "green"
    dup_color = "red" if dups else "green"
    console.print(
        f"[bold]Issues[/]  "
        f"[{dead_color}]{len(dead)} dead code symbols[/]  ·  "
        f"[{dup_color}]{len(dups)} high-severity duplicates[/]"
    )
    if dead:
        sample = ", ".join(d["qualified_name"] for d in dead[:3])
        console.print(f"  [dim]Dead sample: {sample}{'…' if len(dead) > 3 else ''}[/]")
    if dups:
        dup_sample = ", ".join(d["name"] for d in dups[:3])
        console.print(f"  [dim]Dup sample:  {dup_sample}{'…' if len(dups) > 3 else ''}[/]")
    console.print()


@app.command()
def doctor(
    path: Optional[str] = typer.Argument(None, help="Repo root (tests DB open if initialized)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show pip show repograph"),
):
    """Verify Python environment, imports, and optional graph database."""
    from repograph.diagnostics.env_doctor import run_doctor

    run_doctor(repo_path=path, verbose=verbose)


@app.command(name="config")
def config_cmd(
    path: Optional[str] = typer.Argument(None),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Show consumers of a single config key."),
    top: int = typer.Option(20, "--top", "-n", help="Number of keys to show (default 20)."),
    as_json: bool = typer.Option(False, "--json", help="Output as machine-readable JSON."),
    include_tests: bool = typer.Option(
        False,
        "--include-tests",
        help="Rebuild registry from the graph including test files (live scan; ignores cached JSON).",
    ),
) -> None:
    """Config key map: which pathways and files read each config value.

    Use --key <name> to see the full blast radius of a single key rename.
    """
    import json as _json
    from repograph.api import RepoGraph
    from repograph.config import repograph_dir

    root, store = _get_root_and_store(path)

    if include_tests:
        from repograph.plugins.exporters.config_registry.plugin import build_registry

        registry = build_registry(store, include_tests=True)
        store.close()
        if key is not None:
            registry = {key: registry[key]} if key in registry else {}
    else:
        store.close()
        with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
            registry = rg.config_registry(key=key)

    if not registry:
        if key:
            console.print(f"[yellow]Config key '{key}' not found in registry.[/]")
        else:
            console.print("[yellow]Config registry not found.[/] Run [bold]repograph sync[/] first.")
        raise typer.Exit(1)

    if as_json:
        console.print(_json.dumps(registry, indent=2))
        return

    if key:
        # Single key detail view
        data = registry.get(key, {})
        console.print(f"\n[bold cyan]Config key:[/] {key}")
        console.print(f"[bold]Usage count:[/] {data.get('usage_count', 0)}\n")
        pathways = data.get("pathways", [])
        if pathways:
            console.print("[bold]Used by pathways:[/]")
            for pw in pathways:
                console.print(f"  • {pw}")
        files = data.get("files", [])
        if files:
            console.print(f"\n[bold]Read in files ({len(files)}):[/]")
            for fp in files[:20]:
                console.print(f"  {fp}")
            if len(files) > 20:
                console.print(f"  [dim]… and {len(files) - 20} more[/]")
        return

    # Split into top-level keys and dotted-path keys so granular entries
    # (e.g. market.symbol) don't get buried below shallow aggregate keys
    # that happen to have higher raw usage counts (e.g. market: 12 usages).
    top_level = [(k, v) for k, v in registry.items() if "." not in k]
    dotted = [(k, v) for k, v in registry.items() if "." in k]

    def _registry_table(title: str, items: list) -> None:
        if not items:
            return
        t = Table(title=title, show_header=True)
        t.add_column("Config Key", style="cyan", min_width=28)
        t.add_column("Usage", justify="right", style="dim")
        t.add_column("Pathways", justify="right")
        t.add_column("Files", justify="right")
        t.add_column("Sample Pathways", style="dim", max_width=40)
        for k, data in items[:top]:
            pw_list = data.get("pathways", [])
            sample = ", ".join(pw_list[:2])
            if len(pw_list) > 2:
                sample += f" +{len(pw_list)-2}"
            t.add_row(
                k,
                str(data.get("usage_count", 0)),
                str(len(pw_list)),
                str(len(data.get("files", []))),
                sample or "[dim]—[/]",
            )
        console.print(t)

    _registry_table(
        f"Top-Level Config Keys  (top {min(top, len(top_level))} of {len(top_level)})",
        top_level,
    )
    if dotted:
        _registry_table(
            f"Dotted Config Keys  ({len(dotted)} granular paths)",
            sorted(dotted, key=lambda x: -x[1]["usage_count"]),
        )
    total = len(registry)
    console.print(
        f"\n[dim]{total} config keys total "
        f"({len(top_level)} top-level, {len(dotted)} dotted). "
        f"Use [bold]--key <n>[/] for blast-radius detail.[/]"
    )



@app.command()
def modules(
    path: Optional[str] = typer.Argument(None),
    min_files: int = typer.Option(1, "--min-files", "-m", help="Hide modules with fewer than N files."),
    issues_only: bool = typer.Option(False, "--issues", help="Only show modules with dead code or duplicates."),
    as_json: bool = typer.Option(False, "--json", help="Output as machine-readable JSON."),
) -> None:
    """Module map: per-directory overview of classes, coverage, and issues.

    A single call gives a structural map of the entire repository — replaces
    calling 'node' on every file individually when doing context-gathering.
    """
    import json as _json

    root, rg = _get_service(path)
    with rg:
        mod_list = rg.modules()

    if not mod_list:
        console.print("[yellow]Module index not found.[/] Run [bold]repograph sync[/] to build it.")
        raise typer.Exit(1)

    # Apply filters
    if min_files > 1:
        mod_list = [
            m for m in mod_list
            if m.get("prod_file_count", m.get("file_count", 0)) >= min_files
        ]
    if issues_only:
        mod_list = [m for m in mod_list if m["dead_code_count"] > 0 or m["duplicate_count"] > 0]

    if as_json:
        console.print(_json.dumps(mod_list, indent=2))
        return

    table = Table(title="Module Map", show_header=True, show_lines=False)
    table.add_column("Module", style="cyan", min_width=20)
    table.add_column("Src/Test", justify="right", style="dim")
    table.add_column("Fn", justify="right", style="dim")
    table.add_column("Cls", justify="right", style="dim")
    table.add_column("Key Classes", style="white", max_width=36)
    table.add_column("TstFn", justify="right", style="dim")
    table.add_column("Issues", justify="right")

    prod = [m for m in mod_list if m.get("category", "production") != "tooling"]
    tool = [m for m in mod_list if m.get("category") == "tooling"]

    def _src_test(m: dict) -> str:
        src = m.get("prod_file_count", m.get("file_count", 0))
        tst = m.get("test_file_count", 0)
        return f"{src}/{tst}"

    def _add_rows(rows: list) -> None:
        for m in rows:
            issue_parts = []
            if m["dead_code_count"]:
                issue_parts.append(f"[red]{m['dead_code_count']} dead[/]")
            if m["duplicate_count"]:
                issue_parts.append(f"[yellow]{m['duplicate_count']} dup[/]")
            issue_str = "  ".join(issue_parts) if issue_parts else "[green]—[/]"

            tst_fn = m.get("test_function_count", 0)
            tst_fn_str = str(tst_fn) if tst_fn else "[dim]—[/]"
            key_cls = ", ".join(m["key_classes"][:3])
            if len(m["key_classes"]) > 3:
                key_cls += f"… +{len(m['key_classes']) - 3}"

            table.add_row(
                m["display"],
                _src_test(m),
                str(m["function_count"]),
                str(m["class_count"]),
                key_cls or "[dim]—[/]",
                tst_fn_str,
                issue_str,
            )

    _add_rows(prod)
    console.print(table)
    if tool:
        console.print("\n[bold dim]Tooling & scripts[/]")
        t2 = Table(title=None, show_header=True, show_lines=False)
        t2.add_column("Module", style="cyan", min_width=20)
        t2.add_column("Src/Test", justify="right", style="dim")
        t2.add_column("Fn", justify="right", style="dim")
        t2.add_column("Cls", justify="right", style="dim")
        t2.add_column("Key Classes", style="white", max_width=36)
        t2.add_column("TstFn", justify="right", style="dim")
        t2.add_column("Issues", justify="right")
        for m in tool:
            issue_parts = []
            if m["dead_code_count"]:
                issue_parts.append(f"[red]{m['dead_code_count']} dead[/]")
            if m["duplicate_count"]:
                issue_parts.append(f"[yellow]{m['duplicate_count']} dup[/]")
            issue_str = "  ".join(issue_parts) if issue_parts else "[green]—[/]"
            tst_fn = m.get("test_function_count", 0)
            tst_fn_str = str(tst_fn) if tst_fn else "[dim]—[/]"
            key_cls = ", ".join(m["key_classes"][:3])
            if len(m["key_classes"]) > 3:
                key_cls += f"… +{len(m['key_classes']) - 3}"
            t2.add_row(
                m["display"],
                _src_test(m),
                str(m["function_count"]),
                str(m["class_count"]),
                key_cls or "[dim]—[/]",
                tst_fn_str,
                issue_str,
            )
        console.print(t2)

    console.print(
        f"\n[dim]{len(mod_list)} modules shown.[/] Use [bold]--issues[/] to filter, [bold]--json[/] for full data."
    )


@app.command("events")
def events_cmd(
    path: Optional[str] = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Event topology: publish/subscribe style call sites (Phase 19)."""
    import json as _json
    from repograph.api import RepoGraph
    from repograph.config import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()
    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        if not rg._is_initialized():
            console.print("[red]Not initialized. Run [bold]repograph sync[/] first.[/]")
            raise typer.Exit(1)
        rows = rg.event_topology()
    if as_json:
        console.print(_json.dumps(rows, indent=2))
        return
    for r in rows[:80]:
        console.print(
            f"  [cyan]{r.get('event_type', '?')}[/]  "
            f"[dim]{r.get('role', '')}[/]  {r.get('file_path', '')}:{r.get('line', '')}"
        )


@app.command("interfaces")
def interfaces_cmd(
    path: Optional[str] = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Interface map: classes with EXTENDS/IMPLEMENTS edges."""
    import json as _json
    from repograph.api import RepoGraph
    from repograph.config import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()
    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        if not rg._is_initialized():
            console.print("[red]Not initialized. Run [bold]repograph sync[/] first.[/]")
            raise typer.Exit(1)
        data = rg.interface_map()
    if as_json:
        console.print(_json.dumps(data, indent=2))
        return
    for block in data[:40]:
        console.print(f"\n[bold]{block.get('interface', '?')}[/]  [dim]{block.get('interface_file', '')}[/]")
        for impl in block.get("implementations", [])[:12]:
            console.print(f"  • {impl.get('class', '')}  [dim]{impl.get('file_path', '')}[/]")


@app.command("deps")
def deps_cmd(
    symbol: str = typer.Argument(..., help="Class name (unqualified)"),
    path: Optional[str] = typer.Option(None, "--path", help="Repository root"),
    depth: int = typer.Option(2, "--depth", "-d", help="Recursion depth (reserved)."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Constructor dependency hints: ``__init__`` parameter names for a class."""
    import json as _json
    from repograph.api import RepoGraph
    from repograph.config import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()
    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        if not rg._is_initialized():
            console.print("[red]Not initialized. Run [bold]repograph sync[/] first.[/]")
            raise typer.Exit(1)
        data = rg.constructor_deps(symbol, depth=depth)
    if as_json:
        console.print(_json.dumps(data, indent=2))
        return

    if "error" in data:
        console.print(f"[yellow]Class '{symbol}' not found.[/] Run [bold]repograph sync[/] first.")
        raise typer.Exit(1)

    params = data.get("parameters") or []
    if not params:
        console.print(
            f"[bold]{data.get('class', symbol)}[/]  [dim]__init__[/]\n"
            f"  [dim]No typed constructor parameters found.[/]\n"
            f"  [dim](Run [bold]repograph sync[/] if the index was built before the HAS_METHOD fix.)[/]"
        )
        return

    # Render a clean dependency tree showing parameter name and type.
    # Parameters without type annotations are shown in dim style.
    console.print(f"\n[bold cyan]{data.get('class', symbol)}[/]  [dim]__init__ dependencies[/]")
    for p in params:
        name = p.get("name", "?") if isinstance(p, dict) else str(p)
        ptype = p.get("type", "") if isinstance(p, dict) else ""
        if ptype:
            console.print(f"  [green]└──[/] [cyan]{name}[/]  [dim]{ptype}[/]")
        else:
            console.print(f"  [green]└──[/] [cyan]{name}[/]  [dim](no annotation)[/]")
    console.print()


@app.command()
def invariants(
    path: Optional[str] = typer.Argument(None),
    type_filter: Optional[str] = typer.Option(None, "--type", "-t",
        help="Filter by type: constraint | guarantee | thread | lifecycle"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show architectural invariants documented in docstrings.

    Surfaces constraints like 'NEVER calls X', 'NOT thread-safe', 'MUST be
    started before Y' so AI agents and developers don't accidentally violate them.
    """
    import json as _json
    from repograph.api import RepoGraph
    from repograph.config import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()

    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        items = rg.invariants(inv_type=type_filter)

    if not items:
        if type_filter:
            console.print(f"[yellow]No '{type_filter}' invariants found.[/]")
        else:
            console.print("[yellow]No invariants found.[/] Run [bold]repograph sync[/] first, "
                          "or add INV-/NEVER/MUST NOT annotations to docstrings.")
        raise typer.Exit(0)

    if as_json:
        console.print(_json.dumps(items, indent=2))
        return

    type_order = ["constraint", "guarantee", "thread", "lifecycle"]
    by_type: dict[str, list[dict]] = {t: [] for t in type_order}
    for item in items:
        t = item.get("invariant_type", "constraint")
        by_type.setdefault(t, []).append(item)

    type_colors = {"constraint": "red", "guarantee": "green",
                   "thread": "yellow", "lifecycle": "cyan"}

    console.print(f"\n[bold]Architectural Invariants[/]  ({len(items)} total)\n")
    for t in type_order:
        group = by_type.get(t, [])
        if not group:
            continue
        color = type_colors.get(t, "white")
        console.print(f"[bold {color}]{t.upper()} ({len(group)})[/]")
        for item in group:
            sym = item.get("symbol_name", "?")
            fp = item.get("file_path", "")
            text = item.get("invariant_text", "")
            console.print(f"  [cyan]{sym}[/]  [dim]{fp}[/]")
            console.print(f"    {text}")
        console.print()


@app.command(name="test-map")
def test_map(
    path: Optional[str] = typer.Argument(None),
    min_eps: int = typer.Option(1, "--min-eps", help="Only show files with at least N entry points."),
    uncovered_only: bool = typer.Option(False, "--uncovered", help="Only show files with 0% coverage."),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON."),
    any_call: bool = typer.Option(
        False,
        "--any-call",
        help=(
            "Count any production function with a test caller, not only Phase-10 "
            "is_entry_point functions — different denominator; closer to 'tests touch this file'."
        ),
    ),
) -> None:
    """Test coverage map: production functions reachable from tests via CALLS.

    Default metric: share of **Phase-10 entry points** per file with a CALLS edge
    from an ``is_test`` function.  Use ``--any-call`` for **all** non-test
    functions in the file (not line or branch coverage).  Files are sorted by
    coverage (least covered first).  0% rows are highlighted in red.
    """
    import json as _json
    from repograph.api import RepoGraph
    from repograph.config import repograph_dir

    root, store = _get_root_and_store(path)
    store.close()

    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        rows = rg.test_coverage_any_call() if any_call else rg.test_coverage()

    if not rows:
        console.print("[yellow]No rows found.[/] Run [bold]repograph sync[/] first.")
        raise typer.Exit(1)

    count_key = "function_count" if any_call else "entry_point_count"
    tested_key = "tested_functions" if any_call else "tested_entry_points"

    if min_eps > 1:
        rows = [r for r in rows if r[count_key] >= min_eps]
    if uncovered_only:
        rows = [r for r in rows if r[tested_key] == 0]

    if as_json:
        console.print(_json.dumps(rows, indent=2))
        return

    tested_count = sum(1 for r in rows if r["coverage_pct"] == 100.0)
    uncovered_count = sum(1 for r in rows if r[tested_key] == 0)
    total_units = sum(r[count_key] for r in rows)
    total_tested = sum(r[tested_key] for r in rows)
    overall_pct = round(total_tested / total_units * 100, 1) if total_units else 0.0

    from repograph.graph_store.store_queries_analytics import (
        ANY_CALL_TEST_COVERAGE_DEFINITION,
        ENTRY_POINT_TEST_COVERAGE_DEFINITION,
    )

    label = "functions" if any_call else "entry points"
    defn = ANY_CALL_TEST_COVERAGE_DEFINITION if any_call else ENTRY_POINT_TEST_COVERAGE_DEFINITION

    console.print(f"\n[bold]Test Coverage Map[/]  "
                  f"{total_tested}/{total_units} {label} tested  "
                  f"([{'green' if overall_pct >= 70 else 'yellow' if overall_pct >= 40 else 'red'}]"
                  f"{overall_pct}% overall[/])")
    console.print(f"[dim]{defn}[/]\n")

    table = Table(show_header=True, show_lines=False)
    table.add_column("File", style="cyan", min_width=35)
    col_n = "Fns" if any_call else "EPs"
    table.add_column(col_n, justify="right", style="dim")
    table.add_column("Tested", justify="right")
    table.add_column("Coverage", justify="right")
    table.add_column("Test Files", style="dim", max_width=40)

    for r in rows:
        pct = r["coverage_pct"]
        if pct == 0.0:
            pct_str = "[red]0%[/]"
        elif pct < 50.0:
            pct_str = f"[yellow]{pct:.0f}%[/]"
        elif pct < 100.0:
            pct_str = f"[cyan]{pct:.0f}%[/]"
        else:
            pct_str = "[green]100%[/]"

        tf = r.get("test_files", [])
        tf_str = ", ".join(t.split("/")[-1] for t in tf[:2])
        if len(tf) > 2:
            tf_str += f" +{len(tf)-2}"

        table.add_row(
            r["file_path"],
            str(r[count_key]),
            str(r[tested_key]),
            pct_str,
            tf_str or "[dim]none[/]",
        )

    console.print(table)
    console.print(
        f"\n[dim]{len(rows)} files · {uncovered_count} with no test coverage · "
        f"{tested_count} fully covered[/]"
    )


# ---------------------------------------------------------------------------
# repograph pathway list / show / update
# ---------------------------------------------------------------------------

@pathway_app.command("list")
def pathway_list(
    path: Optional[str] = typer.Argument(None),
    include_tests: bool = typer.Option(
        False, "--include-tests",
        help="Include auto-detected test pathways in the list.",
    ),
):
    """List all pathways with confidence and step count.

    By default only production pathways are shown.  Pass --include-tests
    to also see test-entry pathways.
    """
    root, rg = _get_service(path)
    with rg:
        all_pathways = rg.pathways(min_confidence=0.0, include_tests=True)

    if not all_pathways:
        console.print("[yellow]No pathways found. Run [bold]repograph sync[/] first.[/]")
        raise typer.Exit(0)

    prod = [p for p in all_pathways if p.get("source") != "auto_detected_test"]
    tests = [p for p in all_pathways if p.get("source") == "auto_detected_test"]

    def _render_table(pathways: list[dict], title: str) -> None:
        table = Table(title=title, show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Display Name")
        table.add_column("Steps", justify="right")
        table.add_column("Importance", justify="right")
        table.add_column("Confidence", justify="right")
        table.add_column("Source", style="dim")
        sorted_ps = sorted(
            pathways,
            key=lambda x: (-(x.get("importance_score") or 0.0), -(x.get("confidence") or 0.0)),
        )
        for p in sorted_ps:
            conf = p.get("confidence") or 0.0
            imp = p.get("importance_score") or 0.0
            color = "green" if conf >= 0.8 else "yellow" if conf >= 0.5 else "red"
            table.add_row(
                p["name"],
                p.get("display_name") or p["name"],
                str(p.get("step_count") or 0),
                f"{imp:.2f}",
                f"[{color}]{conf:.2f}[/]",
                p.get("source") or "auto",
            )
        console.print(table)

    _render_table(prod, f"Pathways ({len(prod)} production)")
    if tests:
        if include_tests:
            _render_table(tests, f"Test pathways ({len(tests)})")
        else:
            console.print(
                f"[dim]{len(tests)} test pathway(s) hidden "
                f"— pass [bold]--include-tests[/] to show them.[/]"
            )


@pathway_app.command("show")
def pathway_show(
    name: str = typer.Argument(..., help="Pathway name"),
    path: Optional[str] = typer.Argument(None, help="Repo path (defaults to cwd)"),
):
    """Print the full context document for a pathway."""
    root, store = _get_root_and_store(path)
    pathway = store.get_pathway(name)

    if not pathway:
        console.print(f"[red]Pathway '{name}' not found.[/]")
        console.print("Run [bold]repograph pathway list[/] to see available pathways.")
        raise typer.Exit(1)

    ctx = pathway.get("context_doc") or ""
    if not ctx:
        # Generate on demand
        from repograph.plugins.exporters.pathway_contexts.generator import generate_pathway_context
        ctx = generate_pathway_context(pathway["id"], store)

    if ctx:
        console.print(ctx)
    else:
        # Fallback: show basic info
        console.print(Panel(
            f"[bold]{pathway.get('display_name') or name}[/]\n\n"
            f"Entry: {pathway.get('entry_function', '?')}\n"
            f"Steps: {pathway.get('step_count', 0)}\n"
            f"Confidence: {pathway.get('confidence', 0.0):.2f}",
            title=f"pathway: {name}",
        ))


@pathway_app.command("update")
def pathway_update(
    name: str = typer.Argument(..., help="Pathway name"),
    path: Optional[str] = typer.Option(None, "--path"),
):
    """Re-generate context document for a single pathway."""
    root, store = _get_root_and_store(path)
    from repograph.config import get_repo_root
    from repograph.plugins.exporters.pathway_contexts.generator import generate_pathway_context
    from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler
    from repograph.plugins.static_analyzers.pathways.curator import PathwayCurator

    pathway = store.get_pathway(name)
    if not pathway:
        console.print(f"[red]Pathway '{name}' not found.[/]")
        raise typer.Exit(1)

    # Re-assemble pathway steps
    curator = PathwayCurator(root)
    assembler = PathwayAssembler(store)
    ep_id = pathway.get("id", "").replace("pathway:", "", 1)
    curated = curator.get(name)

    doc = assembler.assemble(ep_id, curated_def=curated)
    if doc:
        store.upsert_pathway(doc)
        for step in doc.steps:
            store.insert_step_in_pathway(step.function_id, doc.id, step.order, step.role)

    ctx = generate_pathway_context(pathway["id"], store)
    if ctx:
        console.print(f"[green]✓ Updated context doc for '{name}' ({len(ctx)} chars)[/]")
    else:
        console.print(f"[yellow]Could not generate context for '{name}'[/]")


# ---------------------------------------------------------------------------
# repograph node
# ---------------------------------------------------------------------------

@app.command()
def report(
    path: Optional[str] = typer.Argument(
        None,
        help="Repository root (default: current directory). Do not use a bare “full” as the path — use --full.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON (machine-readable, all fields)."),
    full: bool = typer.Option(
        False,
        "--full",
        help="With --json: write the report to .repograph/report.json instead of stdout.",
    ),
    max_pathways: int = typer.Option(10, "--pathways", "-p", help="Max pathways to include (default 10)."),
    max_dead: int = typer.Option(20, "--dead", "-d", help="Max dead-code symbols per tier (default 20)."),
) -> None:
    """Full intelligence report — every insight the tool has in one command.

    Aggregates: purpose, stats, module map, entry points, top pathways (with
    full context docs), dead code, duplicates (with canonical guidance),
    invariants, config registry, test coverage, and doc warnings.

    Ideal as a single context-injection for an AI entering an unfamiliar repo,
    or as a human-readable health check before a release.
    """
    import json as _json
    from repograph.api import RepoGraph
    from repograph.config import repograph_dir

    if path is not None and path.strip().lower() == "full":
        path = None

    root, store = _get_root_and_store(path)
    store.close()

    with RepoGraph(root, repograph_dir=repograph_dir(root)) as rg:
        data = rg.full_report(max_pathways=max_pathways, max_dead=max_dead)

    if as_json:
        if full:
            rg_path = os.path.join(repograph_dir(root), "report.json")
            os.makedirs(os.path.dirname(rg_path), exist_ok=True)
            with open(rg_path, "w", encoding="utf-8") as f:
                _json.dump(data, f, indent=2, default=str, ensure_ascii=False)
                f.write("\n")
            console.print(f"[green]Wrote[/] {rg_path}")
            return
        # Write plain JSON to stdout — avoid Rich/console markup corrupting strings.
        import sys

        sys.stdout.write(
            _json.dumps(data, indent=2, default=str, ensure_ascii=False)
        )
        sys.stdout.write("\n")
        return

    # ── Human-readable render ────────────────────────────────────────────────
    SEP = "─" * 64

    def _hdr(title: str) -> None:
        console.print(f"\n[bold cyan]{title}[/]")
        console.print(f"[dim]{SEP}[/]")

    def _kv(label: str, value: str, color: str = "white") -> None:
        console.print(f"  [dim]{label:<22}[/][{color}]{value}[/]")

    # ── 1. Identity & health ─────────────────────────────────────────────────
    _hdr("Repository")
    _kv("Path", data["meta"]["repo_path"])
    health = data.get("health", {})
    h_status = health.get("status", "?")
    h_color = "green" if h_status == "ok" else "yellow" if h_status == "degraded" else "red"
    _kv("Health", h_status, h_color)
    _kv("Sync mode", health.get("sync_mode", "?"))
    _kv("Last sync", health.get("generated_at", "?"))
    _kv("Call edges", str(health.get("call_edges_total", "?")))
    if health.get("partial_completion"):
        _kv("Partial completion", "true", "yellow")

    # ── 2. Purpose ───────────────────────────────────────────────────────────
    if data.get("purpose"):
        _hdr("Purpose")
        console.print(f"  {data['purpose']}")

    # ── 3. Stats ─────────────────────────────────────────────────────────────
    _hdr("Index Stats")
    stats = data.get("stats", {})
    stat_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    stat_table.add_column("k", style="dim")
    stat_table.add_column("v", style="cyan")
    for k in ("files", "functions", "classes", "variables", "pathways", "communities"):
        if k in stats:
            stat_table.add_row(k.title(), str(stats[k]))
    console.print(stat_table)

    ro = data.get("runtime_observations") or {}
    n_rt = int(ro.get("functions_with_valid_runtime_revision") or 0)
    if n_rt > 0:
        console.print(
            f"  [dim]Runtime DB (traces merged for current source_hash):[/] "
            f"[green]{n_rt}[/] function(s)"
        )

    # ── 4. Module map ─────────────────────────────────────────────────────────
    mods = data.get("modules", [])
    if mods:
        _hdr(f"Module Map  ({len(mods)} modules)")
        mod_table = Table(show_header=True, show_lines=False, box=None)
        mod_table.add_column("Module", style="cyan", min_width=20)
        mod_table.add_column("Src/Test", justify="right", style="dim")
        mod_table.add_column("Fn", justify="right", style="dim")
        mod_table.add_column("Key Classes", max_width=38)
        mod_table.add_column("TstFn", justify="right", style="dim")
        mod_table.add_column("Issues", justify="right")
        for m in mods:
            issues = []
            if m["dead_code_count"]:
                issues.append(f"[red]{m['dead_code_count']}dead[/]")
            if m["duplicate_count"]:
                issues.append(f"[yellow]{m['duplicate_count']}dup[/]")
            key_cls = ", ".join(m["key_classes"][:3])
            if len(m["key_classes"]) > 3:
                key_cls += f" +{len(m['key_classes'])-3}"
            src = m.get("prod_file_count", m.get("file_count", 0))
            tst = m.get("test_file_count", 0)
            tst_fn = m.get("test_function_count", 0)
            tst_fn_str = str(tst_fn) if tst_fn else "[dim]—[/]"
            mod_table.add_row(
                m["display"],
                f"{src}/{tst}",
                str(m["function_count"]),
                key_cls or "[dim]—[/]",
                tst_fn_str,
                "  ".join(issues) if issues else "[green]—[/]",
            )
        console.print(mod_table)

    # ── 5. Top entry points ──────────────────────────────────────────────────
    eps = data.get("entry_points", [])
    if eps:
        _hdr(f"Top Entry Points  ({len(eps)})")
        ep_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        ep_table.add_column("Score", style="dim", justify="right")
        ep_table.add_column("Function", style="cyan")
        ep_table.add_column("File", style="dim")
        for ep in eps[:10]:
            ep_table.add_row(
                f"{ep.get('entry_score', 0):.1f}",
                ep.get("qualified_name", "?"),
                ep.get("file_path", ""),
            )
        console.print(ep_table)

    # ── 6. Pathways ──────────────────────────────────────────────────────────
    pathways = data.get("pathways", [])
    pw_summary = data.get("pathways_summary", {})
    if pathways:
        total_pw = pw_summary.get("total", len(pathways))
        _hdr(f"Top Pathways  ({len(pathways)} shown of {total_pw}, full context docs included)")
        for pw in pathways:
            name = pw.get("display_name") or pw.get("name", "?")
            conf = pw.get("confidence", 0)
            steps = pw.get("step_count", 0)
            imp = pw.get("importance_score") or 0
            conf_color = "green" if conf >= 0.8 else "yellow" if conf >= 0.6 else "red"
            console.print(
                f"  [cyan]{name}[/]  "
                f"[dim]steps={steps}  imp={imp:.1f}  conf=[/]"
                f"[{conf_color}]{conf:.2f}[/]"
            )
            # Print abridged context doc (first 20 lines)
            ctx = pw.get("context_doc", "")
            if ctx:
                preview_lines = [l for l in ctx.split("\n") if l.strip()][:12]
                for line in preview_lines:
                    console.print(f"    [dim]{line}[/]")
            console.print()

    warnings = data.get("report_warnings", [])
    if warnings:
        _hdr("Report Warnings")
        for w in warnings:
            console.print(f"  [yellow]-[/] {w}")

    # ── 7. Dead code ─────────────────────────────────────────────────────────
    dead = data.get("dead_code", {})
    def_dead = dead.get("definitely_dead", [])
    prob_dead = dead.get("probably_dead", [])
    def_tool = dead.get("definitely_dead_tooling", [])
    prob_tool = dead.get("probably_dead_tooling", [])
    _hdr(
        f"Dead Code (production)  "
        f"(definitely={len(def_dead)}  probably={len(prob_dead)})"
    )
    if def_dead:
        console.print("  [bold red]Definitely dead:[/]")
        d_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        d_table.add_column("Symbol", style="red")
        d_table.add_column("File", style="dim")
        for d in def_dead[:15]:
            d_table.add_row(d.get("qualified_name", "?"), d.get("file_path", ""))
        console.print(d_table)
    if prob_dead:
        console.print("  [bold yellow]Probably dead:[/]")
        p_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        p_table.add_column("Symbol", style="yellow")
        p_table.add_column("Reason", style="dim")
        for d in prob_dead[:10]:
            p_table.add_row(d.get("qualified_name", "?"),
                            d.get("dead_code_reason", ""))
        console.print(p_table)
    if def_tool or prob_tool:
        _hdr(
            f"Dead Code (tooling / tests / docs)  "
            f"(definitely={len(def_tool)}  probably={len(prob_tool)})"
        )
        if def_tool:
            console.print("  [bold red]Definitely dead:[/]")
            dt = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
            dt.add_column("Symbol", style="red")
            dt.add_column("File", style="dim")
            for d in def_tool[:10]:
                dt.add_row(d.get("qualified_name", "?"), d.get("file_path", ""))
            console.print(dt)
        if prob_tool:
            console.print("  [bold yellow]Probably dead:[/]")
            pt = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
            pt.add_column("Symbol", style="yellow")
            pt.add_column("Reason", style="dim")
            for d in prob_tool[:8]:
                pt.add_row(d.get("qualified_name", "?"), d.get("dead_code_reason", ""))
            console.print(pt)

    # ── 8. Duplicates ────────────────────────────────────────────────────────
    dups = data.get("duplicates", [])
    if dups:
        _hdr(f"Duplicate Symbols  ({len(dups)} groups)")
        dup_table = Table(show_header=True, show_lines=False, box=None)
        dup_table.add_column("Symbol", style="cyan")
        dup_table.add_column("Sev", style="dim")
        dup_table.add_column("Canonical", style="green")
        dup_table.add_column("Stale copy", style="red")
        for d in dups[:12]:
            canonical = d.get("canonical_path", "")
            stale = (d.get("superseded_paths") or [""])[0]
            dup_table.add_row(
                d.get("name", "?"),
                d.get("severity", ""),
                canonical.split("/")[-1] if canonical else "[dim]unknown[/]",
                stale.split("/")[-1] if stale else "[dim]—[/]",
            )
        console.print(dup_table)

    # ── 9. Invariants ────────────────────────────────────────────────────────
    invs = data.get("invariants", [])
    if invs:
        _hdr(f"Architectural Invariants  ({len(invs)} documented)")
        type_colors = {"constraint": "red", "guarantee": "green",
                       "thread": "yellow", "lifecycle": "cyan"}
        for inv in invs[:20]:
            t = inv.get("invariant_type", "constraint")
            color = type_colors.get(t, "white")
            sym = inv.get("symbol_name", "?")
            text = inv.get("invariant_text", "")
            console.print(f"  [{color}][{t}][/]  [cyan]{sym}[/]")
            console.print(f"    {text}")

    # ── 10. Config registry ──────────────────────────────────────────────────
    cfg = data.get("config_registry", {})
    if cfg:
        _hdr(f"Config Key Registry  (top {len(cfg)} by usage)")
        cfg_table = Table(show_header=True, show_lines=False, box=None)
        cfg_table.add_column("Key", style="cyan", min_width=20)
        cfg_table.add_column("Usage", justify="right", style="dim")
        cfg_table.add_column("Pathways", justify="right")
        cfg_table.add_column("Files", justify="right")
        for key, val in list(cfg.items())[:20]:
            cfg_table.add_row(
                key,
                str(val.get("usage_count", 0)),
                str(len(val.get("pathways", []))),
                str(len(val.get("files", []))),
            )
        console.print(cfg_table)

    # ── 11. Test coverage ────────────────────────────────────────────────────
    cov = data.get("test_coverage", [])
    if cov:
        total_eps = sum(r["entry_point_count"] for r in cov)
        total_tested = sum(r["tested_entry_points"] for r in cov)
        overall = round(total_tested / total_eps * 100, 1) if total_eps else 0.0
        uncovered = sum(1 for r in cov if r["tested_entry_points"] == 0)
        cov_color = "green" if overall >= 70 else "yellow" if overall >= 40 else "red"
        _hdr(f"Test Coverage  "
             f"[{cov_color}]{overall}% overall[/]  "
             f"({uncovered} files with no coverage)")
        cd = data.get("coverage_definition") or ""
        if cd:
            console.print(f"  [dim]{cd}[/]")
        # Show worst 10 (already sorted ascending)
        if uncovered > 0:
            console.print("  [bold red]Files with 0% entry-point coverage:[/]")
            cov_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
            cov_table.add_column("File", style="red")
            cov_table.add_column("EPs", justify="right", style="dim")
            for r in [r for r in cov if r["tested_entry_points"] == 0][:10]:
                cov_table.add_row(r["file_path"], str(r["entry_point_count"]))
            console.print(cov_table)

    # ── 12. Doc warnings ─────────────────────────────────────────────────────
    warns = data.get("doc_warnings", [])
    if warns:
        _hdr(f"Doc Warnings  ({len(warns)} high-severity)")
        w_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        w_table.add_column("Doc", style="dim")
        w_table.add_column("Line", justify="right", style="dim")
        w_table.add_column("Symbol", style="yellow")
        for w in warns[:10]:
            w_table.add_row(
                w.get("doc_path", ""),
                str(w.get("line_number", "")),
                w.get("symbol_text", ""),
            )
        console.print(w_table)

    console.print(
        "\n[dim]Use [bold]repograph report --json[/bold] for full machine-readable output on stdout; "
        "[bold]repograph report --full --json[/bold] writes the same payload to "
        "[bold].repograph/report.json[/bold].[/]\n"
    )


@app.command()
def node(
    identifier: str = typer.Argument(..., help="File path or symbol qualified name"),
    path: Optional[str] = typer.Option(None, "--path"),
):
    """Show structured truth for a file or symbol."""
    root, store = _get_root_and_store(path)

    # Try as file first
    file_info = store.get_file(identifier)
    if file_info:
        functions = store.get_functions_in_file(identifier)
        table = Table(title=f"File: {identifier}")
        table.add_column("Function", style="cyan")
        table.add_column("Lines")
        table.add_column("Entry", justify="center")
        table.add_column("Dead", justify="center")
        for fn in functions:
            table.add_row(
                fn["qualified_name"],
                f"{fn['line_start']}–{fn['line_end']}",
                "✓" if fn.get("is_entry_point") else "",
                "✗" if fn.get("is_dead") else "",
            )
        console.print(table)
        return

    # Try as function name search
    results = store.search_functions_by_name(identifier, limit=5)
    if not results:
        console.print(f"[red]No file or symbol found for '{identifier}'[/]")
        raise typer.Exit(1)

    for fn_info in results:
        fn = store.get_function_by_id(fn_info["id"])
        if not fn:
            continue
        callers = store.get_callers(fn["id"])
        callees = store.get_callees(fn["id"])
        console.print(Panel(
            f"[bold]{fn['qualified_name']}[/]\n"
            f"File: {fn['file_path']} : {fn['line_start']}–{fn['line_end']}\n"
            f"Signature: {fn['signature']}\n"
            f"Entry point: {fn.get('is_entry_point', False)}  Dead: {fn.get('is_dead', False)}\n"
            f"Callers ({len(callers)}): {', '.join(c['qualified_name'].split(':')[-1] for c in callers[:5])}\n"
            f"Callees ({len(callees)}): {', '.join(c['qualified_name'].split(':')[-1] for c in callees[:5])}",
            title=f"node: {fn['name']}",
        ))


# ---------------------------------------------------------------------------
# repograph impact
# ---------------------------------------------------------------------------

@app.command()
def impact(
    symbol: str = typer.Argument(..., help="Symbol name or qualified name"),
    depth: int = typer.Option(3, "--depth", "-d"),
    path: Optional[str] = typer.Option(None, "--path"),
):
    """Blast radius: everything that calls or imports this symbol."""
    root, store = _get_root_and_store(path)

    results = store.search_functions_by_name(symbol, limit=1)
    if not results:
        console.print(f"[red]Symbol '{symbol}' not found.[/]")
        raise typer.Exit(1)

    fn_id = results[0]["id"]
    fn = store.get_function_by_id(fn_id)
    if not fn:
        raise typer.Exit(1)

    # BFS upward through callers
    visited: dict[str, dict] = {}
    level_map: dict[str, int] = {}
    queue = [(fn_id, 0)]
    while queue:
        cur_id, cur_depth = queue.pop(0)
        if cur_id in visited or cur_depth > depth:
            continue
        visited[cur_id] = store.get_function_by_id(cur_id) or {}
        level_map[cur_id] = cur_depth
        for caller in store.get_callers(cur_id):
            if caller["id"] not in visited:
                queue.append((caller["id"], cur_depth + 1))

    # Remove the target itself
    visited.pop(fn_id, None)

    if not visited:
        console.print(f"[green]'{symbol}' has no callers — safe to change.[/]")
        return

    table = Table(title=f"Impact of changing '{symbol}'")
    table.add_column("Depth", justify="right")
    table.add_column("Caller", style="cyan")
    table.add_column("File")
    for fid, info in sorted(visited.items(), key=lambda x: level_map.get(x[0], 0)):
        table.add_row(
            str(level_map.get(fid, "?")),
            info.get("qualified_name", "?"),
            info.get("file_path", "?"),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# repograph query
# ---------------------------------------------------------------------------

@app.command()
def query(
    text: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n"),
    path: Optional[str] = typer.Option(None, "--path"),
):
    """Hybrid search: BM25 + fuzzy name search."""
    root, store = _get_root_and_store(path)
    from repograph.search.hybrid import HybridSearch

    searcher = HybridSearch(store)
    results = searcher.search(text, limit=limit)

    if not results:
        console.print(f"[yellow]No results for '{text}'[/]")
        return

    table = Table(title=f"Search: {text}")
    table.add_column("Score", justify="right")
    table.add_column("Type", style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("File")
    for r in results:
        table.add_row(
            f"{r.get('score', 0.0):.2f}",
            r.get("type", "?"),
            r.get("name", "?"),
            r.get("file_path", "?"),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# repograph watch
# ---------------------------------------------------------------------------

@app.command()
def watch(
    path: Optional[str] = typer.Argument(None),
    no_git: bool = typer.Option(False, "--no-git"),
    strict: bool = typer.Option(False, "--strict", help="Same as sync --strict for incremental rebuilds."),
):
    """Watch mode: re-sync on file changes."""
    from repograph.config import get_repo_root, repograph_dir, db_path
    from repograph.pipeline.runner import RunConfig, run_incremental_pipeline

    root = os.path.abspath(path or os.getcwd())

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    except ImportError:
        console.print("[red]watchdog not installed.[/]")
        raise typer.Exit(1)

    rg_dir = repograph_dir(root)
    config = RunConfig(
        repo_root=root, repograph_dir=rg_dir, include_git=not no_git, strict=strict,
    )

    class Handler(FileSystemEventHandler):
        def _path_str(self, src_path: bytes | str) -> str:
            return os.fsdecode(src_path) if isinstance(src_path, bytes) else src_path

        def _should_handle(self, event_path: bytes | str) -> bool:
            p = self._path_str(event_path)
            if ".repograph" in p:
                return False
            from repograph.utils.fs import EXTENSION_TO_LANGUAGE
            import pathlib
            ext = pathlib.Path(p).suffix.lower()
            return ext in EXTENSION_TO_LANGUAGE

        def _on_file_changed(self, src_path: bytes | str) -> None:
            if self._should_handle(src_path):
                p = self._path_str(src_path)
                console.print(f"[cyan]Changed:[/] {p}")
                try:
                    run_incremental_pipeline(config)
                except Exception as e:
                    console.print(f"[red]Sync error: {e}[/]")

        def on_modified(self, event):
            if not event.is_directory:
                self._on_file_changed(event.src_path)

        def on_created(self, event):
            if not event.is_directory:
                self._on_file_changed(event.src_path)

        def on_deleted(self, event):
            if not event.is_directory and self._should_handle(event.src_path):
                console.print(f"[red]Deleted:[/] {event.src_path}")
                try:
                    run_incremental_pipeline(config)
                except Exception as e:
                    console.print(f"[red]Sync error: {e}[/]")

    observer = Observer()
    observer.schedule(Handler(), root, recursive=True)
    observer.start()
    console.print(f"[green]Watching[/] {root} for changes. Press Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


# ---------------------------------------------------------------------------
# repograph mcp
# ---------------------------------------------------------------------------

@app.command()
def mcp(
    path: Optional[str] = typer.Argument(None),
    port: Optional[int] = typer.Option(None, "--port", help="HTTP port (default: stdio)"),
):
    """Start the MCP server."""
    from repograph.mcp.server import create_server

    root, rg = _get_service(path)
    server = create_server(rg._service, port=port)

    if port is not None:
        console.print(f"[green]Starting MCP server on port {port}[/]")
        server.run(transport="streamable-http")
    else:
        typer.echo("Starting MCP server (stdio transport)", err=True)
        server.run()


# ---------------------------------------------------------------------------
# repograph export
# ---------------------------------------------------------------------------

@app.command()
def export(
    output: str = typer.Option("repograph_export.json", "--output", "-o"),
    path: Optional[str] = typer.Argument(None),
):
    """Export the full graph as JSON."""
    root, store = _get_root_and_store(path)

    data = {
        "stats": store.get_stats(),
        "functions": store.get_all_functions(),
        "call_edges": store.get_all_call_edges(),
        "pathways": store.get_all_pathways(),
        "entry_points": store.get_entry_points(),
        "dead_code": store.get_dead_functions(),
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    console.print(f"[green]Exported to {output}[/]")


# ---------------------------------------------------------------------------
# repograph clean
# ---------------------------------------------------------------------------

@app.command()
def clean(
    path: Optional[str] = typer.Argument(None),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=(
            "Do not prompt for confirmation (delete the index and, with --dev, run dev "
            "cleanup without interactive checks)."
        ),
    ),
    dev: bool = typer.Option(
        False,
        "--dev",
        "-d",
        help=(
            "Also remove Python caches, local venv dirs (.venv, venv, env), macOS junk, "
            "build/dist, Repograph trace bootstrap files (example conftest + auto-generated "
            "conftest/sitecustomize)."
        ),
    ),
    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        "-R",
        help=(
            "With --dev: scan the entire tree for caches and junk (default: on). "
            "Use --no-recursive to only clean cache dirs at the repo root."
        ),
    ),
):
    """Delete the .repograph/ index directory; use --dev for a full local dev cleanup."""
    from pathlib import Path

    from repograph.config import get_repo_root, repograph_dir
    from repograph.exceptions import RepographNotFoundError
    from repograph.utils.dev_clean import clean_development_artifacts, summarize_removed
    import shutil

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        # clean can run on un-initialized directories; just use the provided path
        root = os.path.abspath(path or os.getcwd())
    root_path = Path(root)
    rg_dir = repograph_dir(root)

    if dev:
        if not yes:
            scan = "the entire repo tree (except .git/ and node_modules/)" if recursive else "only the repo root for cache dirs"
            console.print(
                f"[bold]Dev clean[/] will scan {scan} for caches (__pycache__, etc.), "
                "remove local venv dirs (.venv, venv, env), build/dist, Repograph trace "
                "helper files, and then the RepoGraph index if present.\n"
            )
            if not typer.confirm("Continue?", default=False):
                raise typer.Exit(0)
        removed = clean_development_artifacts(root_path, recursive=recursive)
        console.print("[dim]" + summarize_removed(removed) + "[/]")
        if removed:
            console.print(f"[green]Removed {len(removed)} path(s) (dev cleanup).[/]\n")
        else:
            console.print("[yellow]No dev artifacts matched (or already clean).[/]\n")

    if not os.path.isdir(rg_dir):
        if not dev:
            console.print("[yellow]Nothing to clean.[/]")
        return

    if not dev and not yes:
        confirm = typer.confirm(f"Delete {rg_dir}?")
        if not confirm:
            raise typer.Exit(0)
    elif dev and not yes:
        if not typer.confirm(f"Delete RepoGraph index at {rg_dir}?", default=True):
            raise typer.Exit(0)
    elif dev and yes:
        pass
    elif not dev and yes:
        pass

    shutil.rmtree(rg_dir)
    console.print(f"[green]Deleted {rg_dir}[/]")

    # Clear the plugin scheduler cache so subsequent commands in the same
    # process start from a clean registry state.
    try:
        from repograph.plugins.lifecycle import reset_hook_scheduler
        reset_hook_scheduler()
    except Exception:
        pass




# ---------------------------------------------------------------------------
# repograph trace  —  dynamic analysis commands
# ---------------------------------------------------------------------------

@trace_app.command("install")
def trace_install(
    path: Optional[str] = typer.Argument(None, help="Repository root (default: cwd)."),
    mode: str = typer.Option(
        "pytest",
        "--mode", "-m",
        help="Instrumentation mode: 'pytest' (conftest.py) or 'sitecustomize'.",
    ),
    max_records: int = typer.Option(0, "--max-records", help="Max records per trace session (0 = unlimited)."),
    max_mb: int = typer.Option(0, "--max-mb", help="Max bytes per trace file in MB (0 = unlimited)."),
    rotate_files: int = typer.Option(0, "--rotate-files", help="Rotate at most N extra files when max-mb is reached."),
    sample_rate: float = typer.Option(1.0, "--sample-rate", help="Sampling rate for call records [0.0-1.0]."),
    include_pattern: str = typer.Option("", "--include", help="Regex include filter on 'file::qualified_name'."),
    exclude_pattern: str = typer.Option("", "--exclude", help="Regex exclude filter on 'file::qualified_name'."),
) -> None:
    """Write instrumentation config so the next test run generates call traces.

    Creates a conftest.py (or sitecustomize.py) at the repo root that activates
    sys.settrace tracing and writes JSONL traces to .repograph/runtime/.
    """
    from repograph.config import get_repo_root, repograph_dir as rg_dir_fn
    from repograph.exceptions import RepographNotFoundError
    from repograph.runtime.trace_format import trace_dir
    from repograph.plugins.lifecycle import get_hook_scheduler, ensure_all_plugins_registered

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        console.print("[red]Error:[/] Not initialized. Run [bold]repograph init[/] first.")
        raise typer.Exit(1)
    rg_dir = rg_dir_fn(root)
    td = trace_dir(rg_dir)

    ensure_all_plugins_registered()
    tracers = get_hook_scheduler().list_for_hook("on_tracer_install")
    if not tracers:
        console.print("[red]No tracer plugins registered.[/]")
        raise typer.Exit(1)

    from pathlib import Path
    from repograph.core.plugin_framework import TracerPlugin

    for tracer in tracers:
        if not isinstance(tracer, TracerPlugin):
            continue
        result = tracer.install(
            Path(root),
            td,
            mode=mode,
            max_records=max_records,
            max_file_bytes=max(0, int(max_mb)) * 1024 * 1024,
            rotate_files=rotate_files,
            sample_rate=sample_rate,
            include_pattern=include_pattern,
            exclude_pattern=exclude_pattern,
        )
        status = result.get("status", "?")
        config_path = result.get("config_path", "")
        if status == "already_installed":
            console.print(f"[yellow]Already installed:[/] {config_path}")
        else:
            console.print(f"[green]✓ Installed ({tracer.plugin_id()}):[/] {config_path}")
            console.print(f"  Traces will be written to: {result.get('trace_dir')}")
            console.print(
                "\nNext steps:\n"
                "  1. Run your tests normally (e.g. [bold]pytest[/]) so JSONL appears under "
                "[bold].repograph/runtime/[/]\n"
                "  2. Then run [bold]repograph sync[/] to merge traces into [bold]graph.db[/] "
                "(required — [bold]report[/] alone does not apply traces)\n"
                "  3. Or run [bold]repograph trace report[/] to inspect overlay findings without a full sync"
            )


@trace_app.command("collect")
def trace_collect(
    path: Optional[str] = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json", help="Output trace inventory as JSON."),
) -> None:
    """List trace files collected in .repograph/runtime/."""
    from repograph.config import get_repo_root, repograph_dir as rg_dir_fn
    from repograph.exceptions import RepographNotFoundError
    from repograph.runtime.trace_format import collect_trace_files

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        console.print("[red]Error:[/] Not initialized. Run [bold]repograph init[/] first.")
        raise typer.Exit(1)
    rg_dir = rg_dir_fn(root)

    files = collect_trace_files(rg_dir)
    if not files:
        console.print(
            "[yellow]No trace files in .repograph/runtime/.[/]\n"
            "  • If you have not run [bold]repograph trace install[/], do that first.\n"
            "  • After install, traces are created when Python runs with tracing active — "
            "typically [bold]pytest[/] at the repo root (conftest), or use "
            "[bold]repograph trace install --mode sitecustomize[/] to trace all "
            "`python` processes from this tree."
        )
        return

    total_lines = 0
    total_size_bytes = 0
    rows: list[dict[str, int | str]] = []
    for f in files:
        try:
            lines = sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
        except OSError:
            lines = 0
        size_bytes = 0
        try:
            size_bytes = f.stat().st_size
        except OSError:
            size_bytes = 0
        total_lines += lines
        total_size_bytes += size_bytes
        rows.append({"name": f.name, "records": int(lines), "size_bytes": int(size_bytes)})

    if as_json:
        import json as _json

        typer.echo(
            _json.dumps(
                {
                    "trace_files": rows,
                    "trace_file_count": len(rows),
                    "total_records": total_lines,
                    "total_size_bytes": total_size_bytes,
                },
                indent=2,
            )
        )
        return

    for r in rows:
        rec = r["records"] if isinstance(r.get("records"), int) else 0
        console.print(f"  [cyan]{r['name']}[/]  {rec:,} records")

    console.print(f"\n[green]{len(files)} trace file(s), {total_lines:,} total records.[/]")
    console.print(
        "Run [bold]repograph sync[/] to merge traces into the graph (updates dead-code / "
        "[bold]runtime_*[/] fields). [bold]repograph report full[/] only reads the existing index — "
        "it does not consume new JSONL by itself."
    )


@trace_app.command("report")
def trace_report(
    path: Optional[str] = typer.Argument(None),
    top: int = typer.Option(20, "--top", "-n", help="Number of top-called functions to show."),
    json_out: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Show dynamic overlay findings from collected traces.

    Reads trace files from .repograph/runtime/ and reports:
    - Most frequently called functions
    - Functions marked dead statically but observed live at runtime
    - Dynamic call edges not visible to the static graph
    """
    import json as _json
    from repograph.config import get_repo_root, repograph_dir as rg_dir_fn
    from repograph.exceptions import RepographNotFoundError
    from repograph.runtime.trace_format import trace_dir, collect_trace_files
    from repograph.runtime.overlay import overlay_traces

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        console.print("[red]Error:[/] Not initialized. Run [bold]repograph init[/] first.")
        raise typer.Exit(1)
    rg_dir = rg_dir_fn(root)
    td = trace_dir(rg_dir)

    if not collect_trace_files(rg_dir):
        console.print(
            "[yellow]No trace files.[/] Run [bold]pytest[/] after "
            "[bold]repograph trace install[/], or use [bold]--mode sitecustomize[/]."
        )
        return

    # Open the graph store for overlay
    from repograph.config import db_path, is_initialized
    if not is_initialized(root):
        console.print("[red]Not initialized.[/] Run [bold]repograph sync[/] first.")
        raise typer.Exit(1)

    from repograph.graph_store.store import GraphStore
    store = GraphStore(db_path(root))
    store.initialize_schema()

    persisted = 0
    try:
        from repograph.runtime.overlay import persist_runtime_overlay_to_store

        report = overlay_traces(td, store, repo_root=root)
        persisted = persist_runtime_overlay_to_store(store, report)
    finally:
        store.close()

    if json_out:
        console.print(_json.dumps(report, indent=2))
        return

    console.print(f"\n[bold]Dynamic Overlay Report[/]")
    console.print(
        f"  Trace files:      {report['trace_file_count']}\n"
        f"  Observed fns:     {report['observed_fn_count']}\n"
        f"  New dynamic edges:{report['new_edge_count']}\n"
        f"  Trace calls:      {report.get('trace_call_records', 0)}\n"
        f"  Resolved calls:   {report.get('resolved_trace_calls', 0)}\n"
        f"  Unresolved calls: {report.get('unresolved_trace_calls', 0)}\n"
        f"  Persisted to DB:  {persisted} function(s) (runtime_observed + dead flags cleared)\n"
    )

    if report["top_calls"]:
        console.print("[bold]Top called functions:[/]")
        for fn, count in report["top_calls"][:top]:
            console.print(f"  {count:6,}×  {fn}")
        console.print()

    static_dead_live = [
        f for f in report["findings"]
        if f.get("kind") == "observed_live_but_static_dead"
    ]
    if static_dead_live:
        console.print(f"[bold yellow]⚠  {len(static_dead_live)} function(s) static-dead but observed live:[/]")
        for f in static_dead_live[:10]:
            console.print(f"  {f.get('function_id', '?')}")
        console.print()

    new_edges = [f for f in report["findings"] if f.get("kind") == "dynamic_call_edge"]
    if new_edges:
        console.print(f"[bold blue]  {len(new_edges)} dynamic edge(s) not in static graph:[/]")
        for e in new_edges[:10]:
            console.print(f"  {e['caller']} → {e['callee']}  ({e['file']}:{e['line']})")
    unresolved = report.get("unresolved_examples") or []
    if unresolved:
        console.print(f"[bold yellow]Unresolved trace symbols ({len(unresolved)} shown):[/]")
        for u in unresolved[:10]:
            console.print(f"  {u}")


@trace_app.command("clear")
def trace_clear(
    path: Optional[str] = typer.Argument(None),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete all collected trace files from .repograph/runtime/."""
    import shutil
    from repograph.config import get_repo_root, repograph_dir as rg_dir_fn
    from repograph.exceptions import RepographNotFoundError
    from repograph.runtime.trace_format import trace_dir

    try:
        root = get_repo_root(path)
    except RepographNotFoundError:
        console.print("[red]Error:[/] Not initialized. Run [bold]repograph init[/] first.")
        raise typer.Exit(1)
    td = trace_dir(rg_dir_fn(root))

    if not td.exists():
        console.print("[yellow]No traces to clear.[/]")
        return
    if not yes:
        typer.confirm(f"Delete all traces in {td}?", abort=True)
    shutil.rmtree(td)
    console.print(f"[green]Cleared {td}[/]")



if __name__ == "__main__":
    app()
