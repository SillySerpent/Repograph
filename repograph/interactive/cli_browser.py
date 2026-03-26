"""Interactive browser for Typer CLI commands — curated help + quick-run without typing full strings."""
from __future__ import annotations

import shlex
import subprocess

from repograph.interactive import ui
from repograph.interactive.cli_catalog import CliCategory, CliEntry, all_categories
from repograph.interactive.graph_queries import repograph_cli_path


def _print_banner() -> None:
    pick_help_hint = 'Pick "Show --help" for the authoritative flag list for one command.'
    ui._header("Terminal CLI — full Repograph capabilities")
    print(
        f"  {ui._d('Run any command from a terminal in any directory, for example:')}\n"
        f"    {ui._c('repograph sync --full')}\n"
        f"    {ui._c('repograph pathway list')}\n"
        f"    {ui._c('repograph trace install')}\n\n"
        f"  {ui._b('This browser')} groups every command with short explanations and common flags — "
        f"beyond what {ui._d('repograph --help')} shows (names only).\n"
        f"  {ui._d(pick_help_hint)}\n"
    )
    ui._hr()
    print(f"  {ui._b('Opened from the interactive menu')}")
    print(
        f"  {ui._d('The main menu releases its hold on the graph database before you run commands here. ')}\n"
        f"  {ui._d('That way each quick-run subprocess can open .repograph/graph.db (otherwise you would see a file lock error).')}\n"
    )


def _print_entry(entry: CliEntry) -> None:
    ui._section(entry.title)
    for line in entry.body.split("\n"):
        print(f"  {line}")
    if entry.flags:
        print()
        print(f"  {ui._b('Common options')}")
        for fl in entry.flags:
            print(f"    {ui._c(fl.synopsis)}")
            print(f"      {ui._d(fl.detail)}")
    if entry.examples:
        print()
        print(f"  {ui._b('Examples')}")
        for ex in entry.examples:
            print(f"    {ui._d(ex)}")


def _run_subprocess(argv: list[str]) -> None:
    exe = repograph_cli_path()
    cmd = [exe, *argv]
    print(f"\n  {ui._d('Running:')} {' '.join(cmd)}\n")
    try:
        subprocess.run(cmd, check=False)
    except OSError as e:
        print(f"  {ui._r(str(e))}")


def _run_help(argv: list[str]) -> None:
    exe = repograph_cli_path()
    cmd = [exe, *argv, "--help"]
    print(f"\n  {ui._d('Running:')} {' '.join(cmd)}\n")
    try:
        subprocess.run(cmd, check=False)
    except OSError as e:
        print(f"  {ui._r(str(e))}")


def _quick_run(entry: CliEntry, repo_root: str, *, extra_pre_path: tuple[str, ...] = ()) -> None:
    kind = entry.run_kind
    av = list(entry.argv)
    extra = list(extra_pre_path)

    if kind == "append_path":
        _run_subprocess(av + extra + [repo_root])
        return
    if kind == "none":
        _run_subprocess(av + extra)
        return
    if kind == "symbol":
        sym = ui._ask("File path or qualified symbol name")
        if not sym or sym == "0":
            return
        _run_subprocess(av + extra + [sym, "--path", repo_root])
        return
    if kind == "query":
        q = ui._ask("Search query text")
        if not q or q == "0":
            return
        _run_subprocess(av + extra + [q, "--path", repo_root])
        return
    if kind == "class_name":
        cname = ui._ask("Class name (unqualified, e.g. UserService)")
        if not cname or cname == "0":
            return
        _run_subprocess(av + extra + [cname, "--path", repo_root])
        return
    if kind == "pathway_name":
        name = ui._ask("Pathway name (see repograph pathway list)")
        if not name or name == "0":
            return
        if av[-1] == "show":
            _run_subprocess(av + extra + [name, repo_root])
        else:
            _run_subprocess(av + extra + [name, "--path", repo_root])
        return


