from __future__ import annotations

import json
import os

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
    _print_dict,
    _r,
    _section,
    _table,
    _y,
)


def _action_sync(rg) -> None:
    _section("Index / Sync  —  build or update the graph")
    print("  This scans your repository and builds the intelligence graph.\n")

    if rg._is_initialized():
        mode = _choose(
            "What kind of sync do you want?",
            [
                ("incremental", "Incremental  — only re-process files that changed  (fast)"),
                ("full",        "Full rebuild  — wipe and re-index everything from scratch"),
            ],
        )
        if mode == CHOOSE_EXIT:
            raise MenuExit
        if mode == CHOOSE_BACK:
            return
        full = (mode == "full")
    else:
        print(f"  {_y('No index found yet.')}  Running a full build.\n")
        full = True

    git_present = os.path.isdir(os.path.join(rg.repo_path, ".git"))
    include_git = False
    if git_present:
        include_git = _confirm("Analyse git history for co-change coupling? (slower but richer)")

    print()
    verb = "Full rebuild" if full else "Incremental sync"
    print(f"  {_g('▶')}  {verb} starting on {_b(rg.repo_path)} …\n")

    try:
        # include_git is a RepoGraph constructor field, not a sync() argument
        rg.include_git = include_git
        want_emb = _confirm(
            "Include vector embeddings for semantic search? (needs sentence-transformers)",
            default=False,
        )
        stats = rg.sync(full=full, include_embeddings=want_emb)
        rg._store = None  # re-open fresh after pipeline close
        print(f"\n  {_g('✓')}  Done!\n")
        _section("Results")
        for k, v in stats.items():
            bar = "█" * min(int(v / max(stats.values()) * 30), 30) if isinstance(v, int) and v > 0 else ""
            print(f"    {_b(k):20s}  {_c(str(v))} {_d(bar)}")
    except Exception as exc:
        print(f"\n  {_r('✗  Sync failed:')} {exc}")


def _action_status(rg) -> None:
    _section("Index Status")
    s = rg.status()
    if not s.get("initialized"):
        print(f"  {_y('Not yet indexed.')} Run a sync first.\n")
        return
    print(f"  Repo     : {_b(rg.repo_path)}")
    print(f"  Index dir: {_d(rg.repograph_dir)}")
    if "last_sync" in s:
        print(f"  Last sync: {s['last_sync']}")
    try:
        from repograph.settings import repograph_dir
        from repograph.docs.staleness import StalenessTracker

        st = StalenessTracker(repograph_dir(rg.repo_path))
        stale = st.get_all_stale()
        if stale:
            print(f"  {_y('Stale artifacts:')} {len(stale)}  {_d('(run Sync to refresh)')}")
        else:
            print(f"  {_g('Artifacts:')} up to date")
    except Exception:
        pass
    print()
    items = [(k, v) for k, v in s.items() if k not in ("initialized", "last_sync", "repo")]
    total = sum(v for _, v in items if isinstance(v, int))
    for k, v in items:
        if isinstance(v, int):
            pct = int(v / total * 40) if total else 0
            bar = _c("█" * pct) + _d("░" * (40 - pct))
            print(f"    {_b(k):20s}  {_c(str(v)):>8}  {bar}")
    print()


def _action_pathways(rg) -> None:
    _section("Pathways  —  end-to-end execution flows")

    conf_str = _ask("Minimum confidence to show (0–1.0)?", default="0.7")
    try:
        min_conf = float(conf_str)
    except ValueError:
        min_conf = 0.7

    pathways = rg.pathways(min_confidence=min_conf)
    if not pathways:
        print(f"  {_y('No pathways found at confidence ≥')} {min_conf}")
        return

    print(f"\n  Found {_g(str(len(pathways)))} pathways:\n")
    options = []
    for p in pathways:
        conf = p.get("confidence", 0)
        conf_col = _g if conf >= 0.85 else (_y if conf >= 0.7 else _r)
        conf_str_fmt = f"[{conf:.2f}]"
        step_info = f"steps:{p['step_count']}  entry:{p['entry_function']}"
        label = f"{conf_col(conf_str_fmt)}  {_b(p['name'])}  {_d(step_info)}"
        options.append((p["name"], label))

    while True:
        choice = _choose("Select a pathway to view its full context document:", options)
        if choice == CHOOSE_EXIT:
            raise MenuExit
        if choice == CHOOSE_BACK:
            break

        doc = rg.get_pathway(choice)
        if doc and doc.get("context_doc"):
            _section(f"Pathway: {choice}")
            print(doc["context_doc"])
        else:
            print(f"  {_y('No context document available for this pathway.')}")

        if not _confirm("View another pathway?"):
            break


