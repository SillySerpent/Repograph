# RepoGraph CLI Reference

All commands follow the pattern:

```
repograph <command> [PATH] [OPTIONS]
```

`PATH` defaults to the current working directory when omitted.

For the broadest validated local baseline, use the **Full local workstation**
install tier from [`SETUP.md`](SETUP.md) if you want the best chance of
reproducing the current verified suite of over **1.24k passing tests**
locally. Install Node.js as well only if you plan to run the optional Pyright
quality gate.

Read/query commands also emit structured observability sessions under
`.repograph/logs/`. `sync` creates its own pipeline session; short direct
commands such as `status` and `doctor` create shorter command sessions.

### Interactive menu: CLI command browser

`repograph menu` (or `python -m repograph.entry menu`) opens the text UI. The **first option** is **CLI command browser**: it lists every Typer command in categories, explains what each does and common flags (more narrative than `repograph --help` alone), shows examples, and can **Run…** a command for the current repo with **default args**, **named presets** (for example `clean --dev -y`, or `report --pathways 25`), or **custom flags** you type (parsed like a shell). Under each preset, plain-language text explains what that choice does for someone not used to CLI flags; you can still print **`repograph <cmd> --help`** for the full machine-readable flag list.

---

## `repograph init`

Initialize RepoGraph in a repository.  Creates the `.repograph/` directory
structure. It is optional convenience only — `repograph sync` can bootstrap the
index directly.

```
repograph init [PATH] [--force]
```

| Flag | Description |
|------|-------------|
| `--force / -f` | Re-initialize even if already done (recreates `.repograph/` layout and `.gitignore`; does **not** remove `graph.db` — delete it manually or use `repograph clean` for a full wipe) |

---

## `repograph sync`

Index (or re-index) the repository.  Runs the full analysis pipeline (parse, calls, pathways, dead code, etc. — see `docs/PIPELINE.md`).

```
repograph sync [PATH] [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--full` | Canonical one-shot full rebuild: rebuild static index, then resolve the best eligible automatic runtime path and merge resulting overlays |
| `--static-only` | Force a pure static rebuild from scratch with **no** automatic test execution and **no** merge of on-disk runtime/coverage inputs |
| `--embeddings` | Generate vector embeddings (requires `sentence-transformers`) |
| `--no-git` | Skip git co-change coupling phase (Phase 12) |
| `--strict` | Fail sync if any optional phase errors |
| `--continue-on-error / --no-continue-on-error` | Control optional-phase failure behaviour |
| `--include-tests-config-registry` | Include test files when building `config_registry.json` |

Automatic dynamic-analysis command resolution for `--full`:
1. detect repo-scoped live runtime targets and, when there is exactly one repo-scoped Python server already publishing a RepoGraph live trace session, ask for confirmation before attaching in the CLI; unattended/API usage should set `sync_runtime_attach_policy` to `always` or `never`; otherwise `sync`, `status`, and `report` surface whether attach was unavailable, declined, unsupported, or ambiguous before RepoGraph falls back
2. `sync_runtime_server_command` + `sync_runtime_probe_url` from `settings.json` (or `repograph.index.yaml`) to launch a managed traced Python server, optionally request `sync_runtime_scenario_urls`, and optionally run `sync_runtime_scenario_driver_command` for richer flows
3. `sync_test_command` from `settings.json` (set via `repograph config set`) or `repograph.index.yaml`
4. `python -m pytest tests` when `pyproject.toml` configures pytest and `tests/` exists
5. `python -m pytest` when `pyproject.toml` configures pytest without a `tests/` directory
6. `python -m pytest <dir>` when a `tests/`, `test/`, or `spec/` directory containing `.py` files is found
7. otherwise the full rebuild completes statically and health/report metadata record why dynamic analysis was skipped

If live attach is selected and later fails at execution time, RepoGraph records
the failed attach attempt and then tries the next eligible managed-runtime or
traced-test path instead of claiming the live attach succeeded. `status`,
`summary`, and `report` surface the chosen mode, attach decision, fallback
behavior, and whether runtime or coverage overlays were actually applied.

