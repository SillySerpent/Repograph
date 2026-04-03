"""Sync, init, status, watch, clean, and test commands."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.panel import Panel

from repograph.runtime.orchestration import (
    describe_attach_outcome,
    describe_attach_policy,
    describe_live_target,
    describe_runtime_mode,
    describe_runtime_reason,
    describe_runtime_resolution,
)
from repograph.runtime.session import RuntimeAttachApproval, RuntimeAttachDecision
from repograph.surfaces.cli.app import app, console, _cli_command_session, _get_root_and_store
from repograph.surfaces.cli.output import _print_stats


# ---------------------------------------------------------------------------
# repograph init
# ---------------------------------------------------------------------------

@app.command()
def init(
    path: str | None = typer.Argument(None, help="Repo root (default: current dir)"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-initialize even if already done"),
):
    """Initialize RepoGraph in a repository."""
    from repograph.settings import ensure_settings_file, repograph_dir, is_initialized
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
        f.write("graph.db\ngraph.db.wal\nlogs/\nmeta/\nmirror/\npathways/\nruntime/\nsettings.json\n")

    # Write the self-describing settings document so the settings surface is
    # tangible without letting metadata override YAML/default values.
    ensure_settings_file(root)

    # Write placeholder repograph.index.yaml as a power-user reference.
    # By default every setting is commented out — the primary settings interface
    # is `repograph config set KEY VALUE` which writes .repograph/settings.json.
    yaml_path = os.path.join(rg_dir, "repograph.index.yaml")
    if not os.path.exists(yaml_path):
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(
                "# repograph.index.yaml — Optional power-user overrides\n"
                "#\n"
                "# These settings are a SECONDARY source.  The primary way to configure\n"
                "# RepoGraph is via the CLI:\n"
                "#\n"
                "#   repograph config set KEY VALUE     (persists to settings.json)\n"
                "#   repograph config list              (show current effective settings)\n"
                "#\n"
                "# Values in this file only take effect when uncommented.  They are\n"
                "# overridden by settings.json if both are present.\n"
                "#\n"
                "# exclude_dirs:\n"
                "#   - vendor      # top-level directory names to skip during file walk\n"
                "#   - dist\n"
                "#\n"
                "# sync_test_command:   # override auto-detected test command\n"
                "#   - python\n"
                "#   - -m\n"
                "#   - pytest\n"
                "#   - tests\n"
                "#\n"
                "# doc_symbols_flag_unknown: false\n"
                "# disable_auto_excludes: false\n"
            )

    console.print(Panel(
        f"[green]✓ Initialized RepoGraph[/] at [bold]{rg_dir}[/]\n\n"
        "Run [bold]repograph sync[/] to index the repository.\n"
        "Run [bold]repograph config list[/] to see current settings.\n"
        "Run [bold]repograph config describe[/] to inspect the full settings schema.",
        title="repograph init",
    ))


# ---------------------------------------------------------------------------
# repograph sync
# ---------------------------------------------------------------------------


def _confirm_live_attach(decision: RuntimeAttachDecision) -> RuntimeAttachApproval:
    """Ask the operator whether RepoGraph may reuse one running live target."""
    target_label = (
        describe_live_target(decision.target)
        if decision.target is not None
        else "detected live target"
    )
    attach_reason = describe_runtime_reason(decision.reason)
    console.print(f"[cyan]Live attach candidate detected:[/] {target_label}")
    if attach_reason:
        console.print(f"[dim]{attach_reason}[/]")
    try:
        approved = typer.confirm(
            "Attach dynamic analysis to this running server?",
            default=False,
        )
    except (EOFError, OSError):
        console.print(
            "[yellow]Live attach candidate detected but no interactive terminal is "
            "available; falling back safely.[/]"
        )
        return RuntimeAttachApproval(
            outcome="declined",
            reason="live_attach_prompt_unavailable",
        )
    if approved:
        return RuntimeAttachApproval(
            outcome="approved",
            reason="operator_approved_live_attach",
        )
    return RuntimeAttachApproval(
        outcome="declined",
        reason="live_attach_declined",
    )


def _repo_venv_python(root: str) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return Path(root) / ".venv" / scripts_dir / executable


def _repo_venv_activate_hint(root: str) -> str:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    activate = "activate.bat" if os.name == "nt" else "activate"
    path = Path(root) / ".venv" / scripts_dir / activate
    if os.name == "nt":
        return str(path)
    return f"source {path}"


def _print_repo_venv_mismatch_warning(root: str) -> None:
    """Warn when a repo-local venv exists but this CLI is using another Python.

    Full sync uses ``sys.executable`` to choose the traced test interpreter, so
    a launcher/interpreter mismatch materially changes dynamic-analysis
    behavior. This warning keeps that fact visible without changing the active
    interpreter behind the operator's back.
    """
    repo_python = _repo_venv_python(root)
    if not repo_python.is_file():
        return

    expected = repo_python.resolve()
    current = Path(sys.executable).resolve()
    if current == expected:
        return

    console.print(
        "[yellow]Repo-local .venv detected, but this repograph process is using a "
        f"different interpreter:[/] {current}"
    )
    console.print(
        "[dim]Dynamic analysis will use the current interpreter unless you run "
        f"from the repo venv. Preferred paths: ./run.sh ... or {_repo_venv_activate_hint(root)}[/]"
    )

@app.command()
def sync(
    path: str | None = typer.Argument(
        None,
        help='Repository root (default: current directory). Do not pass "full" here — use --full.',
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="Force a full rebuild; automatic runtime analysis follows the auto_dynamic_analysis setting.",
    ),
    static_only: bool = typer.Option(
        False,
        "--static-only",
        help="Force a full static-only rebuild with no automatic test execution. Implies --full.",
    ),
    embeddings: bool | None = typer.Option(
        None,
        "--embeddings/--no-embeddings",
        help="Override the persisted embeddings setting for this sync only.",
    ),
    include_git: bool | None = typer.Option(
        None,
        "--git/--no-git",
        help="Override the persisted git-coupling setting for this sync only.",
    ),
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

    Use ``repograph sync --full`` for the canonical one-shot full rebuild
    (static index + automatic dynamic analysis when test discovery succeeds).
    Use ``repograph sync --static-only`` for a full static rebuild with no test run.

    A bare word ``full`` is not a flag — if you run ``repograph sync full``, Typer
    treats ``full`` as the repo *path* (usually wrong). We map that common mistake
    to ``--full`` on cwd.
    """
    from repograph.settings import (
        ensure_settings_file,
        is_initialized,
        repograph_dir,
        resolve_runtime_settings,
    )
    from repograph.pipeline.runner import (
        RunConfig,
        run_full_pipeline,
        run_full_pipeline_with_runtime_overlay,
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

    if static_only:
        full = True

    if not is_initialized(root) and not full:
        console.print("[yellow]Not yet indexed. Running full sync...[/]")
        full = True

    os.makedirs(rg_dir, exist_ok=True)
    os.makedirs(os.path.join(rg_dir, "meta"), exist_ok=True)
    # Keep the self-describing settings surface current during the normal sync
    # bootstrap path too, not only after an explicit `repograph init`.
    ensure_settings_file(root)
    _print_repo_venv_mismatch_warning(root)

    resolved = resolve_runtime_settings(
        root,
        include_git=include_git,
        include_embeddings=embeddings,
    )
    config = RunConfig(
        repo_root=root,
        repograph_dir=rg_dir,
        include_git=resolved.include_git,
        include_embeddings=resolved.include_embeddings,
        full=full,
        strict=strict,
        continue_on_error=continue_on_error,
        include_tests_config_registry=include_tests_config_registry,
        max_context_tokens=resolved.max_context_tokens,
        min_community_size=resolved.min_community_size,
        git_days=resolved.git_days,
        allow_dynamic_inputs=not static_only,
        runtime_attach_policy=resolved.settings.sync_runtime_attach_policy,
        runtime_attach_approval_resolver=_confirm_live_attach,
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

    if full:
        if static_only:
            console.print("[cyan]Running full static-only pipeline...[/]")
            stats = run_full_pipeline(config)
        elif resolved.auto_dynamic_analysis:
            console.print("[cyan]Running full pipeline with automatic runtime overlay...[/]")
            stats = run_full_pipeline_with_runtime_overlay(config)
        else:
            console.print("[cyan]Running full static pipeline (automatic dynamic analysis disabled by settings)...[/]")
            stats = run_full_pipeline(config)
    else:
        differ = IncrementalDiff(rg_dir)
        if differ.is_first_run():
            console.print("[cyan]First run — performing full sync...[/]")
            if resolved.auto_dynamic_analysis:
                stats = run_full_pipeline_with_runtime_overlay(config)
            else:
                stats = run_full_pipeline(config)
        else:
            console.print("[cyan]Running incremental sync...[/]")
            stats = run_incremental_pipeline(config)

    _print_stats(stats)


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
    path: str | None = typer.Argument(None, help="Repository root (default: current directory)."),
    extra_args: list[str] | None = typer.Argument(None, help="Extra pytest args passed through as-is."),
) -> None:
    """Run predefined test-suite matrix profiles.

    Profiles use pytest markers and test paths, so they automatically include
    new tests that match those selectors.
    """
    from repograph.settings import get_repo_root
    from repograph.exceptions import RepographNotFoundError

    catalog = _test_profiles_catalog()
    if list_profiles:
        from rich.table import Table
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
def status(path: str | None = typer.Argument(None)):
    """Show index health: node counts, stale artifacts, last sync time."""
    with _cli_command_session(path, command="status"):
        root, store = _get_root_and_store(path)
        from repograph.settings import repograph_dir
        from repograph.docs.staleness import StalenessTracker

        try:
            stats = store.get_stats()
            staleness = StalenessTracker(repograph_dir(root))
            stale = staleness.get_all_stale()

            from rich.table import Table
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
                dyn = health.get("dynamic_analysis") or {}
                if dyn:
                    resolution = describe_runtime_resolution(str(dyn.get("resolution") or ""))
                    mode = describe_runtime_mode(str(dyn.get("mode") or "none"))
                    executed_mode = describe_runtime_mode(
                        str(dyn.get("executed_mode") or dyn.get("mode") or "none")
                    )
                    traces = int(dyn.get("trace_file_count") or 0)
                    persisted = int(dyn.get("overlay_persisted_functions") or 0)
                    if dyn.get("requested") and not dyn.get("executed"):
                        console.print(
                            "[yellow]Dynamic analysis skipped:[/] "
                            f"{describe_runtime_reason(str(dyn.get('skipped_reason') or '')) or dyn.get('skipped_reason') or 'unspecified'} "
                            f"(mode={mode}, selection={resolution})"
                        )
                    elif dyn.get("inputs_present") and not any((
                        dyn.get("runtime_overlay_applied"),
                        dyn.get("coverage_overlay_applied"),
                    )):
                        console.print(
                            "[yellow]Dynamic inputs present but not applied:[/] "
                            f"traces={traces} coverage={bool(dyn.get('coverage_json_present'))}"
                        )
                    else:
                        console.print(
                            f"[dim]Dynamic[/] mode={executed_mode} selected={mode} selection={resolution} "
                            f"traces={traces} runtime_observed={persisted} "
                            f"pytest_exit={dyn.get('pytest_exit_code')}"
                        )
                    attach_outcome = str(dyn.get("attach_outcome") or "not_applicable")
                    if attach_outcome != "not_applicable":
                        attach_target = dyn.get("attach_target") or {}
                        attach_reason = describe_runtime_reason(str(dyn.get("attach_reason") or ""))
                        attach_policy = describe_attach_policy(
                            str(dyn.get("attach_policy") or "prompt")
                        )
                        attach_approval = str(
                            dyn.get("attach_approval_outcome") or "not_applicable"
                        )
                        attach_approval_reason = describe_runtime_reason(
                            str(dyn.get("attach_approval_reason") or "")
                        )
                        attach_line = (
                            f"[dim]Attach[/] status={describe_attach_outcome(attach_outcome)}"
                        )
                        attach_line += f" policy={attach_policy}"
                        if attach_target:
                            attach_line += f" target={describe_live_target(attach_target)}"
                        if attach_reason:
                            attach_line += f" detail={attach_reason}"
                        if attach_approval != "not_applicable":
                            attach_line += f" approval={attach_approval}"
                        if attach_approval_reason:
                            attach_line += f" approval_detail={attach_approval_reason}"
                        console.print(attach_line)
                    fallback_execution = dyn.get("fallback_execution") or {}
                    if fallback_execution:
                        fallback_line = (
                            "[dim]Fallback[/] "
                            f"from={describe_runtime_mode(str(fallback_execution.get('from_mode') or 'none'))} "
                            f"to={describe_runtime_mode(str(fallback_execution.get('to_mode') or 'none'))} "
                            f"status={'ok' if fallback_execution.get('succeeded') else 'failed'}"
                        )
                        fallback_detail = str(fallback_execution.get("reason") or "").strip()
                        if fallback_detail:
                            fallback_line += f" detail={fallback_detail}"
                        console.print(fallback_line)

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
        finally:
            store.close()


# ---------------------------------------------------------------------------
# repograph watch
# ---------------------------------------------------------------------------

@app.command()
def watch(
    path: str | None = typer.Argument(None),
    no_git: bool = typer.Option(False, "--no-git"),
    strict: bool = typer.Option(False, "--strict", help="Same as sync --strict for incremental rebuilds."),
):
    """Watch mode: re-sync on file changes (debounced 200 ms).

    Only one incremental sync runs at a time; further edits queue a single
    follow-up sync after the current run finishes.
    """
    from repograph.settings import repograph_dir
    from repograph.pipeline.runner import RunConfig
    from repograph.interactive.watch import FileWatcherDaemon

    root = os.path.abspath(path or os.getcwd())

    rg_dir = repograph_dir(root)
    config = RunConfig(
        repo_root=root, repograph_dir=rg_dir, include_git=not no_git, strict=strict,
    )

    try:
        daemon = FileWatcherDaemon(config, repo_root=root)
    except ImportError:
        console.print("[red]watchdog not installed. Run: pip install watchdog[/]")
        raise typer.Exit(1)

    console.print(f"[green]Watching[/] {root} for changes (200 ms debounce). Press Ctrl+C to stop.")
    daemon.run_until_interrupted()


# ---------------------------------------------------------------------------
# repograph clean
# ---------------------------------------------------------------------------

@app.command()
def clean(
    path: str | None = typer.Argument(None),
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
    import shutil

    from repograph.settings import get_repo_root, repograph_dir
    from repograph.exceptions import RepographNotFoundError
    from repograph.utils.dev_clean import clean_development_artifacts, summarize_removed

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