def _action_entry_points(rg) -> None:
    _section("Entry Points  —  where execution starts")
    print("  These are the functions most likely to be user-facing: HTTP routes,\n"
          "  CLI commands, event handlers, bot loops, etc.\n")

    limit_str = _ask("How many entry points to show?", default="20")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 20

    eps = rg.entry_points(limit=limit)
    if not eps:
        print(f"  {_y('No entry points found.')}")
        return

    print()
    for i, ep in enumerate(eps, 1):
        score = ep.get("entry_score", 0)
        score_col = _g if score > 20 else (_y if score > 5 else _d)
        print(f"  {_d(str(i)):>5}  {score_col(f'[{score:.1f}]'):>10}  "
              f"{_b(ep['qualified_name'])}")
        print(f"         {_d(ep['file_path'])}")
        if ep.get("signature"):
            print(f"         {_d(ep['signature'][:80])}")
        print()


def _action_dead_code(rg) -> None:
    _section("Dead Code  —  unreachable symbols")
    print("  Functions with no callers anywhere in the codebase.\n"
          "  Note: ABC interface implementations and lifecycle callbacks are\n"
          "  automatically exempted — these results should be genuinely dead.\n")

    tier = _ask(
        "Minimum tier: definitely_dead | probably_dead | possibly_dead",
        default="probably_dead",
    ).strip()
    if tier not in ("definitely_dead", "probably_dead", "possibly_dead"):
        tier = "probably_dead"

    dead = rg.dead_code(min_tier=tier)
    if not dead:
        print(f"  {_g('✓ No dead code found.')}\n")
        return

    # Group by file
    by_file: dict[str, list] = {}
    for fn in dead:
        by_file.setdefault(fn["file_path"], []).append(fn)

    print(f"  Found {_r(str(len(dead)))} potentially dead functions in "
          f"{len(by_file)} files:\n")

    for fp, fns in sorted(by_file.items()):
        print(f"  {_b(fp)}")
        for fn in fns:
            print(f"    {_d('·')} {_r(fn['qualified_name'])}  "
                  f"{_d('line ' + str(fn['line_start']))}")
        print()

    if _confirm("Export dead code list to a file?", default=False):
        out = os.path.join(rg.repo_path, ".repograph", "dead_code.json")
        with open(out, "w") as f:
            json.dump(dead, f, indent=2)
        print(f"  {_g('✓')}  Saved to {_b(out)}\n")


def _action_impact(rg) -> None:
    _section("Blast Radius  —  what does changing a function affect?")
    print("  Enter a function or method name to see everything that calls it,\n"
          "  directly or transitively.\n")

    symbol = _ask("Function name to analyse (e.g. validate_credentials, FlagStore.get):")
    if not symbol:
        return

    depth_str = _ask("How many hops to trace?", default="3")
    try:
        depth = int(depth_str)
    except ValueError:
        depth = 3

    print(f"\n  Tracing impact of {_b(symbol)} up to {depth} hops…\n")
    result = rg.impact(symbol, depth=depth)

    if "error" in result:
        print(f"  {_r(result['error'])}")
        return
    if result.get("ambiguous"):
        print(f"  {_y('Ambiguous:')} multiple symbols match. Please be more specific:\n")
        for m in result["matches"]:
            print(f"    {_d('·')} {m}")
        return

    direct = result.get("direct_callers", [])
    transitive = result.get("transitive_callers", [])
    files = result.get("files_affected", [])

    print(f"  Symbol    : {_b(result['symbol'])}")
    print(f"  File      : {_d(result.get('file', ''))}\n")
    print(f"  {_b('Direct callers')} ({len(direct)}):")
    for c in direct[:15]:
        print(f"    {_c('·')} {c['qualified_name']}  {_d(c['file_path'])}")
    if len(direct) > 15:
        print(f"    {_d(f'… and {len(direct)-15} more')}")

    if transitive and len(transitive) > len(direct):
        extra = [c for c in transitive if c["id"] not in {d["id"] for d in direct}]
        print(f"\n  {_b('Transitive callers')} ({len(extra)} additional):")
        for c in extra[:15]:
            print(f"    {_y('·')} {c['qualified_name']}  {_d(c['file_path'])}")
        if len(extra) > 15:
            print(f"    {_d(f'… and {len(extra)-15} more')}")

    if files:
        print(f"\n  {_b('Files affected')} ({len(files)}):")
        for f in files[:20]:
            print(f"    {_d('·')} {f}")
        if len(files) > 20:
            print(f"    {_d(f'… and {len(files)-20} more')}")
    print()


