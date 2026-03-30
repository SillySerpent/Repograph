"""Curated CLI reference for the interactive CLI browser (richer than ``repograph --help`` alone).

Each entry mirrors a Typer command in :mod:`repograph.cli`. For the authoritative
full flag list, users can still run ``repograph <cmd> --help`` from this browser.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlagLine:
    """One option group: short synopsis + explanation."""

    synopsis: str
    detail: str


@dataclass(frozen=True)
class RunVariant:
    """Named preset for the CLI browser: extra Typer flags before the repo path (when applicable)."""

    label: str
    extra: tuple[str, ...] = ()
    # Shown under *label* in the run submenu — plain language for people new to the CLI.
    explain: str = ""


@dataclass(frozen=True)
class CliEntry:
    """One terminal subcommand."""

    key: str
    argv: tuple[str, ...]
    title: str
    body: str
    flags: tuple[FlagLine, ...] = ()
    examples: tuple[str, ...] = ()
    # Optional copy for the “Default” row in the run submenu (what happens with no extra flags).
    run_default_help: str = ""
    # Optional one-off paragraph before the run submenu (e.g. how limits combine).
    run_submenu_intro: str = ""
    # Browser “Run…” presets (non-empty extras only; default is always the first menu row).
    run_variants: tuple[RunVariant, ...] = ()
    # How "quick run" appends the repo path or prompts for an argument:
    # append_path | none | symbol | query | class_name | pathway_name
    run_kind: str = "append_path"


@dataclass(frozen=True)
class CliCategory:
    id: str
    title: str
    intro: str
    commands: tuple[CliEntry, ...]


def all_categories() -> tuple[CliCategory, ...]:
    return (
        CliCategory(
            id="project",
            title="Project & index",
            intro="Create and refresh the graph under .repograph/, check health, clean artifacts.",
            commands=(
                CliEntry(
                    key="init",
                    argv=("init",),
                    title="init — create .repograph/ layout",
                    body="First-time setup: directories, .gitignore for graph.db. Does not parse source.",
                    flags=(
                        FlagLine("--force / -f", "Re-run layout even if already initialized."),
                    ),
                    examples=("repograph init", "repograph init --force", "repograph init /path/to/repo"),
                    run_default_help=(
                        "Creates the .repograph/ folder and supporting files only—does not parse your source yet. "
                        "Run sync afterward to build the graph."
                    ),
                    run_variants=(
                        RunVariant(
                            "Force re-init layout (--force)",
                            ("--force",),
                            "Recreates the .repograph/ folder layout even if it already exists. "
                            "Use when the folder structure looks wrong; it does not delete your graph database by itself.",
                        ),
                    ),
                ),
                CliEntry(
                    key="sync",
                    argv=("sync",),
                    title="sync — build or refresh the index",
                    body="Runs the pipeline (walk → parse → graph …). Incremental by default; "
                    "use --full for the canonical one-shot full rebuild with automatic runtime overlay. "
                    "Use --static-only for a pure static rebuild. Optional embeddings, git coupling, strict mode.",
                    flags=(
                        FlagLine(
                            "--full",
                            "Complete rebuild plus automatic traced-test overlay when RepoGraph can resolve a test command.",
                        ),
                        FlagLine(
                            "--static-only",
                            "Complete rebuild of the index with no automatic test execution or runtime overlay.",
                        ),
                        FlagLine(
                            "--embeddings",
                            "Runs the optional semantic-embedding step (requires sentence-transformers). "
                            "Skip unless you use hybrid semantic search.",
                        ),
                        FlagLine(
                            "--no-git",
                            "Skips git-based phases (faster when you do not need blame/branch hints from git).",
                        ),
                        FlagLine(
                            "--strict",
                            "If any optional pipeline step fails, abort the whole sync instead of continuing.",
                        ),
                        FlagLine(
                            "--no-continue-on-error",
                            "Like strict: stop on the first optional-phase failure instead of best-effort continuation.",
                        ),
                        FlagLine(
                            "--include-tests-config-registry",
                            "When building the config-key registry, include test files (slower, broader picture).",
                        ),
                    ),
                    examples=("repograph sync", "repograph sync --full", "repograph sync --static-only"),
                    run_default_help=(
                        "Updates the graph for changed files (incremental). First sync can take a while; "
                        "later runs are usually faster."
                    ),
                    run_submenu_intro=(
                        "Presets below are common flag combinations. Your repo path is added automatically at the end."
                    ),
                    run_variants=(
                        RunVariant(
                            "Full rebuild + runtime overlay (--full)",
                            ("--full",),
                            "Re-parses and rebuilds the index from scratch, then auto-runs traced tests when configured.",
                        ),
                        RunVariant(
                            "Full static-only rebuild (--static-only)",
                            ("--static-only",),
                            "Re-parses and rebuilds the index from scratch without running tests.",
                        ),
                        RunVariant(
                            "Full + embeddings (--full --embeddings)",
                            ("--full", "--embeddings"),
                            "Full rebuild and runs the optional embedding step (needs sentence-transformers installed).",
                        ),
                        RunVariant(
                            "Skip git coupling (--no-git)",
                            ("--no-git",),
                            "Faster sync when you do not need git-based hints; skips the git phase entirely.",
                        ),
                        RunVariant(
                            "Strict (fail on optional-phase errors) (--strict)",
                            ("--strict",),
                            "Stops the whole sync if an optional step fails instead of continuing with warnings.",
                        ),
                    ),
                ),
                CliEntry(
                    key="status",
                    argv=("status",),
                    title="status — index counts & staleness",
                    body="Read-only snapshot: how much is indexed, last sync time, and simple health hints.",
                    run_kind="append_path",
                    examples=("repograph status",),
                    run_default_help=(
                        "Prints counts (files, functions, pathways, …) and when the index was last updated. "
                        "Does not change anything."
                    ),
                ),
                CliEntry(
                    key="doctor",
                    argv=("doctor",),
                    title="doctor — environment & import checks",
                    body="Checks that Python, Kuzu, parsers, and optional extras work before you rely on the tool.",
                    flags=(
                        FlagLine(
                            "--verbose / -v",
                            "Adds extra detail such as pip’s view of the installed repograph package.",
                        ),
                    ),
                    examples=("repograph doctor", "repograph doctor -v"),
                    run_default_help=(
                        "Runs a quick health check: can this machine open the graph, import the engine, "
                        "and run a minimal query."
                    ),
                    run_variants=(
                        RunVariant(
                            "Verbose (pip show) (-v)",
                            ("--verbose",),
                            "Prints extra environment detail, including pip’s view of the repograph package.",
                        ),
                    ),
                ),
                CliEntry(
                    key="clean",
                    argv=("clean",),
                    title="clean — remove .repograph/ and optional dev junk",
                    body="Removes the RepoGraph index under .repograph/ (the graph database). "
                    "With --dev, also clears common local junk (caches, venv folders at repo root, trace helpers).",
                    flags=(
                        FlagLine(
                            "--yes / -y",
                            "Do not ask for confirmation before deleting (dangerous if you pick the wrong folder).",
                        ),
                        FlagLine(
                            "--dev / -d",
                            "Before deleting the index, run a broader cleanup of dev artifacts (see help above).",
                        ),
                        FlagLine(
                            "--recursive / --no-recursive",
                            "With --dev: scan the whole tree for caches, or only clean at the repository root (faster).",
                        ),
                    ),
                    examples=("repograph clean", "repograph clean --dev -y"),
                    run_default_help=(
                        "Deletes the .repograph/ index for this repo after a confirmation prompt (unless you use -y)."
                    ),
                    run_submenu_intro=(
                        "Choose how aggressive cleanup should be. The repo path you picked in the menu is passed automatically."
                    ),
                    run_variants=(
                        RunVariant(
                            "Index only, no prompts (--yes)",
                            ("--yes",),
                            "Deletes the .repograph/ index directory without asking for confirmation.",
                        ),
                        RunVariant(
                            "Dev cleanup + index (prompts) (--dev)",
                            ("--dev",),
                            "First removes caches, local venv folders, junk files, then removes the index—asks before deleting.",
                        ),
                        RunVariant(
                            "Dev cleanup + index, no prompts (--dev --yes)",
                            ("--dev", "--yes",),
                            "Same as dev cleanup, but skips confirmation prompts (use only if you are sure).",
                        ),
                        RunVariant(
                            "Dev shallow (root-only caches) + no prompts (--dev --yes --no-recursive)",
                            ("--dev", "--yes", "--no-recursive"),
                            "With --dev, only cleans caches at the repo root (faster), then deletes the index without prompts.",
                        ),
                    ),
                ),
            ),
        ),
        CliCategory(
            id="overview",
            title="Overview & reports",
            intro="One-shot summaries and structural reports over the indexed graph.",
            commands=(
                CliEntry(
                    key="summary",
                    argv=("summary",),
                    title="summary — one-screen intelligence",
                    body="Single screen of high-signal facts: what the repo is for, size stats, top entry points, "
                    "sample pathways, dead code and duplicate hints—good first read for humans or AI.",
                    flags=(
                        FlagLine(
                            "--json",
                            "Print the same content as structured JSON (for scripts, saving to a file, or piping).",
                        ),
                        FlagLine(
                            "--verbose / -v",
                            "Adds numeric score breakdowns for entry points (how important each entry looks).",
                        ),
                    ),
                    examples=("repograph summary", "repograph summary --json"),
                    run_default_help=(
                        "Prints a compact, human-readable overview in the terminal—fast mental model of the codebase."
                    ),
                    run_submenu_intro=(
                        "JSON is for machines; verbose adds numbers; default is the friendliest for reading."
                    ),
                    run_variants=(
                        RunVariant(
                            "JSON (--json)",
                            ("--json",),
                            "Prints the same summary as on screen, but as structured JSON for tools or scripts.",
                        ),
                        RunVariant(
                            "Verbose entry-point scores (-v)",
                            ("--verbose",),
                            "Prints extra scoring detail for entry points (routes, CLIs, etc.).",
                        ),
                    ),
                ),
                CliEntry(
                    key="report",
                    argv=("report",),
                    title="report — full intelligence dump",
                    body="Everything: modules, pathways with context, dead code, dupes, invariants, doc warnings, etc.",
                    flags=(
                        FlagLine(
                            "--json",
                            "Prints the whole report as JSON (one big object) instead of colored tables. "
                            "Good for saving to a file, piping to another program, or pasting into an AI.",
                        ),
                        FlagLine(
                            "--pathways / -p <N>",
                            "How many pathway sections to include (default 10). Raise this if you want more "
                            "documented flows in one run.",
                        ),
                        FlagLine(
                            "--dead / -d <N>",
                            "How many dead-code symbols to show per tier (default 20). Raise this to see "
                            "longer lists of possibly unused code.",
                        ),
                        FlagLine(
                            "--full",
                            "With --json only: writes the report to .repograph/report.json instead of printing JSON "
                            "to the terminal. Without --json, the report is unchanged (habit flag matching sync).",
                        ),
                    ),
                    examples=("repograph report", "repograph report --json", "repograph report --full --json"),
                    run_default_help=(
                        "Prints the full report as readable tables and text in this terminal. "
                        "Nothing is saved to a file unless you redirect output yourself."
                    ),
                    run_submenu_intro=(
                        "Below, each choice only changes the output format (text vs JSON) or how many items "
                        'appear (pathways, dead code). Combine more with "Custom flags" if you need a mix.'
                    ),
                    run_variants=(
                        RunVariant(
                            "Machine-readable JSON (--json)",
                            ("--json",),
                            "Prints the entire report as structured JSON to the terminal. The output looks like "
                            "code, not tables—use it for scripts, another tool, or copying into a file.",
                        ),
                        RunVariant(
                            "Show more pathways (25 instead of 10)",
                            ("--pathways", "25"),
                            "Pathways are documented flows through the code. The default is 10 sections; "
                            "this shows 25 so you see more flows in one run.",
                        ),
                        RunVariant(
                            "Show more dead-code rows (40 per tier)",
                            ("--dead", "40"),
                            "Dead code is grouped into tiers; each tier lists up to N symbols. Default is 20; "
                            "this raises the limit so longer lists appear.",
                        ),
                        RunVariant(
                            "More pathways + more dead code (25 pathways, 40 dead per tier)",
                            ("--pathways", "25", "--dead", "40"),
                            "Uses both higher limits at once for a fuller report while still reading as normal text.",
                        ),
                        RunVariant(
                            "JSON on disk (--full --json)",
                            ("--full", "--json"),
                            "Writes the same JSON payload to .repograph/report.json and prints the path; use this "
                            "when you want a stable file in the index folder instead of terminal output.",
                        ),
                    ),
                ),
                CliEntry(
                    key="modules",
                    argv=("modules",),
                    title="modules — per-directory map",
                    body="Table of folders (modules) with file counts, notable classes, and issue counts—"
                    "a map of the repo structure without opening every file.",
                    flags=(
                        FlagLine(
                            "--min-files / -m <N>",
                            "Hide folders that have fewer than N source files (default 1 = show all). "
                            "Raise N to focus on larger areas.",
                        ),
                        FlagLine(
                            "--issues",
                            "Only list folders that have dead code or duplicate-symbol issues—good for cleanup triage.",
                        ),
                        FlagLine(
                            "--json",
                            "Same data as JSON instead of a table (for tools or large repos).",
                        ),
                    ),
                    examples=("repograph modules", "repograph modules --issues"),
                    run_default_help=(
                        "Shows every module row with default filters—broad structural overview."
                    ),
                    run_submenu_intro=(
                        "Filters reduce noise; JSON is for automation. Combine with Custom if you need -m and --issues together."
                    ),
                    run_variants=(
                        RunVariant(
                            "Only folders with issues (--issues)",
                            ("--issues",),
                            "Skips clean folders so you see where dead code or duplicates were detected.",
                        ),
                        RunVariant(
                            "Ignore tiny folders (min 5 source files) (-m 5)",
                            ("--min-files", "5"),
                            "Hides small folders so the table focuses on substantial parts of the tree.",
                        ),
                        RunVariant(
                            "JSON (--json)",
                            ("--json",),
                            "Machine-readable module list—useful for spreadsheets or custom reports.",
                        ),
                    ),
                ),
                CliEntry(
                    key="config_cmd",
                    argv=("config",),
                    title="config — config key usage map",
                    body="Shows which parts of the codebase reference each configuration key (env vars, settings). "
                    "Useful before renaming a setting or deleting one.",
                    flags=(
                        FlagLine(
                            "--key / -k <NAME>",
                            "Zoom in on one key: list every pathway or file that touches it (rename blast radius).",
                        ),
                        FlagLine(
                            "--top / -n <N>",
                            "How many keys to show in the summary table when not using --key (default 20).",
                        ),
                        FlagLine("--json", "Same data as JSON for scripting or diffing."),
                        FlagLine(
                            "--include-tests",
                            "Rebuild the registry including test files (slower, sees more references).",
                        ),
                    ),
                    examples=("repograph config", "repograph config --key DATABASE_URL"),
                    run_default_help=(
                        "Lists the top config keys and where they are used—start here for a broad picture."
                    ),
                    run_variants=(
                        RunVariant(
                            "Include test files in registry (--include-tests)",
                            ("--include-tests",),
                            "Scans tests too when building the map—finds keys only referenced from tests.",
                        ),
                        RunVariant(
                            "JSON (--json)",
                            ("--json",),
                            "Structured output for tools or saving beside the repo.",
                        ),
                    ),
                ),
                CliEntry(
                    key="invariants",
                    argv=("invariants",),
                    title="invariants — docstring architectural rules",
                    body="Lists rules and constraints mined from docstrings (e.g. MUST, NEVER, INV-…) so teams "
                    "and tools do not violate documented contracts.",
                    flags=(
                        FlagLine(
                            "--type / -t <kind>",
                            "Show only one category: constraint, guarantee, thread, or lifecycle.",
                        ),
                        FlagLine("--json", "Same rules as JSON for automation or dashboards."),
                    ),
                    examples=("repograph invariants",),
                    run_default_help=(
                        "Prints all discovered invariants in a readable grouped view."
                    ),
                    run_variants=(
                        RunVariant(
                            "Only constraints (--type constraint)",
                            ("--type", "constraint"),
                            "Filters to hard rules like “never” or “must not”.",
                        ),
                        RunVariant(
                            "JSON (--json)",
                            ("--json",),
                            "Machine-readable list of invariant records.",
                        ),
                    ),
                ),
                CliEntry(
                    key="test_map",
                    argv=("test-map",),
                    title="test-map — entry-point test coverage map",
                    body="For each production file, shows what share of its “entry” functions have a test that calls "
                    "them (static graph reachability—not line or branch coverage).",
                    flags=(
                        FlagLine(
                            "--min-eps <N>",
                            "Only show files that have at least N entry-point functions (default 1). "
                            "Use to focus on files with many routes or handlers.",
                        ),
                        FlagLine(
                            "--uncovered",
                            "Only files where graph-based test coverage is 0%—good backlog for test gaps.",
                        ),
                        FlagLine("--json", "Same rows as JSON."),
                        FlagLine(
                            "--any-call",
                            "Count any production function with a test caller, not only Phase-10 entry points — "
                            "different denominator (all functions); closer to “tests touch this file”.",
                        ),
                    ),
                    examples=(
                        "repograph test-map",
                        "repograph test-map --uncovered",
                        "repograph test-map --any-call",
                    ),
                    run_default_help=(
                        "Full table sorted from least-covered toward best-covered files."
                    ),
                    run_variants=(
                        RunVariant(
                            "Only completely uncovered files (--uncovered)",
                            ("--uncovered",),
                            "Filters to files where no test code appears to call any entry point.",
                        ),
                        RunVariant(
                            "JSON (--json)",
                            ("--json",),
                            "Structured rows for CI or spreadsheets.",
                        ),
                    ),
                ),
            ),
        ),
        CliCategory(
            id="search",
            title="Search, node & impact",
            intro="Look up symbols, hybrid search, blast radius, and dependency-style queries.",
            commands=(
                CliEntry(
                    key="node",
                    argv=("node",),
                    title="node — file or symbol detail",
                    body="Looks up one file path or one function’s dotted name. Shows functions in a file, or "
                    "details for a symbol—good drill-down after search.",
                    flags=(
                        FlagLine(
                            "--path",
                            "Which repository root to use (the menu already passes your chosen repo when you run here).",
                        ),
                    ),
                    examples=("repograph node src/app.py", "repograph node mypkg.handlers.run"),
                    run_default_help=(
                        "You will be asked for a file path or symbol name; output is a table in the terminal."
                    ),
                    run_submenu_intro=(
                        "After picking a preset (if any), you still type the file or symbol—extra flags go before that."
                    ),
                    run_kind="symbol",
                ),
                CliEntry(
                    key="impact",
                    argv=("impact",),
                    title="impact — blast radius (callers)",
                    body="From one function, walks upward through callers: who would be affected if this code changed. "
                    "Uses static call edges from the graph.",
                    flags=(
                        FlagLine(
                            "--depth / -d <N>",
                            "How many hops upward through callers to show (default 3). Higher = wider radius, more noise.",
                        ),
                        FlagLine("--path", "Repository root; usually filled automatically from this menu."),
                    ),
                    examples=("repograph impact handle_request",),
                    run_default_help=(
                        "You will type a function name; default depth is 3 caller levels."
                    ),
                    run_variants=(
                        RunVariant(
                            "Deeper callers (depth 6) (-d 6)",
                            ("--depth", "6"),
                            "Shows more levels of callers—use for large refactors.",
                        ),
                        RunVariant(
                            "Shallow callers only (depth 1) (-d 1)",
                            ("--depth", "1"),
                            "Only direct callers—quickest picture of immediate impact.",
                        ),
                    ),
                    run_kind="symbol",
                ),
                CliEntry(
                    key="query",
                    argv=("query",),
                    title="query — hybrid BM25 + fuzzy search",
                    body="Search by plain-language text over functions and pathways (hybrid BM25 + fuzzy name match). "
                    "Different from the menu item \"Search\" which is tuned for symbol names.",
                    flags=(
                        FlagLine(
                            "--limit / -n <N>",
                            "Maximum number of hits to return (default 10). Raise for broader exploration.",
                        ),
                        FlagLine("--path", "Repository root; usually set automatically from this menu."),
                    ),
                    examples=("repograph query \"auth middleware\"",),
                    run_default_help=(
                        "You will type a search phrase; results are ranked by relevance."
                    ),
                    run_variants=(
                        RunVariant(
                            "More results (25) (-n 25)",
                            ("--limit", "25"),
                            "Returns a longer list—useful when the first 10 are not enough.",
                        ),
                    ),
                    run_kind="query",
                ),
                CliEntry(
                    key="deps",
                    argv=("deps",),
                    title="deps — class constructor dependencies",
                    body="For a class name, lists constructor parameters and types inferred from the graph—"
                    "helps see what a class needs wired in.",
                    flags=(
                        FlagLine(
                            "--depth / -d <N>",
                            "How deep to follow constructor-related hints when resolving dependencies (default 2).",
                        ),
                        FlagLine("--path", "Repository root; usually from this menu."),
                        FlagLine("--json", "Same result as JSON."),
                    ),
                    examples=("repograph deps UserService",),
                    run_default_help=(
                        "You will type a class name (short name, not dotted path)."
                    ),
                    run_variants=(
                        RunVariant(
                            "Deeper dependency resolution (depth 3) (-d 3)",
                            ("--depth", "3"),
                            "Follows a bit further when resolving constructor-related hints.",
                        ),
                        RunVariant(
                            "JSON (--json)",
                            ("--json",),
                            "Structured output for scripts comparing constructor shapes.",
                        ),
                    ),
                    run_kind="class_name",
                ),
                CliEntry(
                    key="events_cmd",
                    argv=("events",),
                    title="events — domain event topology",
                    body="If the index contains domain events, summarizes which parts emit or handle them.",
                    flags=(
                        FlagLine(
                            "--json",
                            "Same graph-derived event summary as JSON.",
                        ),
                    ),
                    examples=("repograph events",),
                    run_default_help=(
                        "Prints a human-readable summary of event relationships."
                    ),
                    run_variants=(
                        RunVariant(
                            "JSON (--json)",
                            ("--json",),
                            "For dashboards or custom tooling.",
                        ),
                    ),
                ),
                CliEntry(
                    key="interfaces_cmd",
                    argv=("interfaces",),
                    title="interfaces — protocol / implementation pairs",
                    body="Lists protocol-style interfaces and which classes implement them—helps navigate abstractions.",
                    flags=(
                        FlagLine(
                            "--json",
                            "Same list as JSON.",
                        ),
                    ),
                    examples=("repograph interfaces",),
                    run_default_help=(
                        "Table-style view in the terminal."
                    ),
                    run_variants=(
                        RunVariant(
                            "JSON (--json)",
                            ("--json",),
                            "Machine-readable interface/implementation pairs.",
                        ),
                    ),
                ),
            ),
        ),
        CliCategory(
            id="pathway",
            title="Pathway subcommands",
            intro="Pathways are documented flows through the graph (repograph pathway …).",
            commands=(
                CliEntry(
                    key="pathway_list",
                    argv=("pathway", "list"),
                    title="pathway list",
                    body="Lists pathway names and metadata.",
                    flags=(
                        FlagLine(
                            "--include-tests",
                            "Also list pathways that only appear in tests (can be noisier but more complete).",
                        ),
                    ),
                    examples=("repograph pathway list",),
                    run_default_help=(
                        "Lists pathway names and short metadata from the index—start here to pick a name for show/update."
                    ),
                    run_variants=(
                        RunVariant(
                            "Include test-only pathways (--include-tests)",
                            ("--include-tests",),
                            "Also lists flows that only appear in tests, not just production code.",
                        ),
                    ),
                ),
                CliEntry(
                    key="pathway_show",
                    argv=("pathway", "show"),
                    title="pathway show <name>",
                    body="Prints one pathway: ordered steps, context text, and how it was inferred—read the doc for a flow.",
                    flags=(),
                    examples=("repograph pathway show checkout_flow",),
                    run_default_help=(
                        "You will type the pathway id or name (see pathway list). Output is long-form text."
                    ),
                    run_kind="pathway_name",
                ),
                CliEntry(
                    key="pathway_update",
                    argv=("pathway", "update"),
                    title="pathway update <name>",
                    body="Rebuilds the stored context document for one pathway after code changes (refreshes steps and narrative).",
                    flags=(
                        FlagLine(
                            "--path",
                            "Rarely needed here—the menu passes your repo root when you quick-run.",
                        ),
                    ),
                    examples=("repograph pathway update my_flow --path .",),
                    run_default_help=(
                        "You will type which pathway to regenerate; use after you changed code on that flow."
                    ),
                    run_kind="pathway_name",
                ),
            ),
        ),
        CliCategory(
            id="trace",
            title="Trace & dynamic overlay",
            intro="Advanced/manual runtime JSONL tooling under .repograph/runtime/. Routine dynamic overlay happens on `repograph sync --full`.",
            commands=(
                CliEntry(
                    key="trace_install",
                    argv=("trace", "install"),
                    title="trace install",
                    body="Writes conftest.py or sitecustomize.py so pytest/python emits call traces to JSONL. Use this only when you want manual tracing control.",
                    flags=(
                        FlagLine(
                            "--mode / -m",
                            "pytest: hook pytest runs (default). sitecustomize: trace any python process that imports your repo.",
                        ),
                    ),
                    examples=("repograph trace install", "repograph trace install --mode sitecustomize"),
                    run_default_help=(
                        "Installs helper files so runs can write JSONL traces under .repograph/runtime/."
                    ),
                    run_submenu_intro=(
                        "Default uses pytest-oriented hooks; sitecustomize is for non-test processes."
                    ),
                    run_variants=(
                        RunVariant(
                            "sitecustomize (trace all python processes) (--mode sitecustomize)",
                            ("--mode", "sitecustomize"),
                            "Traces every Python process that loads your repo, not only pytest. "
                            "Use when you run the app outside tests.",
                        ),
                    ),
                ),
                CliEntry(
                    key="trace_collect",
                    argv=("trace", "collect"),
                    title="trace collect",
                    body="Lists trace JSONL files already on disk and how large they are—sanity check before report.",
                    examples=("repograph trace collect",),
                    run_default_help=(
                        "Read-only listing; does not delete or merge traces."
                    ),
                ),
                CliEntry(
                    key="trace_report",
                    argv=("trace", "report"),
                    title="trace report",
                    body="Combines runtime JSONL traces with the static graph: hot functions, dead-in-static but live "
                    "at runtime, and new dynamic edges.",
                    flags=(
                        FlagLine(
                            "--top / -n <N>",
                            "How many top hot functions to show (limits table size).",
                        ),
                        FlagLine(
                            "--json",
                            "Same analysis as JSON for saving or piping.",
                        ),
                    ),
                    examples=("repograph trace report",),
                    run_default_help=(
                        "Human-readable trace summary for the current repo’s collected JSONL files."
                    ),
                    run_variants=(
                        RunVariant(
                            "JSON (--json)",
                            ("--json",),
                            "Prints the same trace analysis as structured JSON instead of colored text.",
                        ),
                    ),
                ),
                CliEntry(
                    key="trace_clear",
                    argv=("trace", "clear"),
                    title="trace clear",
                    body="Removes collected JSONL trace files under .repograph/runtime/. Does not delete graph.db or "
                    "your source—only runtime capture data.",
                    flags=(
                        FlagLine(
                            "--yes / -y",
                            "Delete trace files without a confirmation prompt.",
                        ),
                    ),
                    examples=("repograph trace clear",),
                    run_default_help=(
                        "Asks before deleting unless you pick the no-prompt preset or use -y."
                    ),
                    run_variants=(
                        RunVariant(
                            "No confirm prompt (-y)",
                            ("--yes",),
                            "Deletes trace files immediately without asking (use when you are sure).",
                        ),
                    ),
                ),
            ),
        ),
        CliCategory(
            id="ops",
            title="Export, watch & MCP",
            intro="Export JSON, filesystem watch for incremental sync, MCP server for AI clients.",
            commands=(
                CliEntry(
                    key="export",
                    argv=("export",),
                    title="export — dump graph JSON",
                    body="Writes a large JSON file with stats, functions, call edges, pathways, entry points, and dead "
                    "code lists—snapshot of the graph for offline tools.",
                    flags=(
                        FlagLine(
                            "--output / -o <file>",
                            "Where to write (default repograph_export.json in the current working directory of the process).",
                        ),
                    ),
                    examples=("repograph export -o dump.json",),
                    run_default_help=(
                        "Creates repograph_export.json next to the process cwd unless you set -o."
                    ),
                    run_variants=(
                        RunVariant(
                            "Write to dump.json in the repo (-o dump.json)",
                            ("-o", "dump.json"),
                            "Saves beside your project with an obvious name (still uses cwd—run from repo root in a shell).",
                        ),
                    ),
                ),
                CliEntry(
                    key="watch",
                    argv=("watch",),
                    title="watch — re-sync on file changes",
                    body="Keeps running: when you save source files, reruns incremental sync so the graph stays fresh "
                    "during development.",
                    flags=(
                        FlagLine(
                            "--no-git",
                            "Each background sync skips git phases—faster if you do not need git metadata.",
                        ),
                        FlagLine(
                            "--strict",
                            "Passes strict mode into each incremental sync so failures surface immediately.",
                        ),
                    ),
                    examples=("repograph watch",),
                    run_default_help=(
                        "Long-running process: leave it in a terminal while you edit code."
                    ),
                    run_submenu_intro=(
                        "Watch holds the terminal; press Ctrl+C in that shell to stop (not from this menu)."
                    ),
                    run_variants=(
                        RunVariant(
                            "Skip git coupling (--no-git)",
                            ("--no-git",),
                            "Each auto-sync skips git-based steps—handy when git is slow or unavailable.",
                        ),
                        RunVariant(
                            "Strict incremental sync (--strict)",
                            ("--strict",),
                            "Passes strict mode into each incremental sync so failures are not silently ignored.",
                        ),
                    ),
                ),
                CliEntry(
                    key="mcp",
                    argv=("mcp",),
                    title="mcp — Model Context Protocol server",
                    body="Starts a server that exposes RepoGraph tools (search, impact, pathways, …) to editors and AI "
                    "clients that speak MCP.",
                    flags=(
                        FlagLine(
                            "--port <N>",
                            "If set, listens for HTTP on this port. If omitted, uses stdio—what most IDE integrations expect.",
                        ),
                    ),
                    examples=("repograph mcp", "repograph mcp --port 8765"),
                    run_default_help=(
                        "stdio mode: your editor launches repograph mcp and talks over pipes. Blocks until stopped."
                    ),
                    run_submenu_intro=(
                        "HTTP mode is for custom clients; stdio is default for Cursor/VS Code style MCP."
                    ),
                    run_variants=(
                        RunVariant(
                            "HTTP on port 8765 (--port 8765)",
                            ("--port", "8765"),
                            "Listens on localhost:8765 instead of stdio—use when wiring a remote or custom client.",
                        ),
                    ),
                ),
            ),
        ),
    )
