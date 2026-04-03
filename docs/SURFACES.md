# Surfaces: Python API, CLI, and MCP

RepoGraph exposes one implementation layer — **`RepoGraphService`** (`repograph/services/repo_graph_service.py`) — through three surfaces. They are **not** feature-identical: the **CLI** and **Python API** are broad, while **MCP** is intentionally curated for agent workflows.

All three surfaces live under **`repograph/surfaces/`**. The entry-point for each is:

| Surface | Entry point |
|---------|-------------|
| Python API | `repograph.surfaces.api.RepoGraph` |
| CLI | `repograph.surfaces.cli` (Typer app) |
| MCP | `repograph.surfaces.mcp.server.create_server` |

## Python API

- Entry point: **`RepoGraph`** (`repograph/surfaces/api.py`).
- It delegates every attribute to **`RepoGraphService`** via `__getattr__`, so the public surface matches the service's public methods (sync, pathways, dead_code, full_report, etc.).
- Use this for scripts, tests, and applications embedding RepoGraph.
- When no structured-log session is active, read/query calls open one automatically under
  `.repograph/logs/` and keep it for the lifetime of the `RepoGraph` / `RepoGraphService`
  instance. Using `with RepoGraph(...) as rg:` keeps related queries in the same session.
- `RepoGraph.sync(full=True)` remains a **static** full rebuild and does not run
  tests automatically. If runtime inputs already exist (`.repograph/runtime/*`
  or `coverage.json`), the sync can still merge them. The one-shot automatic
  traced-test workflow is the CLI command **`repograph sync --full`** when
  `auto_dynamic_analysis` is enabled.
- `RepoGraphService.search()` / `RepoGraph.search()` is currently a lighter
  service-side name/keyword lookup. The richer hybrid concept/pathway search
  surface is the CLI command **`repograph query`**.

### Settings methods

`RepoGraph` exposes settings methods that delegate to `repograph.settings`:

```python
rg = RepoGraph("/path/to/repo")
rg.list_config()                          # → dict of all settings
rg.describe_config("include_git")         # → schema/default/current/lifecycle metadata
rg.get_config("include_git")              # → current value
rg.set_config("include_git", False)       # persists a runtime override in .repograph/settings.json
rg.unset_config("include_git")            # removes one runtime override
rg.reset_config()                         # clears overrides, keeps the settings document
```

## CLI

- Entry point: Typer app assembled in **`repograph/surfaces/cli/__init__.py`** (`repograph` console script).
- Commands are split across **`repograph/surfaces/cli/commands/`**: sync, query, report, analysis, trace, config, export, mcp_cmd, admin.
- Output helpers live in **`repograph/surfaces/cli/output.py`**.
- `repograph query` is the richer hybrid search surface: keyword ranking,
  fuzzy name matching, pathway matching, and optional semantic ranking when
  embeddings are available.
- Details: **`docs/CLI_REFERENCE.md`**.

### Advanced trace subcommands

Start with **`repograph sync --full`**. `trace install`, `trace collect`, and
`trace report` are secondary diagnostics for cases where you want explicit
instrumentation control or need to inspect raw trace payloads yourself.

Use **`repograph trace collect`** (not `collection`) when you want a read-only
inventory of already-collected JSONL under **`.repograph/runtime/`**. Manual
traces are merged on the next `sync` when that directory has data. Coverage
overlay is also opportunistic: drop `coverage.json` in the repo root before
sync if you want `is_covered` fields populated.

Long-running live Python processes instrumented via `sitecustomize` publish
their raw trace stream under **`.repograph/runtime/live/`** plus a live-session
marker. `repograph sync --full` can prompt before capturing a current attach
delta from those processes; unattended/API usage should preconfigure
`sync_runtime_attach_policy` to `always` or `never`. `trace collect` reports
live-session traces separately from the
overlay-ready top-level runtime inputs.
If a selected live attach attempt later fails, RepoGraph records that failed
attempt explicitly and then tries the next eligible managed-runtime or traced-
test fallback path instead of pretending attach succeeded.

Instrumentation files (`conftest.py`, `sitecustomize.py`) are written to
**`.repograph/`**, not the repo root. Pytest discovers `.repograph/conftest.py`
automatically when run from the repo root.

## MCP server

- Factory: **`repograph/surfaces/mcp/server.py`** → **`create_server(service: RepoGraphService)`**.
- NL query engine: **`repograph/surfaces/mcp/nl_query.py`** → **`NLQueryEngine`**.
- **Intentionally** exposes fewer tools than the CLI/API. There is **no** `sync` or `full_report` tool on MCP by default.
- **Default alignment:** `get_dead_code` uses the same **`dead_code`** tier default as **`RepoGraphService.dead_code()`** — **`min_tier="probably_dead"`** (see service docstring for tier meanings).
- **`impact`** MCP tool returns a **stable** shape: `symbol`, `will_break`, `may_break`, `warnings`, plus `error` or `ambiguous` when applicable. Symbol lookup now prefers exact file/qualified/simple-name matches before falling back to fuzzy search, and ambiguous matches are surfaced explicitly rather than guessed.

