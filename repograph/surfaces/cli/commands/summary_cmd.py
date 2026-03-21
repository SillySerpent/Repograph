"""Summary CLI command."""
from __future__ import annotations

import json as _json
import os

import typer
from rich import box as _box
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from repograph.surfaces.cli.app import app, console, _get_service


@app.command()
def summary(
    path: str | None = typer.Argument(None),
    as_json: bool = typer.Option(False, "--json", help="Output as machine-readable JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show entry-point score breakdowns."),
):
    """Compact repo overview: trust, top entry surfaces, top flows, risks, and hotspots.

    Ideal as a first prompt injection when entering an unfamiliar codebase.
    """
    from repograph.plugins.static_analyzers.pathways.scorer import ScoreBreakdown
    from repograph.runtime.orchestration import (
        describe_attach_outcome,
        describe_attach_policy,
        describe_live_target,
        describe_runtime_mode,
        describe_runtime_reason,
    )
    from repograph.surfaces.cli.summary_helpers import build_summary_payload

    root, rg = _get_service(path)
    with rg:
        report_data = rg.full_report(
            max_pathways=5,
            max_dead=5,
            entry_point_limit=5,
            max_config_keys=5,
            max_communities=5,
        )
    data = build_summary_payload(root, report_data)

    if as_json:
        import sys

        sys.stdout.write(_json.dumps(data, indent=2, ensure_ascii=False))
        sys.stdout.write("\n")
        return

    repo_name = data.get("repo", os.path.basename(root))
    purpose = data.get("purpose", "")
    stats = data.get("stats", {})
    trust = data.get("trust", {})
    health = data.get("health", {})
    analysis_readiness = trust.get("analysis_readiness", {}) or {}
    dynamic = data.get("dynamic_analysis", {}) or {}

    trust_status = trust.get("status", "caution")
    trust_color = "green" if trust_status == "high" else "yellow" if trust_status == "caution" else "red"
    sync_status = trust.get("sync_status", health.get("status", "unknown"))
    sync_color = "green" if sync_status == "ok" else "yellow" if sync_status == "degraded" else "red"
    sync_mode = trust.get("sync_mode", health.get("sync_mode", "?"))

    console.print()
    header_body = Text()
    if purpose:
        header_body.append(purpose[:320] + "\n\n", style="")
    header_body.append(
        f"{stats.get('files', 0)} files  ·  {stats.get('functions', 0)} functions  "
        f"·  {stats.get('classes', 0)} classes  ·  {health.get('call_edges_total', '?')} call edges  "
        f"·  {stats.get('pathways', 0)} pathways  ·  {stats.get('communities', 0)} communities",
        style="dim",
    )
    header_body.append("\n\nSync: ", style="dim")
    header_body.append(f"● {sync_status}", style=sync_color + " bold")
    header_body.append(f"  ({sync_mode})", style="dim")
    header_body.append("\nTrust: ", style="dim")
    header_body.append(trust_status, style=trust_color + " bold")
    console.print(Panel(
        header_body,
        title=f"[bold cyan]{repo_name}[/]",
        border_style="cyan",
        padding=(0, 2),
    ))
    console.print()

    console.print(Rule("[bold]Trust[/]", style="dim", align="left"))
    console.print(
        "  "
        f"[bold]Runtime overlay:[/] {'yes' if analysis_readiness.get('runtime_overlay_applied') else 'no'}"
        f"  ·  [bold]Coverage overlay:[/] {'yes' if analysis_readiness.get('coverage_overlay_applied') else 'no'}"
        f"  ·  [bold]Pathway contexts:[/] {'yes' if analysis_readiness.get('pathway_contexts_generated') else 'no'}"
    )
    if dynamic:
        requested = bool(dynamic.get("requested"))
        executed = bool(dynamic.get("executed"))
        trace_files = int(dynamic.get("trace_file_count") or 0)
        console.print(
            "  "
            f"[bold]Dynamic analysis:[/] requested={'yes' if requested else 'no'}"
            f"  ·  executed={'yes' if executed else 'no'}"
            f"  ·  traces={trace_files}"
        )
        selected_mode = describe_runtime_mode(str(dynamic.get("mode") or "none"))
        executed_mode = describe_runtime_mode(
            str(dynamic.get("executed_mode") or dynamic.get("mode") or "none")
        )
        console.print(
            "  "
            f"[bold]Executed mode:[/] {executed_mode}"
            f"  ·  [bold]Selected mode:[/] {selected_mode}"
        )
        attach_outcome = str(dynamic.get("attach_outcome") or "not_applicable")
        if attach_outcome != "not_applicable":
            attach_reason = describe_runtime_reason(str(dynamic.get("attach_reason") or ""))
            attach_policy = describe_attach_policy(str(dynamic.get("attach_policy") or "prompt"))
            attach_approval = str(dynamic.get("attach_approval_outcome") or "not_applicable")
            attach_approval_reason = describe_runtime_reason(
                str(dynamic.get("attach_approval_reason") or "")
            )
            attach_target = dynamic.get("attach_target") or {}
            attach_line = (
                "  "
                f"[bold]Attach:[/] {describe_attach_outcome(attach_outcome)}"
            )
            attach_line += f"  ·  [bold]Policy:[/] {attach_policy}"
            if attach_target:
                attach_line += (
                    f"  ·  [bold]Target:[/] {describe_live_target(attach_target)}"
                )
            if attach_reason:
                attach_line += f"  ·  [bold]Detail:[/] {attach_reason}"
            if attach_approval != "not_applicable":
                attach_line += f"  ·  [bold]Approval:[/] {attach_approval}"
            if attach_approval_reason:
                attach_line += f"  ·  [bold]Approval detail:[/] {attach_approval_reason}"
            console.print(attach_line)
        live_target_count = int(dynamic.get("detected_live_target_count") or 0)
        if live_target_count:
            fallback_reason = (
                describe_runtime_reason(str(dynamic.get("fallback_reason") or ""))
                or "none"
            )
            console.print(
                "  "
                f"[bold]Live targets:[/] {live_target_count}"
                f"  ·  [bold]Fallback:[/] {fallback_reason}"
            )
        fallback_execution = dynamic.get("fallback_execution") or {}
        if fallback_execution:
            console.print(
                "  "
                f"[bold]Fallback execution:[/] "
                f"{describe_runtime_mode(str(fallback_execution.get('from_mode') or 'none'))}"
                " -> "
                f"{describe_runtime_mode(str(fallback_execution.get('to_mode') or 'none'))}"
                f"  ·  {'ok' if fallback_execution.get('succeeded') else 'failed'}"
            )
            fallback_detail = str(fallback_execution.get("reason") or "").strip()
            if fallback_detail:
                console.print(f"  [bold]Fallback detail:[/] {fallback_detail}")
        scenario_actions = dynamic.get("scenario_actions") or {}
        if scenario_actions:
            console.print(
                "  "
                f"[bold]Scenarios:[/] {int(scenario_actions.get('successful_count') or 0)} ok"
                f"  ·  {int(scenario_actions.get('failed_count') or 0)} failed"
                f"  ·  {int(scenario_actions.get('executed_count') or 0)} executed"
            )
            scenario_driver = scenario_actions.get("driver") or {}
            if scenario_driver:
                console.print(
                    "  "
                    f"[bold]Scenario driver:[/] {'ok' if scenario_driver.get('ok') else 'failed'}"
                    f"  ·  [bold]Exit:[/] {scenario_driver.get('exit_code')!r}"
                )
    for warning in trust.get("warnings", []):
        console.print(f"  [yellow]▲[/] {warning}")
    if not trust.get("warnings"):
        console.print("  [green]No active trust warnings in the current capped snapshot.[/]")
    console.print()

    eps = data.get("top_entry_points", [])
    if eps:
        console.print(Rule("[bold]Top Entry Points[/]", style="dim", align="left"))
        ep_table = Table(
            show_header=True, header_style="dim",
            box=_box.SIMPLE, padding=(0, 1),
        )
        ep_table.add_column("Score", style="cyan", justify="right", min_width=6)
        ep_table.add_column("Function", style="bold")
        ep_table.add_column("File", style="dim", max_width=50)
        ep_table.add_column("Callers / Callees", justify="right", style="dim", min_width=14)
        if verbose:
            ep_table.add_column("Score Breakdown", style="dim")
        for ep in eps:
            caller_count = ep.get("callers")
            callee_count = ep.get("callees")
            if verbose:
                if ep.get("entry_score_base") is not None:
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
                        final_score=float(ep["score"]),
                        base_score=float(ep["entry_score_base"]),
                        callees_count=int(ep.get("callees") or 0),
                        callers_count=int(ep.get("callers") or 0),
                        multipliers=pairs,
                    )
                    explain = bd.explain()
                else:
                    explain = "score breakdown unavailable"
                ep_table.add_row(
                    f"{ep['score']:.1f}",
                    ep["name"],
                    ep["file"],
                    f"{caller_count if caller_count is not None else '?'} ↑  {callee_count if callee_count is not None else '?'} ↓",
                    explain,
                )
            else:
                ep_table.add_row(
                    f"{ep['score']:.1f}",
                    ep["name"],
                    ep["file"],
                    f"{caller_count if caller_count is not None else '?'} ↑  {callee_count if callee_count is not None else '?'} ↓",
                )
        console.print(ep_table)
        console.print()

    top_ps = data.get("top_pathways", [])
    if top_ps:
        console.print(Rule("[bold]Top Pathways[/]  (by importance)", style="dim", align="left"))
        p_table = Table(
            show_header=True, header_style="dim",
            box=_box.SIMPLE, padding=(0, 1),
        )
        p_table.add_column("Imp", style="cyan", justify="right", min_width=5)
        p_table.add_column("Name", style="bold")
        p_table.add_column("Entry", style="dim", max_width=30)
        p_table.add_column("Steps", justify="right", style="dim")
        p_table.add_column("Conf", justify="right", style="dim")
        for pathway in top_ps:
            conf = pathway.get("confidence", 0.0)
            conf_color = "green" if conf >= 0.8 else "yellow" if conf >= 0.5 else "red"
            p_table.add_row(
                f"{pathway.get('importance', 0.0):.1f}",
                pathway["name"],
                pathway.get("entry", ""),
                str(pathway.get("steps", 0)),
                f"[{conf_color}]{conf:.2f}[/]",
            )
        console.print(p_table)
        console.print()

    console.print(Rule("[bold]Major Risks[/]", style="dim", align="left"))
    risks = data.get("major_risks", [])
    if risks:
        for risk in risks:
            sev = risk.get("severity", "low")
            color = "red" if sev == "high" else "yellow" if sev == "medium" else "dim"
            console.print(
                f"  [{color}]● {risk.get('kind', 'risk')}[/] "
                f"{risk.get('summary', '')}"
            )
    else:
        console.print("  [green]No high-signal risks surfaced in the compact summary.[/]")
    console.print()

    hotspots = data.get("structural_hotspots", [])
    if hotspots:
        console.print(Rule("[bold]Structural Hotspots[/]", style="dim", align="left"))
        hotspot_table = Table(
            show_header=True,
            header_style="dim",
            box=_box.SIMPLE,
            padding=(0, 1),
        )
        hotspot_table.add_column("Module", style="cyan", min_width=20)
        hotspot_table.add_column("Role / Notes", style="white", max_width=44)
        hotspot_table.add_column("Fns", justify="right", style="dim")
        hotspot_table.add_column("Cls", justify="right", style="dim")
        hotspot_table.add_column("Issues", justify="right")
        for hotspot in hotspots:
            issue_count = int(hotspot.get("dead_code_count") or 0) + int(hotspot.get("duplicate_count") or 0)
            hotspot_table.add_row(
                hotspot.get("module", ""),
                hotspot.get("summary", "") or "No summary available.",
                str(hotspot.get("function_count", 0)),
                str(hotspot.get("class_count", 0)),
                str(issue_count) if issue_count else "—",
            )
        console.print(hotspot_table)
        console.print()

    console.print(
        "[dim]  Run [bold]repograph report[/] for the full structured report with dead code, "
        "coverage, invariants, config, and communities.[/]\n"
    )