def _action_search(rg) -> None:
    _section("Search  —  find functions and symbols by name")

    while True:
        query = _ask("What are you looking for? (partial name is fine, or 0 to go back):")
        if not query or query == "0":
            break

        limit_str = _ask("How many results?", default="10")
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 10

        results = rg.search(query, limit=limit)
        if not results:
            print(f"  {_y('Nothing found for')} {_b(query)}\n")
            continue

        print(f"\n  Found {_g(str(len(results)))} results for {_b(repr(query))}:\n")
        options = []
        for r in results:
            label = f"{_b(r['qualified_name'])}  {_d(r['file_path'])}"
            if r.get("signature"):
                label += f"\n         {_d(r['signature'][:80])}"
            options.append((r["id"], label))

        choice = _choose("Select a result to inspect:", options)
        if choice == CHOOSE_EXIT:
            raise MenuExit
        if choice == CHOOSE_BACK:
            continue

        by_id = {r["id"]: r for r in results}
        sel = by_id.get(choice)
        if not sel:
            continue
        node = rg.node(sel["qualified_name"])
        if node:
            _section(f"Symbol detail: {sel['qualified_name']}")
            _print_dict({k: v for k, v in node.items() if k != "type"})
        print()


def _action_inspect_file(rg) -> None:
    _section("Inspect a File  —  see everything in a specific file")

    path = _ask("File path (relative to repo root, e.g. src/advisor/engine.py):")
    if not path:
        return

    result = rg.node(path)
    if not result:
        print(f"  {_r('File not found in index:')} {path}")
        print(f"  {_d('Tip: make sure you ran sync, and the path is relative to the repo root.')}\n")
        return

    funcs = result.get("functions", [])
    classes = result.get("classes", [])

    print(f"\n  {_b(path)}")
    print(f"  Language : {result.get('language', 'unknown')}")
    print(f"  Functions: {len(funcs)}")
    print(f"  Classes  : {len(classes)}\n")

    if classes:
        print(f"  {_b('Classes:')}")
        for cls in classes:
            print(f"    {_c(cls['name'])}  {_d('line ' + str(cls['line_start']))}")
        print()

    if funcs:
        print(f"  {_b('Functions:')}")
        for fn in funcs:
            dead_flag = _r(" [DEAD?]") if fn.get("is_dead") else ""
            entry_flag = _g(" [ENTRY]") if fn.get("is_entry_point") else ""
            print(f"    {_b(fn['name'])}{dead_flag}{entry_flag}  "
                  f"{_d('line ' + str(fn['line_start']))}")
            if fn.get("signature"):
                print(f"    {_d(fn['signature'][:80])}")
        print()


