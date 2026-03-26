# RepoGraph CLI Reference

All commands follow the pattern:

```
repograph <command> [PATH] [OPTIONS]
```

`PATH` defaults to the current working directory when omitted.

### Interactive menu: CLI command browser

`repograph menu` (or `python -m repograph.entry menu`) opens the text UI. The **first option** is **CLI command browser**: it lists every Typer command in categories, explains what each does and common flags (more narrative than `repograph --help` alone), shows examples, and can **Run…** a command for the current repo with **default args**, **named presets** (for example `clean --dev -y`, or `report --pathways 25`), or **custom flags** you type (parsed like a shell). Under each preset, plain-language text explains what that choice does for someone not used to CLI flags; you can still print **`repograph <cmd> --help`** for the full machine-readable flag list.

---

## `repograph init`

Initialize RepoGraph in a repository.  Creates the `.repograph/` directory
structure.  Must be run (or `sync` used directly) before any other command.

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
| `--full` | Force complete rebuild from scratch |
| `--embeddings` | Generate vector embeddings (requires `sentence-transformers`) |
| `--no-git` | Skip git co-change coupling phase (Phase 12) |
| `--strict` | Fail sync if any optional phase errors |
| `--continue-on-error / --no-continue-on-error` | Control optional-phase failure behaviour |
| `--include-tests-config-registry` | Include test files when building `config_registry.json` |
| `--full-with-tests` | Run full sync, install tracer, run `pytest tests`, collect traces, then merge runtime overlay |

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

`report --json` now includes capped-surface metadata (`pathways_summary`, `communities_summary`) and may include `report_warnings` (for example when the latest sync mode is `incremental_traces_only` or health is `degraded`).

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

## `repograph config`

Global config-key → consumer mapping.  Use `--key` to see the blast radius
of renaming a single config value.

```
repograph config [PATH] [--key NAME] [--top N] [--json] [--include-tests]
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

---

## `repograph impact SYMBOL`

Blast radius: everything that calls or imports this symbol.

```
repograph impact <symbol> [--depth N] [--path PATH]
```

| Flag | Description |
|------|-------------|
| `--depth / -d N` | Call-graph hops to traverse (default 3) |

---

## `repograph query TEXT`

Hybrid search: BM25 + fuzzy name matching.

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

```
repograph trace install [PATH] [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--mode / -m` | `pytest` (writes `conftest.py`) or `sitecustomize` |
| `--max-records` | Max records per trace session (0 = unlimited) |
| `--max-mb` | Max per-file trace size in MB before rotation/drop logic |
| `--rotate-files` | Number of extra rotated files when `--max-mb` is hit |
| `--sample-rate` | Call record sampling rate from `0.0` to `1.0` |
| `--include` | Regex include filter over `file::qualified_name` |
| `--exclude` | Regex exclude filter over `file::qualified_name` |

---

## `repograph trace collect`

List collected traces under `.repograph/runtime/`.

```
repograph trace collect [PATH] [--json]
```

| Flag | Description |
|------|-------------|
| `--json` | Emit trace inventory with record and byte totals |

---

## `repograph trace report`

Summarize runtime overlay diagnostics and persistence impact.

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
