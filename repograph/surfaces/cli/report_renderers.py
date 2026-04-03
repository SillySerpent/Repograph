"""Human-readable renderers for full RepoGraph reports."""
from __future__ import annotations

import os
import re

from rich import box as _box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from repograph.runtime.orchestration import (
    describe_attach_outcome,
    describe_attach_policy,
    describe_live_target,
    describe_runtime_mode,
    describe_runtime_reason,
    describe_runtime_resolution,
    describe_trace_collection,
)


def _ellipsize(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].strip()
    return (cut or text[:limit]).rstrip(",;:") + "…"


def _first_sentence(text: str, *, max_len: int = 220) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    match = re.search(r"(?<=[.!?])\s", text)
    sentence = text[: match.start() + 1] if match else text
    return _ellipsize(sentence, max_len)


def _tail_path(path: str, keep: int = 2) -> str:
    if not path:
        return ""
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    if not parts:
        return ""
    return "/".join(parts[-keep:])


def _module_purpose(module: dict) -> str:
    key_classes = [name for name in (module.get("key_classes") or []) if name]
    summary = _first_sentence(module.get("summary", ""), max_len=68)
    summary_looks_like_function_doc = summary.lower().startswith((
        "return ",
        "create ",
        "compute ",
        "collect ",
        "walk ",
        "read ",
        "write ",
        "add ",
        "detect ",
        "turn ",
        "generate ",
        "load ",
        "check ",
        "build ",
        "parse ",
        "install ",
        "open ",
        "ensure ",
        "satisfy ",
    ))
    if summary and not (summary_looks_like_function_doc and key_classes):
        return summary
    if key_classes:
        text = ", ".join(key_classes[:3])
        if len(key_classes) > 3:
            text += f" +{len(key_classes) - 3}"
        return f"Key types: {text}"
    if module.get("category") == "tooling":
        return "Tests, docs, scripts, or other support code."
    return "No summary available."


def _module_sort_key(module: dict) -> tuple:
    support_only = (
        module.get("category") == "tooling"
        or (
            module.get("function_count", 0) == 0
            and module.get("class_count", 0) == 0
            and module.get("dead_code_count", 0) == 0
            and module.get("duplicate_count", 0) == 0
        )
    )
    issue_weight = module.get("dead_code_count", 0) + module.get("duplicate_count", 0)
    return (
        1 if support_only else 0,
        -issue_weight,
        -module.get("function_count", 0),
        -module.get("class_count", 0),
        module.get("display", ""),
    )


def _extract_pathway_files_from_context(doc: str) -> list[str]:
    files: list[str] = []
    in_files = False
    for raw_line in (doc or "").splitlines():
        line = raw_line.strip()
        if not line:
            if in_files:
                break
            continue
        if line == "PARTICIPATING FILES (BFS discovery order)":
            in_files = True
            continue
        if not in_files:
            continue
        if line.startswith("["):
            continue
        match = re.match(r"\d+\.\s+(.*)", line)
        if not match:
            break
        files.append(match.group(1).strip())
    return files


def _short_step_name(step: dict) -> str:
    name = (
        step.get("qualified_name")
        or step.get("function_name")
        or step.get("name")
        or "?"
    )
    return _ellipsize(str(name), 28)


def _pathway_flow_preview(steps: list[dict], *, limit: int = 4) -> str:
    if not steps:
        return ""
    labels = [_short_step_name(step) for step in steps[:limit]]
    preview = " -> ".join(labels)
    if len(steps) > limit:
        preview += f" -> +{len(steps) - limit} more"
    return preview


def _pathway_files_preview(pathway: dict, steps: list[dict], *, limit: int = 4) -> str:
    files = list(
        dict.fromkeys(
            step.get("file_path", "")
            for step in steps
            if step.get("file_path")
        )
    )
    if not files:
        files = _extract_pathway_files_from_context(pathway.get("context_doc", ""))
    pretty = [_tail_path(path, keep=2) for path in files[:limit] if path]
    if len(files) > limit:
        pretty.append(f"+{len(files) - limit} more")
    return ", ".join(pretty)


def _sec(console: Console, title: str) -> None:
    console.print(Rule(f"[bold white]{title}[/]", style="bright_cyan", align="left"))


