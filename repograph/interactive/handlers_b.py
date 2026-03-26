from __future__ import annotations

import json
import os
import shutil
import subprocess

from repograph.interactive.graph_queries import (
    dependencies_by_depth,
    dependents_by_depth,
    hybrid_search,
    repograph_cli_path,
    trace_variable,
)
from repograph.interactive.ui import (
    CHOOSE_BACK,
    CHOOSE_EXIT,
    MenuExit,
    _ask,
    _b,
    _c,
    _choose,
    _confirm,
    _d,
    _g,
    _r,
    _section,
    _y,
)


def _action_pathway_steps(rg) -> None:
    _section("Pathway steps  —  ordered functions in a flow")
    pathways = rg.pathways(min_confidence=0.0)
    if not pathways:
        print(f"  {_y('No pathways. Run Sync first.')}\n")
        return
    options = [(p["name"], f"{p['name']}  {_d('conf ' + str(round(p.get('confidence', 0), 2)))}") for p in pathways]
    name = _choose("Pick a pathway:", options)
    if name == CHOOSE_EXIT:
        raise MenuExit
    if name == CHOOSE_BACK:
        return
    steps = rg.pathway_steps(name)
    if not steps:
        print(f"  {_y('No steps recorded for this pathway.')}\n")
        return
    print()
    for s in sorted(steps, key=lambda x: x.get("step_order", 0)):
        print(f"  {_c(str(s.get('step_order', '?')))}  {_b(s.get('function_name', '?'))}  "
              f"{_d(s.get('file_path', ''))}  [{s.get('role', '')}]")
    print()


def _action_duplicates(rg) -> None:
    _section("Duplicate symbols  —  same name in multiple files")
    sev = _ask("Minimum severity: high | medium | low", default="medium").strip().lower()
    if sev not in ("high", "medium", "low"):
        sev = "medium"
    dups = rg.duplicates(min_severity=sev)
    if not dups:
        print(f"  {_g('No duplicate groups at this severity.')}\n")
        return
    print(f"  {_b(str(len(dups)))} group(s):\n")
    for g in dups[:40]:
        paths = g.get("file_paths") or []
        print(f"  {_b(g.get('name', '?'))}  [{g.get('severity', '')}]  "
              f"{g.get('occurrence_count', 0)}×  {_d(g.get('reason', ''))}")
        for fp in paths[:6]:
            print(f"    {_d('·')} {fp}")
        if len(paths) > 6:
            print(f"    {_d('…')} {len(paths) - 6} more files")
        print()
    if len(dups) > 40:
        print(f"  {_d('… and ' + str(len(dups) - 40) + ' more groups')}\n")


def _action_doc_warnings(rg) -> None:
    _section("Documentation warnings  —  stale backtick references")
    sev = _ask("Severity filter: high | medium | low", default="high").strip().lower()
    if sev not in ("high", "medium", "low"):
        sev = "high"
    rows = rg.doc_warnings(min_severity=sev)
    if not rows:
        print(f"  {_g('No doc warnings at this level.')}\n")
        return
    print(f"  {_b(str(len(rows)))} warning(s):\n")
    for w in rows[:50]:
        print(f"  {_y(w.get('doc_path', ''))}:{w.get('line_number', '')}  "
              f"{_b(w.get('symbol_text', ''))}  {_d(w.get('warning_type', ''))}")
        if w.get("context_snippet"):
            print(f"    {_d(w['context_snippet'][:120])}")
    if len(rows) > 50:
        print(f"\n  {_d('… and ' + str(len(rows) - 50) + ' more')}")
    print()