---

## `repograph summary`

One-screen intelligence summary.  The best starting point for an AI or human
entering an unfamiliar codebase.

```
repograph summary [PATH] [--json] [--verbose]
```

| Flag | Description |
|------|-------------|
| `--json` | Output as machine-readable JSON |
| `--verbose / -v` | Show score breakdown for each entry point |

`summary` is the compact high-signal overview built from a capped `report`
snapshot. It surfaces repo purpose, index/trust state, top entry surfaces,
top pathways, major risks, structural hotspots, and dynamic-analysis status.

Stable `summary --json` contract:

- Top-level keys: `repo`, `purpose`, `stats`, `health`, `dynamic_analysis`, `trust`, `top_entry_points`, `top_pathways`, `major_risks`, `structural_hotspots`, `warnings`, `dead_code_count`, `dead_code_sample`, `high_severity_duplicates`, `duplicate_sample`, `doc_warning_count`
- `trust`: `status`, `sync_status`, `sync_mode`, `warnings`, `analysis_readiness`
- `top_entry_points[]`: `name`, `file`, `score`, `callers`, `callees`, `entry_score_base`, `entry_score_multipliers`
- `top_pathways[]`: `name`, `entry`, `steps`, `importance`, `confidence`, `source`
- `major_risks[]`: `kind`, `severity`, `count`, `summary`
- `structural_hotspots[]`: `module`, `category`, `summary`, `function_count`, `class_count`, `test_function_count`, `dead_code_count`, `duplicate_count`, `issue_count`, `complexity`

Scores and rankings depend on the indexed repo and analyzer version.

---

## `repograph report`

Single JSON or human-readable **full intelligence dump** — same data as
`RepoGraph.full_report()` (entry points, pathways with context docs, dead code,
duplicates, modules, invariants, config registry, test coverage, doc warnings,
communities).

```
repograph report [PATH] [--json] [--full] [--pathways N] [--dead N]
```

| Flag | Description |
|------|-------------|
| `--json` | Print JSON only (no Rich markup); suitable for piping to a file |
| `--full` | With `--json`, write output to `.repograph/report.json` instead of stdout |
| `--pathways / -p N` | Max pathways to include (default 10) |
| `--dead / -d N` | Max dead-code symbols per tier (default 20) |

Pathway `context_doc` values include an **INTERPRETATION** section: steps follow
BFS over `CALLS` edges, not guaranteed runtime order.

`report --json` includes capped-surface metadata (`pathways_summary`, `communities_summary`), count-semantics metadata, and may include `report_warnings` (for example when the latest sync mode is `incremental_traces_only`, dynamic analysis was skipped, or health is `degraded`).

---

## `repograph modules`

Per-directory structural overview.  Replaces calling `node` on every file
when doing context-gathering.

```
repograph modules [PATH] [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--min-files / -m N` | Hide modules with fewer than N files |
| `--issues` | Only show modules with dead code or duplicates |
| `--json` | Output as JSON |

---

## `repograph config` (settings subgroup)

Manage persistent RepoGraph settings.  Settings are stored in `.repograph/settings.json`
as a self-describing settings document. The editable `runtime_overrides` section
takes precedence over YAML-level defaults, while the same file also shows the
current effective values and per-setting schema metadata.

```
repograph config list [PATH]             # show all settings and current values
repograph config get KEY [PATH]          # read one setting
repograph config describe [KEY] [PATH]   # show schema/default/lifecycle details
repograph config set KEY VALUE [PATH]    # persist a value
repograph config unset KEY [PATH]        # remove one runtime override
repograph config reset [PATH]            # clear overrides, refresh the settings document
```

Known settings keys: `include_git`, `include_embeddings`, `auto_dynamic_analysis`,
`sync_test_command`, `sync_runtime_server_command`, `sync_runtime_probe_url`,
`sync_runtime_scenario_urls`, `sync_runtime_scenario_driver_command`,
`sync_runtime_ready_timeout`, `sync_runtime_attach_policy`,
`doc_symbols_flag_unknown`, `context_tokens`, `git_days`, `entry_point_limit`,
`min_community_size`, `nl_model`, `exclude_dirs`, `disable_auto_excludes`.

