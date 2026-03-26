"""Interactive menu entry: main loop and dispatch."""
from __future__ import annotations

import sys

from repograph.interactive import ui
from repograph.interactive.bootstrap import (
    ensure_kuzu_available,
    ensure_repograph_importable,
    get_repo,
    needs_index,
    open_rg,
)
from repograph.interactive.handlers_a import (
    _action_communities,
    _action_dead_code,
    _action_entry_points,
    _action_export,
    _action_full_report,
    _action_impact,
    _action_inspect_file,
    _action_pathways,
    _action_raw_query,
    _action_search,
    _action_status,
    _action_sync,
)
from repograph.interactive.cli_browser import run_cli_browser
from repograph.interactive.handlers_b import (
    _action_clean,
    _action_clean_dev,
    _action_dependencies,
    _action_dependents,
    _action_doc_warnings,
    _action_duplicates,
    _action_hybrid_search,
    _action_mcp,
    _action_pathway_regenerate,
    _action_pathway_steps,
    _action_trace_variable,
    _action_watch,
)

_MAIN_MENU = [
    (
        "cli",
        "CLI command browser     — terminal commands, flags & quick-run (full tool surface)",
    ),
    ("sync", "Sync / Index            — build or refresh the graph"),
    ("status", "Status                  — counts, last sync, staleness"),
    ("report", "Full report (tables)    — one-shot: pathways, entries, dead, dupes, docs, …"),
    ("pathways", "Browse pathways           — context documents"),
    ("steps", "Pathway steps             — ordered functions in a flow"),
    ("entries", "Entry points              — routes, CLI, handlers"),
    ("dead", "Dead code                 — unreachable functions"),
    ("duplicates", "Duplicate symbols         — copy-paste / name clashes"),
    ("docs", "Doc warnings              — stale markdown references"),
    ("impact", "Blast radius              — callers affected by a change"),
    ("search", "Search (fuzzy name)       — quick symbol lookup"),
    ("hybrid", "Search (hybrid BM25)      — concepts + names"),
    ("deps_up", "Dependents                — who calls X (by depth)"),
    ("deps_down", "Dependencies              — what X calls (by depth)"),
    ("tracevar", "Trace variable            — dataflow / occurrences"),
    ("file", "Inspect file              — classes & functions"),
    ("community", "Communities               — Leiden clusters"),
    ("query", "Raw Cypher                — Kuzu queries"),
    ("export", "Export                    — JSON / pathways / full graph"),
    ("pathup", "Regenerate pathway        — rebuild one pathway doc"),
    ("watch", "Watch mode                — auto re-sync on save"),
    ("mcp", "MCP server                — AI agent tools (stdio/HTTP)"),
    ("clean", "Clean index               — delete .repograph/"),
    ("cleandev", "Clean dev junk           — caches, venv, macOS, trace helpers, …"),
]


def main() -> None:
    ensure_repograph_importable()
    ensure_kuzu_available()

    argv_path = sys.argv[1] if len(sys.argv) > 1 else None
    repo = get_repo(argv_path)

    ui._header("RepoGraph  ·  Interactive Menu")
    print(f"  Repository : {ui._b(repo)}")

    rg = open_rg(repo)

    def need_index() -> bool:
        if needs_index(rg):
            print(f"  {ui._y('Index the repo first (choose Sync).')}\n")
            return False
        return True

    try:
        if needs_index(rg):
            print(f"\n  {ui._y('This repository has not been indexed yet.')}")
            if ui._confirm("Run a full index now?"):
                _action_sync(rg)
            else:
                print(f"\n  {ui._d('You can run sync any time from the main menu.')}\n")
        else:
            status = rg.status()
            print(
                f"  Status     : {ui._g('indexed')}  "
                f"{status.get('files', 0)} files · "
                f"{status.get('functions', 0)} functions · "
                f"{status.get('pathways', 0)} pathways"
            )
            if status.get("last_sync"):
                print(f"  Last sync  : {ui._d(status['last_sync'])}")

        while True:
            choice = ui._choose(
                "What would you like to do?",
                _MAIN_MENU,
                foot=(
                    "Type a number 1–25, then Enter.  "
                    "Empty Enter = leave this menu.  0 = exit RepoGraph completely.  "
                    "Tip: option 1 opens the terminal CLI browser (all Typer commands). "
                    "Option \"Full report\" runs every overview query at once."
                ),
            )

            if choice == ui.CHOOSE_EXIT:
                print(f"\n  {ui._d('Goodbye.')}\n")
                break
            if choice == ui.CHOOSE_BACK:
                print(f"\n  {ui._d('Goodbye.')}\n")
                break
            elif choice == "cli":
                # Subprocess CLI needs exclusive access to graph.db; this menu holds an open RepoGraph.
                rg.close()
                try:
                    run_cli_browser(repo)
                finally:
                    rg = open_rg(repo)
            elif choice == "sync":
                _action_sync(rg)
            elif choice == "status":
                _action_status(rg)
            elif choice == "report":
                if need_index():
                    _action_full_report(rg)
            elif choice == "pathways":
                if need_index():
                    _action_pathways(rg)
            elif choice == "steps":
                if need_index():
                    _action_pathway_steps(rg)
            elif choice == "entries":
                if need_index():
                    _action_entry_points(rg)
            elif choice == "dead":
                if need_index():
                    _action_dead_code(rg)
            elif choice == "duplicates":
                if need_index():
                    _action_duplicates(rg)
            elif choice == "docs":
                if need_index():
                    _action_doc_warnings(rg)
            elif choice == "impact":
                if need_index():
                    _action_impact(rg)
            elif choice == "search":
                if need_index():
                    _action_search(rg)
            elif choice == "hybrid":
                if need_index():
                    _action_hybrid_search(rg)
            elif choice == "deps_up":
                if need_index():
                    _action_dependents(rg)
            elif choice == "deps_down":
                if need_index():
                    _action_dependencies(rg)
            elif choice == "tracevar":
                if need_index():
                    _action_trace_variable(rg)
            elif choice == "file":
                if need_index():
                    _action_inspect_file(rg)
            elif choice == "community":
                if need_index():
                    _action_communities(rg)
            elif choice == "query":
                if need_index():
                    _action_raw_query(rg)
            elif choice == "export":
                if need_index():
                    _action_export(rg)
            elif choice == "pathup":
                if need_index():
                    _action_pathway_regenerate(rg)
                    rg = open_rg(repo)
            elif choice == "watch":
                if need_index():
                    _action_watch(rg)
                    rg = open_rg(repo)
            elif choice == "mcp":
                if need_index():
                    _action_mcp(rg)
                    rg = open_rg(repo)
            elif choice == "clean":
                _action_clean(rg)
                rg = open_rg(repo)
            elif choice == "cleandev":
                _action_clean_dev(rg)
                rg = open_rg(repo)
    except ui.MenuExit:
        print(f"\n  {ui._d('Goodbye.')}\n")
    except KeyboardInterrupt:
        print(f"\n  {ui._d('Interrupted.')}\n")
    finally:
        try:
            rg.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