def _action_hybrid_search(rg) -> None:
    _section("Hybrid search  —  BM25 + fuzzy (concepts & names)")
    query = _ask("Search query:")
    if not query:
        return
    try:
        lim = int(_ask("Max results", default="10") or "10")
    except ValueError:
        lim = 10
    store = rg._get_store()
    results = hybrid_search(store, query, limit=max(1, lim))
    if not results:
        print(f"  {_y('No results.')}\n")
        return
    print()
    for r in results[:30]:
        score = r.get("score", 0)
        print(f"  {_c(f'{score:.2f}'):>8}  {_b(r.get('name', '?'))}  "
              f"{_d(r.get('type', ''))}  {r.get('file_path', '')}")
    if len(results) > 30:
        print(f"  {_d('…')}\n")


def _action_dependents(rg) -> None:
    _section("Dependents  —  who calls this symbol (by depth)")
    sym = _ask("Symbol name:")
    if not sym:
        return
    try:
        d = int(_ask("Max depth", default="3") or "3")
    except ValueError:
        d = 3
    store = rg._get_store()
    out = dependents_by_depth(store, sym, depth=max(1, d))
    if "error" in out:
        print(f"  {_r(out['error'])}\n")
        return
    levels = out.get("dependents_by_depth") or {}
    print(f"\n  {_b(out['symbol'])}\n")
    for depth, fns in sorted(levels.items()):
        print(f"  {_b('Depth ' + str(depth))} ({len(fns)})")
        for fn in fns[:25]:
            print(f"    {_d('·')} {fn.get('qualified_name', '')}  {fn.get('file_path', '')}")
        if len(fns) > 25:
            print(f"    {_d('…')}")
        print()


def _action_dependencies(rg) -> None:
    _section("Dependencies  —  what this symbol calls")
    sym = _ask("Symbol name:")
    if not sym:
        return
    try:
        d = int(_ask("Max depth", default="3") or "3")
    except ValueError:
        d = 3
    store = rg._get_store()
    out = dependencies_by_depth(store, sym, depth=max(1, d))
    if "error" in out:
        print(f"  {_r(out['error'])}\n")
        return
    levels = out.get("dependencies_by_depth") or {}
    print(f"\n  {_b(out['symbol'])}\n")
    for depth, fns in sorted(levels.items()):
        print(f"  {_b('Depth ' + str(depth))} ({len(fns)})")
        for fn in fns[:25]:
            print(f"    {_d('·')} {fn.get('qualified_name', '')}  {fn.get('file_path', '')}")
        if len(fns) > 25:
            print(f"    {_d('…')}")
        print()


def _action_trace_variable(rg) -> None:
    _section("Trace variable  —  occurrences & dataflow edges")
    name = _ask("Variable name (exact match in graph):")
    if not name:
        return
    store = rg._get_store()
    out = trace_variable(store, name)
    if "error" in out:
        print(f"  {_r(out['error'])}\n")
        return
    occ = out.get("occurrences") or []
    flows = out.get("flows") or []
    print(f"\n  {_b(str(len(occ)))} occurrence(s), {_b(str(len(flows)))} flow edge(s)\n")
    for o in occ[:30]:
        print(f"  {_d(o.get('file_path', ''))}:{o.get('line_number', '')}  "
              f"{_b(str(o.get('inferred_type', '')))}  param={o.get('is_parameter')} ret={o.get('is_return')}")
    for e in flows[:20]:
        print(f"  {_c('flow')}  {e}")
    print()


def _action_pathway_regenerate(rg) -> None:
    _section("Regenerate pathway  —  re-assemble one pathway (CLI parity)")
    name = _ask("Pathway name (see Browse Pathways):")
    if not name:
        return
    exe = repograph_cli_path()
    repo_path = rg.repo_path
    print(f"\n  {_d('Closing DB handle; running CLI…')}\n")
    rg.close()
    try:
        subprocess.run(
            [exe, "pathway", "update", name, "--path", repo_path],
            check=False,
        )
    finally:
        rg._store = None


