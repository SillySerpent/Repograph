# Surfaces: Python API, CLI, and MCP

RepoGraph exposes one implementation layer — **`RepoGraphService`** (`repograph/services/repo_graph_service.py`) — through three surfaces. They are **not** feature-identical: the **CLI** and **Python API** are broad, while **MCP** is intentionally curated for agent workflows.

## Python API

- Entry point: **`RepoGraph`** (`repograph/api.py`).
- It delegates every attribute to **`RepoGraphService`** via `__getattr__`, so the public surface matches the service’s public methods (sync, pathways, dead_code, full_report, etc.).
- Use this for scripts, tests, and applications embedding RepoGraph.
- When no structured-log session is active, read/query calls open one automatically under
  `.repograph/logs/` and keep it for the lifetime of the `RepoGraph` / `RepoGraphService`
  instance. Using `with RepoGraph(...) as rg:` keeps related queries in the same session.
- `RepoGraph.sync(full=True)` remains a **static** full rebuild. The one-shot
  automatic runtime-overlay workflow is currently the CLI command
  **`repograph sync --full`**.

## CLI

- Entry point: Typer app in **`repograph/cli.py`** (`repograph` console script).
- Covers init, sync, report, summary, trace, pathway, node, impact, modules, config, invariants, test-map, mcp, doctor, export, clean, watch, etc.
- Details: **`docs/CLI_REFERENCE.md`**.

### Trace subcommands

Use **`repograph trace collect`** (not `collection`). `trace install` is now an
advanced/manual path for writing instrumentation files yourself; routine
runtime overlay happens automatically on **`repograph sync --full`**. Manual
traces are merged on the next `sync` when `.repograph/runtime/` has data.

## MCP server

- Factory: **`repograph/mcp/server.py`** → **`create_server(service: RepoGraphService)`**.
- **Intentionally** exposes fewer tools than the CLI/API. There is **no** `sync` or `full_report` tool on MCP by default.
- **Default alignment:** `get_dead_code` uses the same **`dead_code`** tier default as **`RepoGraphService.dead_code()`** — **`min_tier="probably_dead"`** (see service docstring for tier meanings).
- **`impact`** MCP tool returns a **stable** shape: `symbol`, `will_break`, `may_break`, `warnings`, plus `error` or `ambiguous` when applicable.

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
| `get_entry_points` | `entry_points(limit=limit)` |
| `get_dead_code` | `dead_code()` with service default tier |
| `list_log_sessions` | `list_log_sessions()` |
| `get_errors` | `get_recent_errors(run_id)` |
| `get_log_subsystem` | `get_log_session(run_id, subsystem)` |
| `query_graph` | NL→Cypher translation via Anthropic API (requires `anthropic` + `ANTHROPIC_API_KEY`) |

Resources: `repograph://overview`, `.../pathways`, `.../communities`, `.../schema`.

### `query_graph` — natural language queries (Block I5)

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

The generated Cypher is always read-only — queries containing `CREATE`, `SET`, `DELETE`, `MERGE`, or `DETACH` are refused before execution. Model defaults to `claude-haiku-4-5-20251001`; override with `REPOGRAPH_NL_MODEL` env var.

---

## Naming: parsing vs plugins

| Name | Location | Role |
|------|----------|------|
| **`BaseParser`** | `repograph/parsing/base.py` | Abstract tree-sitter-backed parser for one language; **not** a plugin. |
| **`ParserPlugin`** | `repograph/core/plugin_framework/contracts.py` | Plugin contract: `parse_file`, manifest, hooks. |
| **`ParserAdapter`** | `repograph/plugins/parsers/base.py` | Wraps a `BaseParser` factory so it registers as a `ParserPlugin`. |
| **Language implementations** | `repograph/plugins/parsers/<lang>/` | `build_plugin()` → `ParserAdapter` or custom `ParserPlugin`. |

**`parse_file`** appears at multiple layers: the pipeline calls the **parser registry**’s `parse_file`, which delegates to the right **`ParserPlugin.parse_file`**, which uses **`BaseParser.parse_file`** internally for language parsers.

---

## Diagnostics & impact tags

- **`repograph doctor`** is implemented in **`repograph/diagnostics/env_doctor.py`** (`run_doctor`, `collect_doctor_results`).
- **Impact API warnings** (strings like `static_call_graph_only`) are built in **`repograph/diagnostics/impact_warnings.py`** and attached to **`RepoGraphService.impact()`** / MCP `impact` tool responses.

## Logging

User-visible messages for CLI sync use **`repograph.utils.logging`**: Rich output to **stderr**; this is **not** the stdlib `logging` module. **`warn_once`** deduplicates by the **full message string**. Plugin hook failures in the pipeline use **`warn`** per failure (see `repograph/pipeline/runner.py`).

Structured observability JSONL now covers more than sync:
- `sync` opens a dedicated pipeline run with per-phase and hook-stage spans.
- CLI read commands that bypass the service wrapper (for example `status`, `doctor`, `config --include-tests`) open short-lived command sessions.
- Python API and MCP read/query flows open a session automatically when none is active.

## Concurrency note

CLI/API/MCP read surfaces open the existing graph without running schema DDL.
That makes concurrent readers safe with each other, but writes (`sync`, `clean`)
still require exclusive access to the `.repograph/graph.db` directory.