### MCP tools (current)

| Tool | Maps to service (approx.) |
|------|-----------------------------|
| `list_pathways` | `pathways(min_confidence=0.0, include_tests=True)` |
| `get_pathway` | `pathway_document(name)` |
| `get_node` | `node(identifier)` |
| `get_dependents` | `dependents(symbol, depth=depth)` |
| `get_dependencies` | `dependencies(symbol, depth=depth)` |
| `search` | `search(query, limit=limit)` |
| `impact` | `impact(symbol)` (normalized for MCP) |
| `trace_variable` | `trace_variable(variable_name)` |
| `get_entry_points` | `entry_points()` with configured default limit, or `entry_points(limit=limit)` when provided |
| `get_dead_code` | `dead_code()` with service default tier |
| `list_log_sessions` | `list_log_sessions()` |
| `get_errors` | `get_recent_errors(run_id)` |
| `get_log_subsystem` | `get_log_session(run_id, subsystem)` |
| `query_graph` | NL→Cypher translation via Anthropic API (requires `anthropic` + `ANTHROPIC_API_KEY`) |
| `get_config` | Read the current effective value from `.repograph/settings.json` / YAML / defaults |
| `set_config` | Write a runtime override to `.repograph/settings.json` |

Resources: `repograph://overview`, `.../pathways`, `.../communities`, `.../schema`, `.../settings`.

`search` in MCP delegates to the service `search()` method, so it is narrower
than the CLI `repograph query` command. Use `query_graph` when you want
natural-language graph questions rather than name/keyword lookup.

### `query_graph` — natural language queries

Translates a plain-English question about the codebase into a KuzuDB Cypher query and returns results:

```python
result = mcp.query_graph("Which API functions are not covered by tests?")
# {
#   "question": "...",
#   "cypher": "MATCH (f:Function) WHERE f.layer = 'api' AND f.is_covered = false RETURN ...",
#   "explanation": "Returns uncovered API layer functions",
#   "rows": [...],
#   "row_count": 12,
#   "truncated": false,
#   "error": null
# }
```

`is_covered` queries are only meaningful after the coverage overlay has run.
Check `repograph://overview` or `status()["health"]["analysis_readiness"]`
before treating uncovered-function results as authoritative.

The generated Cypher is always read-only — queries containing `CREATE`, `SET`, `DELETE`, `MERGE`, or `DETACH` are refused before execution. Model defaults to `claude-haiku-4-5-20251001`; override with `REPOGRAPH_NL_MODEL` env var.

---

## Naming: parsing vs plugins

| Name | Location | Role |
|------|----------|------|
| **`BaseParser`** | `repograph/parsing/base.py` | Abstract tree-sitter-backed parser for one language; **not** a plugin. |
| **`ParserPlugin`** | `repograph/core/plugin_framework/contracts.py` | Plugin contract: `parse_file`, manifest, hooks. |
| **`ParserAdapter`** | `repograph/plugins/parsers/base.py` | Wraps a `BaseParser` factory so it registers as a `ParserPlugin`. |
| **Language implementations** | `repograph/plugins/parsers/<lang>/` | `build_plugin()` → `ParserAdapter` or custom `ParserPlugin`. |

**`parse_file`** appears at multiple layers: the pipeline calls the **parser registry**'s `parse_file`, which delegates to the right **`ParserPlugin.parse_file`**, which uses **`BaseParser.parse_file`** internally for language parsers.

---

## Diagnostics & impact tags

- **`repograph doctor`** is implemented in **`repograph/diagnostics/env_doctor.py`** (`run_doctor`, `collect_doctor_results`).
- **Impact API warnings** (strings like `static_call_graph_only`) are built in **`repograph/diagnostics/impact_warnings.py`** and attached to **`RepoGraphService.impact()`** / MCP `impact` tool responses.

## Logging

User-visible messages for CLI sync use **`repograph.utils.logging`**: Rich output to **stderr**; this is **not** the stdlib `logging` module. **`warn_once`** deduplicates by the **full message string**. Plugin hook failures in the pipeline use **`warn`** per failure (see `repograph/pipeline/runner_parts/hooks.py`).

Structured observability JSONL now covers more than sync:
- `sync` opens a dedicated pipeline run with per-phase and hook-stage spans.
- CLI read commands that bypass the service wrapper (for example `status`, `doctor`, `config`) open short-lived command sessions.
- Python API and MCP read/query flows open a session automatically when none is active.

## Concurrency note

CLI/API/MCP read surfaces open the existing graph without running schema DDL.
That makes concurrent readers safe with each other, but writes (`sync`, `clean`)
still require exclusive access to the `.repograph/graph.db` directory.