---

## `repograph config-registry`

Global config-key → consumer mapping.  Use `--key` to see the blast radius
of renaming a single config value.

```
repograph config-registry [PATH] [--key NAME] [--top N] [--json] [--include-tests]
```

| Flag | Description |
|------|-------------|
| `--key / -k NAME` | Show full detail (pathways + files) for one key |
| `--top / -n N` | Number of keys to show (default 20) |
| `--json` | Output as JSON |
| `--include-tests` | Rebuild the registry from the graph including test files (live scan; ignores cached JSON) |

---

## `repograph invariants`

Architectural constraints documented in docstrings (`INV-`, `NEVER`,
`MUST NOT`, `ALWAYS`, thread-safety notes, etc.).

```
repograph invariants [PATH] [--type TYPE] [--json]
```

| Flag | Description |
|------|-------------|
| `--type / -t TYPE` | Filter: `constraint` / `guarantee` / `thread` / `lifecycle` |
| `--json` | Output as JSON |

---

## `repograph test-map`

Per-file test coverage of entry points.  Sorted by coverage ascending so
gaps are immediately obvious.

```
repograph test-map [PATH] [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--min-eps N` | Only show files with at least N entry points |
| `--uncovered` | Only show files with 0% coverage |
| `--any-call` | Use "any production function called by tests" metric instead of entry-point-only metric |
| `--json` | Output as JSON |

---

## `repograph pathway list`

List all detected pathways sorted by importance.

```
repograph pathway list [PATH] [--include-tests]
```

| Flag | Description |
|------|-------------|
| `--include-tests` | Also show test-entry pathways |

---

## `repograph pathway show NAME`

Print the full context document for a pathway.  Includes BFS-ordered steps (see
the INTERPRETATION block in the doc — not necessarily runtime order), config
dependencies, variable threads, and docstring annotations.

```
repograph pathway show <name> [PATH]
```

---

## `repograph pathway update NAME`

Re-generate the context document for a single pathway.

```
repograph pathway update <name> [--path PATH]
```

---

## `repograph node IDENTIFIER`

Show structured data for a file path or qualified symbol name.

```
repograph node <identifier> [--path PATH]
```

`identifier` can be a relative file path (`src/bots/champion_bot.py`) or
a symbol name (`ChampionBot.on_tick`).

Resolution order is deterministic:
- exact file path
- exact qualified symbol name
- exact simple symbol name
- light normalized symbol forms such as `pkg::Class.method`
- fuzzy fallback

If multiple symbols still match, RepoGraph prints an ambiguity table and exits
non-zero instead of silently picking the first fuzzy match.

---

## `repograph impact SYMBOL`

Blast radius: everything that calls or imports this symbol.

```
repograph impact <symbol> [--depth N] [--path PATH]
```

| Flag | Description |
|------|-------------|
| `--depth / -d N` | Call-graph hops to traverse (default 3) |

`impact` uses the same deterministic symbol resolution rules as `node`.
If the lookup is ambiguous, RepoGraph returns the candidate list and exits
non-zero instead of choosing one arbitrarily.

---

## `repograph query TEXT`

Hybrid search over functions and pathways: keyword ranking, fuzzy name
matching, and optional semantic ranking when embeddings are available.

```
repograph query <text> [--limit N] [--path PATH]
```

---

## `repograph status`

Show index health: node counts, stale artifacts, last sync time.

```
repograph status [PATH]
```

Health status values:
- `ok`: pipeline and hooks completed without recorded plugin failures.
- `degraded`: sync completed but one or more optional hooks/plugins failed; inspect health hook summary.
- `failed`: sync aborted.

---

## `repograph trace install`

Install runtime tracing instrumentation for the next test/run session.
This is an **advanced/manual** workflow; start with `repograph sync --full`
unless you explicitly want to write instrumentation files and inspect raw JSONL
yourself.