def _table(**kwargs) -> Table:
    options = {
        "show_header": True,
        "header_style": "bold white",
        "box": _box.SQUARE,
        "show_lines": True,
        "padding": (0, 1),
        "border_style": "white",
    }
    options.update(kwargs)
    return Table(**options)


def _visible(rows: list[dict], default_limit: int, *, show_all: bool) -> list[dict]:
    return rows if show_all else rows[:default_limit]


def render_full_report(
    console: Console,
    data: dict,
    *,
    pathway_step_map: dict[str, list[dict]],
    full_requested: bool,
    show_all: bool = False,
) -> None:
    """Render the human-readable full report from a prepared payload."""
    repo_name = os.path.basename(data["meta"]["repo_path"])
    health = data.get("health", {})
    h_status = health.get("status", "?")
    h_color = "green" if h_status == "ok" else "yellow" if h_status == "degraded" else "red"
    sync_mode = health.get("sync_mode", "?")
    last_sync = health.get("generated_at", "?")

    dyn = health.get("dynamic_analysis") or {}
    dyn_line = ""
    if dyn:
        mode = str(dyn.get("mode") or "").strip()
        mode_label = describe_runtime_mode(mode or "none")
        resolution_label = describe_runtime_resolution(str(dyn.get("resolution") or ""))
        n_files = int(dyn.get("trace_file_count") or 0)
        n_fns = int(dyn.get("overlay_persisted_functions") or 0)
        coverage_present = bool(dyn.get("coverage_json_present"))
        dyn_line += f"\n  [cyan]Dynamic mode:[/] {mode_label}"
        if dyn.get("resolution"):
            dyn_line += f"\n  [cyan]Selection:[/] {resolution_label}"
        if dyn.get("requested") and not dyn.get("executed"):
            skipped = describe_runtime_reason(str(dyn.get("skipped_reason") or ""))
            dyn_line += (
                "\n  [yellow]Dynamic analysis skipped:[/] "
                f"{skipped or dyn.get('skipped_reason') or 'unspecified'}"
            )
        elif dyn.get("inputs_present") and not any((
            dyn.get("runtime_overlay_applied"),
            dyn.get("coverage_overlay_applied"),
        )):
            dyn_line += (
                "\n  [yellow]Dynamic inputs present[/] but no runtime or coverage overlay was applied"
            )
        else:
            if mode == "existing_inputs":
                parts: list[str] = []
                if n_files or n_fns:
                    parts.append(f"{n_files} trace file(s), {n_fns} observed fn(s)")
                if coverage_present:
                    parts.append("coverage.json present")
                if parts:
                    dyn_line += f"\n  [cyan]Dynamic inputs reused:[/] {'  ·  '.join(parts)}"
                else:
                    dyn_line += "\n  [cyan]Dynamic inputs reused[/]"
            elif n_files or n_fns:
                selected_mode = describe_runtime_mode(mode)
                executed_mode = describe_runtime_mode(str(dyn.get("executed_mode") or mode))
                dyn_line += (
                    f"\n  [green]Trace collection:[/] {describe_trace_collection(str(dyn.get('executed_mode') or mode))}"
                    f"\n  [green]Dynamic traces:[/] {n_files} file(s), {n_fns} observed fn(s)"
                )
                if executed_mode != selected_mode:
                    dyn_line += (
                        f"\n  [green]Executed mode:[/] {executed_mode}"
                        f"\n  [green]Selected mode:[/] {selected_mode}"
                    )
        scenario_actions = dyn.get("scenario_actions") or {}
        if scenario_actions:
            dyn_line += (
                "\n  [cyan]Scenarios:[/] "
                f"{int(scenario_actions.get('successful_count') or 0)} ok / "
                f"{int(scenario_actions.get('failed_count') or 0)} failed"
            )
            scenario_driver = scenario_actions.get("driver") or {}
            if scenario_driver:
                driver_status = "ok" if scenario_driver.get("ok") else "failed"
                dyn_line += f"\n  [cyan]Scenario driver:[/] {driver_status}"
        attach_outcome = str(dyn.get("attach_outcome") or "not_applicable")
        attach_reason = describe_runtime_reason(str(dyn.get("attach_reason") or ""))
        if attach_outcome != "not_applicable":
            attach_policy = describe_attach_policy(str(dyn.get("attach_policy") or "prompt"))
            attach_approval = str(dyn.get("attach_approval_outcome") or "not_applicable")
            attach_approval_reason = describe_runtime_reason(
                str(dyn.get("attach_approval_reason") or "")
            )
            attach_line = (
                "\n  [yellow]Attach:[/] "
                f"{describe_attach_outcome(attach_outcome)}"
            )
            attach_line += f"  [white](policy: {attach_policy})[/]"
            if attach_reason:
                attach_line += f"  [white]({attach_reason})[/]"
            if attach_approval != "not_applicable":
                attach_line += f"  [white](approval: {attach_approval})[/]"
            if attach_approval_reason:
                attach_line += f"  [white]({attach_approval_reason})[/]"
            dyn_line += attach_line
            attach_target = dyn.get("attach_target") or {}
            if attach_target:
                dyn_line += (
                    "\n  [yellow]Attach target:[/] "
                    f"{describe_live_target(attach_target)}"
                )
        live_target_count = int(dyn.get("detected_live_target_count") or 0)
        if live_target_count:
            fallback_reason = describe_runtime_reason(str(dyn.get("fallback_reason") or ""))
            live_targets = dyn.get("detected_live_targets") or []
            live_line = f"\n  [yellow]Live targets:[/] {live_target_count} detected"
            if fallback_reason and fallback_reason != attach_reason:
                live_line += f"  [white](fallback: {fallback_reason})[/]"
            dyn_line += live_line
            if live_targets:
                dyn_line += (
                    "\n  [yellow]Live target detail:[/] "
                    + "  ·  ".join(describe_live_target(target) for target in live_targets[:3])
                )
        fallback_execution = dyn.get("fallback_execution") or {}
        if fallback_execution:
            from_mode = describe_runtime_mode(str(fallback_execution.get("from_mode") or "none"))
            to_mode = describe_runtime_mode(str(fallback_execution.get("to_mode") or "none"))
            fallback_status = "ok" if fallback_execution.get("succeeded") else "failed"
            dyn_line += (
                "\n  [yellow]Fallback execution:[/] "
                f"{from_mode} -> {to_mode} ({fallback_status})"
            )
            fallback_detail = str(fallback_execution.get("reason") or "").strip()
            if fallback_detail:
                dyn_line += f"\n  [yellow]Fallback detail:[/] {fallback_detail}"

        cleanup = dyn.get("cleanup") or {}
        if cleanup:
            if cleanup.get("stopped") is True and cleanup.get("bootstrap_removed") is not False:
                cleanup_label = "clean"
            elif cleanup.get("forced_kill"):
                cleanup_label = "forced kill"
            else:
                cleanup_label = "incomplete"
            dyn_line += f"\n  [cyan]Cleanup:[/] {cleanup_label}"

    runtime_observations = data.get("runtime_observations") or {}
    n_rt = int(runtime_observations.get("functions_with_valid_runtime_revision") or 0)
    rt_line = f"\n  [green]Runtime DB:[/] {n_rt} fn(s) with current-hash trace data" if n_rt else ""

    if health.get("partial_completion"):
        rt_line += "\n  [yellow]Partial completion[/] — some pipeline phases did not finish"

    console.print()
    console.print(Panel(
        f"[bold white]Path:[/]       {data['meta']['repo_path']}\n"
        f"[bold white]Health:[/]     [{h_color}]● {h_status}[/]  [white]({sync_mode})[/]\n"
        f"[bold white]Last sync:[/]  {last_sync}"
        + dyn_line
        + rt_line,
        title=f"[bold cyan]RepoGraph Report · {repo_name}[/]",
        border_style="bright_cyan",
        padding=(0, 2),
    ))

    if data.get("purpose"):
        _sec(console, "Purpose")
        console.print(f"  {data['purpose']}\n")

    stats = data.get("stats", {})
    _sec(console, "Index")
    stat_table = _table(padding=(0, 2))
    for col in ("Files", "Functions", "Classes", "Variables", "Call Edges", "Pathways", "Communities"):
        stat_table.add_column(col, justify="right")
    stat_table.add_row(
        str(stats.get("files", 0)),
        str(stats.get("functions", 0)),
        str(stats.get("classes", 0)),
        str(stats.get("variables", 0)),
        str(health.get("call_edges_total", "?")),
        str(stats.get("pathways", 0)),
        str(stats.get("communities", 0)),
    )
    console.print(stat_table)

    modules = data.get("modules", [])
    if modules:
        _sec(console, f"Module Map  ({len(modules)} modules)")
        console.print(
            "  [white]Directory-level structural map. Each row groups files under one folder prefix; "
            "it is not an import graph or a Python-package listing.[/]"
        )
        console.print(
            "  [white]Files = production/test files. Fns and Classes count production code. "
            "Test Fns counts test-only functions in that area. Role / Notes is a short heuristic summary. "
            "Issues flags dead code or duplicates.[/]\n"
        )
        mod_table = _table()
        mod_table.add_column("Module", style="bright_cyan", min_width=22)
        mod_table.add_column("Role / Notes", max_width=44)
        mod_table.add_column("Files", justify="right", style="white", min_width=7)
        mod_table.add_column("Fns", justify="right", style="white")
        mod_table.add_column("Classes", justify="right", style="white")
        mod_table.add_column("Test Fns", justify="right", style="white")
        mod_table.add_column("Issues", justify="right", min_width=10)
        for module in sorted(modules, key=_module_sort_key):
            issues = []
            if module["dead_code_count"]:
                issues.append(f"[red]{module['dead_code_count']} dead[/]")
            if module["duplicate_count"]:
                issues.append(f"[yellow]{module['duplicate_count']} dup[/]")
            src = module.get("prod_file_count", module.get("file_count", 0))
            tst_fn = module.get("test_function_count", 0)
            mod_table.add_row(
                module["display"],
                _module_purpose(module),
                f"{src}/{module.get('test_file_count', 0)}",
                str(module["function_count"]),
                str(module.get("class_count", 0)),
                str(tst_fn) if tst_fn else "—",
                "  ".join(issues) if issues else "[green]—[/]",
            )
        console.print(mod_table)

    entry_points = data.get("entry_points", [])
    if entry_points:
        entry_rows = _visible(entry_points, 15, show_all=show_all)
        title = (
            f"Entry Points  ({len(entry_rows)} total)"
            if show_all
            else f"Top Entry Points  (showing {len(entry_rows)} of {len(entry_points)})"
        )
        _sec(console, title)
        entry_table = _table()
        entry_table.add_column("Score", style="bright_cyan", justify="right", min_width=6)
        entry_table.add_column("Function", style="bold")
        entry_table.add_column("File", style="white", max_width=50)
        entry_table.add_column("Callers / Callees", justify="right", style="white", min_width=14)
        for entry_point in entry_rows:
            callers = entry_point.get("entry_caller_count", "?")
            callees = entry_point.get("entry_callee_count", "?")
            entry_table.add_row(
                f"{entry_point.get('entry_score', 0):.1f}",
                entry_point.get("qualified_name", "?"),
                entry_point.get("file_path", ""),
                f"{callers} ↑  {callees} ↓",
            )
        console.print(entry_table)

    pathways = data.get("pathways", [])
    pathways_summary = data.get("pathways_summary", {})
    if pathways:
        total_pathways = pathways_summary.get("total", len(pathways))
        _sec(
            console,
            f"Pathways  ({len(pathways)} execution flows)"
            if show_all
            else f"Top Pathways  ({len(pathways)} of {total_pathways} execution flows)",
        )
        console.print(
            "  [white]High-importance execution flows. Each card shows what the flow does, where it starts, "
            "the first few functions in order, and the main files it touches.[/]"
        )
        console.print(
            "  [white]Use [bold]repograph pathway show <name>[/] when you want the full machine-generated "
            "context document.[/]\n"
        )
        for pathway in pathways:
            name = pathway.get("display_name") or pathway.get("name", "?")
            conf = pathway.get("confidence", 0)
            steps = pathway.get("step_count", 0)
            importance = pathway.get("importance_score") or 0
            conf_color = "green" if conf >= 0.8 else "yellow" if conf >= 0.6 else "red"
            ordered_steps = pathway_step_map.get(str(pathway.get("name") or ""), [])
            entry = pathway.get("entry_function") or (
                ordered_steps[0].get("qualified_name") if ordered_steps else "?"
            )
            summary = _first_sentence(pathway.get("description", ""), max_len=260)
            if not summary:
                summary = f"Execution flow across {steps} steps."
            flow_preview = _pathway_flow_preview(ordered_steps)
            files_preview = _pathway_files_preview(pathway, ordered_steps)
            source_label = str(pathway.get("source") or "auto_detected").replace("_", " ")
            body_lines = [summary, ""]
            body_lines.append(f"[bold white]Entry:[/] {entry}")
            if flow_preview:
                body_lines.append(f"[bold white]Flow:[/] {flow_preview}")
            if files_preview:
                body_lines.append(f"[bold white]Files:[/] {files_preview}")
            body_lines.append(
                f"[bold white]Scope:[/] {steps} steps  ·  importance {importance:.1f}  ·  "
                f"[{conf_color}]{conf:.2f} confidence[/]  ·  {source_label}"
            )
            console.print(Panel(
                "\n".join(body_lines),
                title=f"[bold cyan]{name}[/]",
                border_style="white",
                padding=(0, 2),
                expand=False,
            ))
        console.print()

    warnings = data.get("report_warnings", [])
    dead_data = data.get("dead_code", {})
    terminal_is_capped = bool(full_requested) or any((
        len(data.get("entry_points", [])) > 15,
        len(dead_data.get("definitely_dead", [])) > 15,
        len(dead_data.get("probably_dead", [])) > 10,
        len(dead_data.get("definitely_dead_tooling", [])) > 10,
        len(dead_data.get("probably_dead_tooling", [])) > 8,
        len(data.get("duplicates", [])) > 12,
        len(data.get("invariants", [])) > 20,
        len(data.get("config_registry", {})) > 20,
        len(data.get("doc_warnings", [])) > 10,
        len(data.get("communities", [])) > 8,
    ))
    if warnings or terminal_is_capped:
        _sec(console, "Report Warnings")
        for warning in warnings:
            console.print(f"  [yellow]▲[/] {warning}")
        if terminal_is_capped:
            console.print("  [yellow]▲[/] Terminal output is capped for readability.")
            console.print(
                "    [white]Use [bold]repograph report --json --full[/] to write the complete "
                "report to [bold].repograph/report.json[/].[/]"
            )
            console.print(
                "    [white]Use [bold]repograph pathway show <name>[/] for the full context of one pathway.[/]"
            )
        console.print()

    def_dead = dead_data.get("definitely_dead", [])
    prob_dead = dead_data.get("probably_dead", [])
    def_tool = dead_data.get("definitely_dead_tooling", [])
    prob_tool = dead_data.get("probably_dead_tooling", [])

    if def_dead or prob_dead:
        _sec(
            console,
            f"Dead Code — Production  "
            f"([red]definitely={len(def_dead)}[/]  [yellow]probably={len(prob_dead)}[/])",
        )
        if def_dead:
            console.print("  [bold red]Definitely dead[/] — zero callers, not exported")
            dead_table = _table()
            dead_table.add_column("Symbol", style="red")
            dead_table.add_column("File", style="white", max_width=55)
            dead_table.add_column("Reason", style="white", max_width=25)
            for dead_symbol in _visible(def_dead, 15, show_all=show_all):
                dead_table.add_row(
                    dead_symbol.get("qualified_name", "?"),
                    dead_symbol.get("file_path", ""),
                    dead_symbol.get("dead_code_reason", "zero_callers"),
                )
            console.print(dead_table)
        if prob_dead:
            console.print("  [bold yellow]Probably dead[/] — low confidence; review before removing")
            probably_dead_table = _table()
            probably_dead_table.add_column("Symbol", style="yellow")
            probably_dead_table.add_column("File", style="white", max_width=45)
            probably_dead_table.add_column("Reason", style="white", max_width=30)
            for dead_symbol in _visible(prob_dead, 10, show_all=show_all):
                probably_dead_table.add_row(
                    dead_symbol.get("qualified_name", "?"),
                    dead_symbol.get("file_path", ""),
                    dead_symbol.get("dead_code_reason", ""),
                )
            console.print(probably_dead_table)

    if def_tool or prob_tool:
        _sec(
            console,
            f"Dead Code — Tooling / Tests / Docs  "
            f"([red]definitely={len(def_tool)}[/]  [yellow]probably={len(prob_tool)}[/])",
        )
        if def_tool:
            tooling_table = _table()
            tooling_table.add_column("Symbol", style="red")
            tooling_table.add_column("File", style="white", max_width=55)
            tooling_table.add_column("Reason", style="white", max_width=25)
            for dead_symbol in _visible(def_tool, 10, show_all=show_all):
                tooling_table.add_row(
                    dead_symbol.get("qualified_name", "?"),
                    dead_symbol.get("file_path", ""),
                    dead_symbol.get("dead_code_reason", ""),
                )
            console.print(tooling_table)
        if prob_tool:
            probable_tool_table = _table()
            probable_tool_table.add_column("Symbol", style="yellow")
            probable_tool_table.add_column("File", style="white", max_width=45)
            probable_tool_table.add_column("Reason", style="white", max_width=30)
            for dead_symbol in _visible(prob_tool, 8, show_all=show_all):
                probable_tool_table.add_row(
                    dead_symbol.get("qualified_name", "?"),
                    dead_symbol.get("file_path", ""),
                    dead_symbol.get("dead_code_reason", ""),
                )
            console.print(probable_tool_table)

    duplicates = data.get("duplicates", [])
    if duplicates:
        _sec(console, f"Duplicate Symbols  ({len(duplicates)} groups)")
        duplicate_table = _table()
        duplicate_table.add_column("Symbol", style="bright_cyan")
        duplicate_table.add_column("Sev", style="white", justify="center", min_width=6)
        duplicate_table.add_column("Canonical", style="green", max_width=40)
        duplicate_table.add_column("Stale copies", style="red", max_width=40)
        for duplicate in _visible(duplicates, 12, show_all=show_all):
            canonical = duplicate.get("canonical_path", "")
            stale_paths = duplicate.get("superseded_paths") or []
            stale = ", ".join("/".join(path.split("/")[-2:]) for path in stale_paths[:2])
            if len(stale_paths) > 2:
                stale += f" +{len(stale_paths) - 2}"
            duplicate_table.add_row(
                duplicate.get("name", "?"),
                duplicate.get("severity", ""),
                "/".join(canonical.split("/")[-2:]) if canonical else "unknown",
                stale or "—",
            )
        console.print(duplicate_table)

    invariants = data.get("invariants", [])
    if invariants:
        _sec(console, f"Architectural Invariants  ({len(invariants)} documented)")
        type_colors = {
            "constraint": "red",
            "guarantee": "green",
            "thread": "yellow",
            "lifecycle": "cyan",
        }
        invariant_table = _table()
        invariant_table.add_column("Type", style="white", min_width=10)
        invariant_table.add_column("Symbol", style="bright_cyan", max_width=35)
        invariant_table.add_column("Rule", max_width=70)
        for invariant in _visible(invariants, 20, show_all=show_all):
            invariant_type = invariant.get("invariant_type", "constraint")
            color = type_colors.get(invariant_type, "white")
            invariant_table.add_row(
                f"[{color}]{invariant_type}[/]",
                invariant.get("symbol_name", "?"),
                invariant.get("invariant_text", ""),
            )
        console.print(invariant_table)

    config_registry = data.get("config_registry", {})
    if config_registry:
        config_rows = list(config_registry.items()) if show_all else list(config_registry.items())[:20]
        _sec(
            console,
            f"Config Key Registry  ({len(config_rows)} keys)"
            if show_all
            else f"Config Key Registry  (top {len(config_rows)} by usage)",
        )
        config_table = _table()
        config_table.add_column("Config Key", style="bright_cyan", min_width=22)
        config_table.add_column("Uses", justify="right", style="white")
        config_table.add_column("Pathways", justify="right")
        config_table.add_column("Files", justify="right")
        for key, val in config_rows:
            config_table.add_row(
                key,
                str(val.get("usage_count", 0)),
                str(len(val.get("pathways", []))),
                str(len(val.get("files", []))),
            )
        console.print(config_table)

    coverage = data.get("test_coverage", [])
    if coverage:
        total_eps = sum(row["entry_point_count"] for row in coverage)
        total_tested = sum(row["tested_entry_points"] for row in coverage)
        overall = round(total_tested / total_eps * 100, 1) if total_eps else 0.0
        uncovered = [row for row in coverage if row["tested_entry_points"] == 0]
        partially = [
            row
            for row in coverage
            if 0 < row["tested_entry_points"] < row["entry_point_count"]
        ]
        cov_color = "green" if overall >= 70 else "yellow" if overall >= 40 else "red"

        _sec(
            console,
            f"Test Coverage  [{cov_color}]{overall}%[/]  ·  "
            f"{len(uncovered)} uncovered  ·  {len(partially)} partial",
        )
        coverage_definition = data.get("coverage_definition") or ""
        if coverage_definition:
            console.print(f"  [white]{coverage_definition}[/]\n")

        if uncovered:
            console.print(f"  [bold red]{len(uncovered)} files with 0% entry-point coverage:[/]")
            coverage_table = _table()
            coverage_table.add_column("File", style="red", max_width=60)
            coverage_table.add_column("EPs", justify="right", style="white")
            for row in _visible(uncovered, 12, show_all=show_all):
                coverage_table.add_row(row["file_path"], str(row["entry_point_count"]))
            console.print(coverage_table)

        if partially:
            console.print(f"\n  [bold yellow]{len(partially)} files with partial coverage:[/]")
            partial_table = _table()
            partial_table.add_column("File", style="yellow", max_width=60)
            partial_table.add_column("Tested", justify="right", style="white")
            partial_table.add_column("Total EPs", justify="right", style="white")
            partial_rows = sorted(
                partially,
                key=lambda row: row["tested_entry_points"] / row["entry_point_count"],
            )
            for row in _visible(partial_rows, 8, show_all=show_all):
                partial_table.add_row(
                    row["file_path"],
                    str(row["tested_entry_points"]),
                    str(row["entry_point_count"]),
                )
            console.print(partial_table)

    doc_warnings = data.get("doc_warnings", [])
    if doc_warnings:
        _sec(console, f"Doc Symbol Warnings  ({len(doc_warnings)} high-severity)")
        warning_table = _table()
        warning_table.add_column("Doc file", style="white", max_width=45)
        warning_table.add_column("Line", justify="right", style="white", min_width=4)
        warning_table.add_column("Unknown symbol", style="yellow", max_width=40)
        for warning in _visible(doc_warnings, 10, show_all=show_all):
            warning_table.add_row(
                warning.get("doc_path", ""),
                str(warning.get("line_number", "")),
                warning.get("symbol_text", ""),
            )
        console.print(warning_table)

    communities = data.get("communities", [])
    community_summary = data.get("communities_summary", {})
    if communities:
        total_comms = community_summary.get("total", len(communities))
        community_rows = _visible(communities, 8, show_all=show_all)
        _sec(
            console,
            f"Communities  ({total_comms} total)"
            if show_all
            else f"Communities  ({total_comms} total  ·  top {len(community_rows)} shown)",
        )
        community_table = _table()
        community_table.add_column("Community", style="bright_cyan", max_width=30)
        community_table.add_column("Members", justify="right", style="white")
        community_table.add_column("Representative files", style="white", max_width=55)
        for community in community_rows:
            members = community.get("member_count", len(community.get("members", [])))
            rep_files = ", ".join((community.get("members") or [])[:3])
            community_table.add_row(
                community.get("label") or community.get("name") or community.get("id", "?"),
                str(members),
                rep_files or "—",
            )
        console.print(community_table)

    footer = Text()
    footer.append("  ", style="white")
    footer.append("repograph report --json", style="bold")
    footer.append("           → full JSON on stdout\n", style="white")
    footer.append("  ", style="white")
    footer.append("repograph report --json --full", style="bold")
    footer.append("     → write to .repograph/report.json\n", style="white")
    footer.append("  ", style="white")
    footer.append("repograph pathway show <name>", style="bold")
    footer.append("      → full context doc for one pathway", style="white")
    console.print(f"\n{footer}")