def _action_watch(rg) -> None:
    _section("Watch mode  —  re-sync on file changes")
    print("  Runs until Ctrl+C. Uses the same incremental pipeline as the CLI.\n")
    if not _confirm("Start watch now? (closes this menu's DB connection until you exit watch)", default=True):
        return
    exe = repograph_cli_path()
    repo_path = rg.repo_path
    no_git = not _confirm("Include git coupling on each incremental sync?", default=rg.include_git)
    print(f"\n  {_d('Closing database connection…')}\n")
    rg.close()
    cmd = [exe, "watch", repo_path]
    if no_git:
        cmd.append("--no-git")
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        pass
    rg._store = None


def _action_mcp(rg) -> None:
    _section("MCP server  —  for Cursor / Claude / other MCP clients")
    print("  Stdio mode is typical for editor integration; HTTP is optional.\n")
    mode = _choose(
        "Transport",
        [
            ("stdio", "stdio  — default for MCP clients"),
            ("http",  "HTTP  — specify a port"),
        ],
    )
    if mode == CHOOSE_EXIT:
        raise MenuExit
    if mode == CHOOSE_BACK:
        return
    port: str | None = None
    if mode == "http":
        port = _ask("Port", default="8765")
    exe = repograph_cli_path()
    repo_path = rg.repo_path
    print(f"\n  {_d('Closing database connection…')}\n")
    rg.close()
    cmd = [exe, "mcp", repo_path]
    if port:
        cmd.extend(["--port", port])
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        pass
    rg._store = None


def _action_clean(rg) -> None:
    _section("Clean index  —  delete .repograph/")
    from repograph.config import repograph_dir

    rdir = repograph_dir(rg.repo_path)
    if not os.path.isdir(rdir):
        print(f"  {_y('No index directory found.')}\n")
        return
    print(f"  This deletes: {_b(rdir)}\n")
    if not _confirm("Delete the entire RepoGraph index?", default=False):
        return
    rg.close()
    shutil.rmtree(rdir)
    print(f"\n  {_g('✓')}  Removed index. Run Sync to rebuild.\n")
    rg._store = None
    try:
        from repograph.plugins.lifecycle import reset_hook_scheduler

        reset_hook_scheduler()
    except Exception:
        pass


def _action_clean_dev(rg) -> None:
    """Remove caches, venv dirs, macOS junk, trace bootstrap files, then the index."""
    from pathlib import Path

    from repograph.config import repograph_dir
    from repograph.utils.dev_clean import clean_development_artifacts, summarize_removed

    _section("Clean dev junk  —  caches, venv, macOS, trace helpers")
    root = Path(rg.repo_path).resolve()
    print(
        f"  Repository: {_b(str(root))}\n\n"
        f"  Removes Python caches, root-level .venv/venv/env, build/dist, .DS_Store, "
        f"Repograph trace helper files (including {_d('conftest_repograph_trace_install.example.py')} "
        f"and auto-generated trace conftest/sitecustomize), then the RepoGraph index.\n"
    )
    if not _confirm("Proceed with dev cleanup?", default=False):
        return
    removed = clean_development_artifacts(root, recursive=True)
    print(f"\n  {_d(summarize_removed(removed))}\n")
    if removed:
        print(f"  {_g('✓')}  Removed {len(removed)} path(s).\n")
    else:
        print(f"  {_y('No matching dev artifacts (tree may already be clean).')}\n")

    rdir = repograph_dir(str(root))
    if not os.path.isdir(rdir):
        print(f"  {_y('No .repograph/ index to remove.')}\n")
        return
    print(f"  Index directory: {_b(rdir)}\n")
    if not _confirm("Delete the RepoGraph index (.repograph/)?", default=True):
        return
    rg.close()
    shutil.rmtree(rdir)
    print(f"\n  {_g('✓')}  Removed index. Run Sync to rebuild.\n")
    rg._store = None
    try:
        from repograph.plugins.lifecycle import reset_hook_scheduler

        reset_hook_scheduler()
    except Exception:
        pass