```
repograph trace install [PATH] [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--mode / -m` | `pytest` (writes `conftest.py`) or `sitecustomize` (live Python attach bootstrap) |
| `--max-records` | Max records per trace session (0 = unlimited) |
| `--max-mb` | Max per-file trace size in MB before rotation/drop logic |
| `--rotate-files` | Number of extra rotated files when `--max-mb` is hit |
| `--sample-rate` | Call record sampling rate from `0.0` to `1.0` |
| `--include` | Regex include filter over `file::qualified_name` |
| `--exclude` | Regex exclude filter over `file::qualified_name` |

---

## `repograph trace collect`

List collected traces under `.repograph/runtime/`. This is read-only; it does
not merge anything into the graph. Use it when you are manually inspecting
trace volume or payload presence after `trace install` or another custom trace
workflow.

```
repograph trace collect [PATH] [--json]
```

| Flag | Description |
|------|-------------|
| `--json` | Emit trace inventory with record and byte totals |

---

## `repograph trace report`

Summarize runtime overlay diagnostics for already-collected traces. This is
primarily for manual runtime-debugging workflows; the standard full-power path
is still `repograph sync --full`.

```
repograph trace report [PATH] [--top N] [--json]
```

---

## `repograph trace clear`

Delete all trace files under `.repograph/runtime/`.

```
repograph trace clear [PATH] [--yes]
```

| Flag | Description |
|------|-------------|
| `--yes / -y` | Skip confirmation prompt |

---

## `repograph doctor`

Verify Python environment, imports, and optional graph database.

```
repograph doctor [PATH] [--verbose]
```

---

## `repograph events`

Show event publish/subscribe topology extracted by static analyzers.

```
repograph events [PATH] [--json]
```

---

## `repograph interfaces`

Show interface/base classes and discovered implementations.

```
repograph interfaces [PATH] [--json]
```

---

## `repograph deps SYMBOL`

Show constructor dependency hints for a class (from `__init__` parameters).

```
repograph deps <symbol> [--path PATH] [--depth N] [--json]
```

---

## `repograph export`

Export the full graph as JSON.

```
repograph export [PATH] [--output FILE]
```

---

## `repograph watch`

Watch mode: re-sync on file changes.

```
repograph watch [PATH] [--no-git] [--strict]
```

---

## `repograph test`

Run predefined test-matrix profiles from the CLI.

```
repograph test [PATH] [--profile NAME] [EXTRA_PYTEST_ARGS...]
```

| Profile | Selector | Auto-includes new tests? |
|---------|----------|---------------------------|
| `unit-fast` | `tests/unit/ -m "not dynamic and not integration and not requires_mcp"` | Yes |
| `plugin-dynamic` | `tests/ -m "plugin or dynamic"` | Yes |
| `integration` | `tests/integration/` | Yes |
| `full` | `tests/` | Yes |

Example:

```bash
repograph test --profile plugin-dynamic -- -k runtime_overlay
```

Because selection is path/marker-based, new tests are picked up automatically
when they match those selectors.

For the broadest local baseline, the easiest path is still the full workstation
install tier from [`SETUP.md`](SETUP.md). The `full` profile runs the checked-in
Python suite; the separate Pyright quality gate still requires Node.js with
`npx`.

Useful options:

- `--list-profiles` prints the available matrix profiles and exits.
- `--json` emits machine-readable profile/run metadata (CI-friendly).

---

## `repograph mcp`

Start the MCP (Model Context Protocol) server.

```
repograph mcp [PATH] [--port N]
```

---

## `repograph clean`

Delete the `.repograph/` directory entirely.

```
repograph clean [PATH] [--yes / -y] [--dev] [--recursive/--no-recursive]
```

| Flag | Description |
|------|-------------|
| `--yes / -y` | Skip confirmation prompts |
| `--dev / -d` | Also clean common local development artifacts (caches, venv dirs, build outputs, trace helpers) |
| `--recursive / --no-recursive` | With `--dev`, scan whole repo tree (default) or only repo root |