_DEFAULT_RUN_HELP = (
    "Runs the command with no extra flags—same idea as the first example listed on the previous screen."
)
_CUSTOM_RUN_HELP = (
    "Type the flags yourself (space-separated; use quotes if a value has spaces). "
    "They are inserted in the same place as the presets—usually just before the repository path. "
    'Use "Show --help" from the previous menu for the authoritative flag list.'
)


def _run_submenu(entry: CliEntry, repo_root: str) -> None:
    opts_detail: list[tuple[str, str, str | None]] = [
        (
            "default",
            "Default — no extra flags",
            entry.run_default_help or _DEFAULT_RUN_HELP,
        ),
    ]
    for i, rv in enumerate(entry.run_variants):
        opts_detail.append((f"p{i}", rv.label, rv.explain or None))
    opts_detail.append(("custom", "Custom flags — type your own", _CUSTOM_RUN_HELP))

    key = ui._choose_with_details(
        "How should we run this command?",
        opts_detail,
        allow_back=True,
        intro=entry.run_submenu_intro or None,
        foot="Enter = back without running.  0 = exit RepoGraph completely.",
    )
    if key == ui.CHOOSE_EXIT:
        raise ui.MenuExit
    if key == ui.CHOOSE_BACK:
        return
    if key == "default":
        _quick_run(entry, repo_root)
        return
    if key == "custom":
        raw = ui._ask(
            "Extra arguments",
            help_lines=[
                "Space-separated flags and values (same as in a terminal).",
                "Example: --json --pathways 30   or   --dev --yes",
            ],
        )
        parts = tuple(shlex.split(raw))
        _quick_run(entry, repo_root, extra_pre_path=parts)
        return
    if key.startswith("p"):
        idx = int(key[1:])
        _quick_run(entry, repo_root, extra_pre_path=entry.run_variants[idx].extra)
        return


def _command_actions(entry: CliEntry, repo_root: str) -> None:
    opts = [
        ("run", "Run… (default, presets, or custom flags)"),
        ("help", "Show full ``repograph … --help`` for this command"),
        ("back", "← Back"),
    ]
    keys = [o[0] for o in opts]
    while True:
        c = ui._choose("What next?", list(zip(keys, [x[1] for x in opts])), allow_back=True)
        if c == ui.CHOOSE_EXIT:
            raise ui.MenuExit
        if c == ui.CHOOSE_BACK or c == "back":
            return
        if c == "help":
            _run_help(list(entry.argv))
            input(f"\n  {ui._d('Press Enter to continue…')}")
        elif c == "run":
            _run_submenu(entry, repo_root)
            input(f"\n  {ui._d('Press Enter to continue…')}")


def run_cli_browser(repo_root: str) -> None:
    """Main loop: categories → commands → detail → actions."""
    cats = all_categories()
    while True:
        _print_banner()
        cat_opts = [
            (
                c.id,
                f"{c.title} — {c.intro[:76]}{'…' if len(c.intro) > 76 else ''}",
            )
            for c in cats
        ]
        cid = ui._choose("Pick a category", cat_opts, allow_back=True)
        if cid == ui.CHOOSE_EXIT:
            raise ui.MenuExit
        if cid == ui.CHOOSE_BACK:
            return
        cat: CliCategory | None = next((c for c in cats if c.id == cid), None)
        if not cat:
            continue

        while True:
            ui._section(cat.title)
            print(f"  {ui._d(cat.intro)}\n")
            cmd_opts = [(e.key, e.title) for e in cat.commands]
            eid = ui._choose("Pick a command", cmd_opts, allow_back=True)
            if eid == ui.CHOOSE_EXIT:
                raise ui.MenuExit
            if eid == ui.CHOOSE_BACK:
                break
            entry = next((e for e in cat.commands if e.key == eid), None)
            if not entry:
                continue

            print()
            _print_entry(entry)
            _command_actions(entry, repo_root)