def _action_communities(rg) -> None:
    _section("Communities  —  module clusters")
    print("  Groups of functions that frequently call each other, detected\n"
          "  via the Leiden graph algorithm.\n")

    communities = rg.communities()
    if not communities:
        print(f"  {_y('No communities found.')}")
        return

    for c in communities:
        size = c["member_count"]
        bar = _c("█" * min(size // 5, 30)) + _d("░" * max(0, 30 - size // 5))
        cohesion_col = _g if c["cohesion"] > 0.3 else (_y if c["cohesion"] > 0.1 else _d)
        cohesion_str = f"{c['cohesion']:.2f}"
        print(f"  {_b(c['label']):30s}  "
              f"{_c(str(size)):>5} members  "
              f"cohesion:{cohesion_col(cohesion_str)}")
    print()


def _action_raw_query(rg) -> None:
    _section("Raw Cypher Query  —  power user mode")
    print("  Run a Cypher query directly against the graph database.\n"
          "  Available node types: File, Function, Class, Variable, Import,\n"
          "                        Pathway, Community, Process\n"
          "  Example queries:\n"
          f"    {_d('MATCH (f:Function) WHERE f.is_dead = true RETURN f.qualified_name LIMIT 20')}\n"
          f"    {_d('MATCH (a:Function)-[:CALLS]->(b:Function) RETURN a.name, b.name LIMIT 10')}\n")

    while True:
        cypher = _ask("Cypher (or 0 to go back):")
        if not cypher or cypher == "0":
            break
        try:
            rows = rg.query(cypher)
            if not rows:
                print(f"  {_d('(no results)')}\n")
            else:
                print(f"\n  {_g(str(len(rows)))} rows:\n")
                for row in rows[:50]:
                    print(f"  {' | '.join(str(v) for v in row)}")
                if len(rows) > 50:
                    print(f"  {_d(f'… and {len(rows)-50} more rows')}")
                print()
        except Exception as exc:
            print(f"  {_r('Query error:')} {exc}\n")


def _action_export(rg) -> None:
    _section("Export  —  save graph data to a file")

    fmt = _choose(
        "What format do you want?",
        [
            ("json",     "JSON summary — stats, files, functions, pathways"),
            ("full",     "Full graph export — same as CLI `repograph export`"),
            ("pathways", "Pathways only  — all pathway context docs as text"),
            ("dead",     "Dead code report  — JSON list of unreachable symbols"),
        ],
    )
    if fmt == CHOOSE_EXIT:
        raise MenuExit
    if fmt == CHOOSE_BACK:
        return

    out_dir = os.path.join(rg.repograph_dir)
    os.makedirs(out_dir, exist_ok=True)

    if fmt == "dead":
        out = os.path.join(out_dir, "dead_code.json")
        dead = rg.dead_code()
        with open(out, "w") as f:
            json.dump(dead, f, indent=2)
        print(f"\n  {_g('✓')}  {len(dead)} dead functions written to {_b(out)}\n")

    elif fmt == "pathways":
        out = os.path.join(out_dir, "pathways_export.txt")
        pathways = rg.pathways()
        with open(out, "w") as f:
            for p in pathways:
                full = rg.get_pathway(p["name"])
                if full and full.get("context_doc"):
                    f.write(full["context_doc"])
                    f.write("\n\n")
        print(f"\n  {_g('✓')}  {len(pathways)} pathway docs written to {_b(out)}\n")

    elif fmt == "full":
        default_out = os.path.join(out_dir, "repograph_export.json")
        out = _ask("Output file path", default=default_out)
        store = rg._get_store()
        data = {
            "stats": store.get_stats(),
            "functions": store.get_all_functions(),
            "call_edges": store.get_all_call_edges(),
            "pathways": store.get_all_pathways(),
            "entry_points": store.get_entry_points(),
            "dead_code": store.get_dead_functions(),
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"\n  {_g('✓')}  Full graph written to {_b(out)}\n")

    elif fmt == "json":
        out = os.path.join(out_dir, "graph_export.json")
        files = rg.get_all_files()
        fns = rg._get_store().get_all_functions()
        data = {
            "repo": rg.repo_path,
            "stats": rg.status(),
            "files": files,
            "functions": fns,
            "pathways": rg.pathways(),
        }
        with open(out, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"\n  {_g('✓')}  Graph exported to {_b(out)}\n")


def _action_full_report(rg) -> None:
    """One-shot overview: all intelligence via rg.full_report()."""
    _section("Full report  —  complete repository intelligence")
    print(
        f"  {_d('Aggregates: status, modules, entry points, pathways (with context docs),')}\n"
        f"  {_d('dead code, duplicates (with canonical guidance), invariants,')}\n"
        f"  {_d('config registry, test coverage, doc warnings, communities.')}\n"
    )

    if not rg._is_initialized():
        print(f"  {_y('Not indexed yet.')} Run \"Sync / Index\" first.\n")
        return

    print(f"  {_b('Repository')}   {rg.repo_path}")
    print(f"  {_b('Index dir  ')}   {rg.repograph_dir}\n")

    # ── Sync state / staleness ───────────────────────────────────────────────
    try:
        from repograph.settings import repograph_dir
        from repograph.docs.staleness import StalenessTracker
        from repograph.pipeline.sync_state import lock_status

        st_tr, st_li = lock_status(repograph_dir(rg.repo_path))
        _warn_sym = "\u26a0"
        if st_tr == "active" and st_li:
            print(
                f"  {_y(f'{_warn_sym} sync.lock active')}  pid={st_li.pid}  mode={st_li.mode}  "
                f"since={st_li.started_at}\n"
            )
        elif st_tr == "stale":
            print(f"  {_y(f'{_warn_sym} Stale sync.lock — remove if no sync is running.')}\n")
        tr = StalenessTracker(repograph_dir(rg.repo_path))
        stale_n = len(tr.get_all_stale())
        if stale_n:
            print(f"  {_y('Stale artifacts:')} {stale_n}  {_d('(run Sync to refresh)')}\n")
        else:
            print(f"  {_g('Staleness:')} OK\n")
    except Exception:
        pass

    # ── Fetch everything in one call ─────────────────────────────────────────
    data = rg.full_report(max_pathways=10, max_dead=20)

    # ── Health ───────────────────────────────────────────────────────────────
    h = data.get("health") or {}
    if h:
        print(f"  {_b('Health')}")
        h_status = h.get("status", "?")
        print(
            f"    status={h_status}  sync_mode={h.get('sync_mode', '?')}  "
            f"call_edges={h.get('call_edges_total', '?')}"
        )
        if h.get("generated_at"):
            print(f"    generated_at={h['generated_at']}")
        if h_status == "failed":
            print(
                f"    {_r('error:')} {h.get('error_phase')} — "
                f"{str(h.get('error_message', ''))[:200]}"
            )
        print()

    # ── Purpose ──────────────────────────────────────────────────────────────
    purpose = data.get("purpose", "")
    if purpose:
        print(f"  {_b('Purpose')}")
        print(f"    {purpose[:300]}\n")

    # ── Stats ────────────────────────────────────────────────────────────────
    stats = {
        k: v for k, v in (data.get("stats") or {}).items()
        if isinstance(v, int) and k != "initialized"
    }
    if stats:
        print(f"  {_b('Entity counts')}")
        _table(
            ["entity", "count"],
            sorted([[k.replace("_", " "), str(v)] for k, v in stats.items()]),
            col_widths=[22, 10],
        )

    # ── Module map ───────────────────────────────────────────────────────────
    mods = data.get("modules", [])
    if mods:
        print(f"  {_b(f'Module map  ({len(mods)} modules)')}")
        rows = []
        for m in mods:
            issues = []
            if m.get("dead_code_count"):
                issues.append(f"{m['dead_code_count']}dead")
            if m.get("duplicate_count"):
                issues.append(f"{m['duplicate_count']}dup")
            key_cls = ", ".join((m.get("key_classes") or [])[:3])
            src = m.get("prod_file_count", m.get("file_count", 0))
            tst = m.get("test_file_count", 0)
            tst_fn = m.get("test_function_count", 0)
            rows.append([
                m.get("display", ""),
                f"{src}/{tst}",
                str(m.get("function_count", 0)),
                key_cls[:36],
                str(tst_fn) if tst_fn else "—",
                ", ".join(issues) or "—",
            ])
        _table(
            ["module", "src/tst", "fn", "key classes", "tst fn", "issues"],
            rows,
            col_widths=[22, 9, 6, 36, 6, 14],
        )

    # ── Entry points ─────────────────────────────────────────────────────────
    eps = data.get("entry_points", [])
    if eps:
        print(f"  {_b('Entry points (top 15)')}")
        rows = []
        for ep in eps[:15]:
            fp = ep.get("file_path", "")
            rows.append([
                f"{ep.get('entry_score', 0):.1f}",
                str(ep.get("qualified_name", ""))[:42],
                fp[:40] + ("…" if len(fp) > 40 else ""),
            ])
        _table(["score", "qualified_name", "file"], rows, col_widths=[8, 42, 42])

    # ── Pathways ─────────────────────────────────────────────────────────────
    pathways = data.get("pathways", [])
    if pathways:
        print(f"  {_b(f'Pathways (top {len(pathways)})')}")
        rows = []
        for p in pathways:
            ef = str(p.get("entry_function") or "")[:36]
            rows.append([
                str(p.get("name", ""))[:28],
                f"{p.get('confidence', 0):.2f}",
                str(p.get("step_count", "")),
                f"{p.get('importance_score') or 0:.1f}",
                ef,
            ])
        _table(
            ["name", "conf", "steps", "imp", "entry_function"],
            rows,
            col_widths=[28, 6, 6, 6, 38],
        )
        print(f"  {_d('Use pathway show <n> to read a full context doc.')}")
        print()

    # ── Dead code ────────────────────────────────────────────────────────────
    dead = data.get("dead_code", {})
    def_dead = dead.get("definitely_dead", [])
    prob_dead = dead.get("probably_dead", [])
    print(
        f"  {_b('Dead code')}  "
        f"definitely_dead={len(def_dead)}  probably_dead={len(prob_dead)}"
    )
    if def_dead:
        rows = [
            [str(fn.get("qualified_name", ""))[:40],
             str(fn.get("file_path", ""))[:36],
             str(fn.get("line_start", ""))]
            for fn in def_dead[:15]
        ]
        _table(["qualified_name", "file", "line"], rows, col_widths=[40, 36, 6])
    else:
        print(f"  {_g('No definitely_dead symbols.')}\n")

    # ── Duplicates ────────────────────────────────────────────────────────────
    dups = data.get("duplicates", [])
    print(f"  {_b(f'Duplicates (medium+)  total={len(dups)}')}")
    if dups:
        rows = []
        for g in dups[:12]:
            canonical = g.get("canonical_path") or ""
            stale = (g.get("superseded_paths") or [""])[0]
            rows.append([
                str(g.get("name", ""))[:22],
                str(g.get("severity", "")),
                str(g.get("occurrence_count", "")),
                canonical.split("/")[-1][:28] if canonical else "?",
                stale.split("/")[-1][:28] if stale else "—",
            ])
        _table(
            ["name", "sev", "#", "canonical", "stale copy"],
            rows,
            col_widths=[22, 8, 3, 28, 28],
        )
    else:
        print(f"  {_d('(none)')}\n")

    # ── Invariants ────────────────────────────────────────────────────────────
    invs = data.get("invariants", [])
    if invs:
        print(f"  {_b(f'Architectural invariants  ({len(invs)} documented)')}")
        rows = []
        for inv in invs[:20]:
            rows.append([
                str(inv.get("invariant_type", ""))[:12],
                str(inv.get("symbol_name", ""))[:30],
                str(inv.get("invariant_text", ""))[:60],
            ])
        _table(["type", "symbol", "constraint"], rows, col_widths=[12, 30, 60])
    else:
        print(f"  {_d('No invariants found. Add INV-/NEVER/MUST NOT to docstrings.')}\n")

    # ── Config registry ───────────────────────────────────────────────────────
    cfg = data.get("config_registry", {})
    if cfg:
        print(f"  {_b(f'Config key registry  (top {len(cfg)})')}")
        rows = []
        for key, val in list(cfg.items())[:20]:
            rows.append([
                key[:24],
                str(val.get("usage_count", 0)),
                str(len(val.get("pathways", []))),
                str(len(val.get("files", []))),
            ])
        _table(["key", "usage", "pathways", "files"], rows, col_widths=[24, 8, 10, 8])

    # ── Test coverage ─────────────────────────────────────────────────────────
    cov = data.get("test_coverage", [])
    if cov:
        total_eps = sum(r["entry_point_count"] for r in cov)
        total_tested = sum(r["tested_entry_points"] for r in cov)
        overall = round(total_tested / total_eps * 100, 1) if total_eps else 0.0
        uncovered = sum(1 for r in cov if r["tested_entry_points"] == 0)
        print(
            f"  {_b('Test coverage')}  {overall}% overall  "
            f"{uncovered} files with 0% coverage"
        )
        cd = data.get("coverage_definition") or ""
        if cd:
            print(f"  {_d(cd)}")
        no_cov = [r for r in cov if r["tested_entry_points"] == 0][:10]
        if no_cov:
            rows = [
                [r["file_path"][:48], str(r["entry_point_count"])]
                for r in no_cov
            ]
            _table(["file (0% coverage)", "EPs"], rows, col_widths=[48, 4])
        else:
            print(f"  {_g('All files have at least one tested entry point.')}\n")

    # ── Doc warnings ──────────────────────────────────────────────────────────
    warns = data.get("doc_warnings", [])
    print(f"  {_b(f'Doc warnings (high)  total={len(warns)}')}")
    if warns:
        rows = []
        for w in warns[:10]:
            dp = str(w.get("doc_path", ""))
            rows.append([
                dp[:34] + ("…" if len(dp) > 34 else ""),
                str(w.get("line_number", "")),
                str(w.get("warning_type", ""))[:18],
                str(w.get("symbol_text", ""))[:22],
            ])
        _table(["doc_path", "line", "type", "symbol"], rows, col_widths=[34, 5, 18, 22])
    else:
        print(f"  {_d('(none)')}\n")

    # ── Communities ───────────────────────────────────────────────────────────
    comms = data.get("communities", [])
    if comms:
        print(f"  {_b(f'Communities (top {len(comms)})')}")
        rows = [
            [
                str(c.get("label", ""))[:30],
                str(c.get("member_count", "")),
                f"{float(c.get('cohesion') or 0):.3f}",
            ]
            for c in comms[:12]
        ]
        _table(["label", "members", "cohesion"], rows, col_widths=[30, 8, 8])

    print(f"  {_d('Tip: use individual menu items for filters, drill-down, and exports.')}\n")
