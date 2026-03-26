# Surfaces: Python API, CLI, and MCP

RepoGraph exposes one implementation layer — **`RepoGraphService`** (`repograph/services/repo_graph_service.py`) — through three surfaces. They are **not** feature-identical: the **CLI** and **Python API** are broad; **MCP** is a curated subset for AI agents.

## Python API

- Entry point: **`RepoGraph`** (`repograph/api.py`).
- It delegates every attribute to **`RepoGraphService`** via `__getattr__`, so the public surface matches the service’s public methods (sync, pathways, dead_code, full_report, etc.).
- Use this for scripts, tests, and applications that import RepoGraph as a library.

## CLI

- Entry point: Typer app in **`repograph/cli.py`** (`repograph` console script).
- Covers init, sync, report, summary, trace, pathway, node, impact, modules, config, invariants, test-map, mcp, doctor, export, clean, watch, etc.
- Details: **`docs/CLI_REFERENCE.md`**.

### Trace subcommands

Use **`repograph trace collect`** (not `collection`). **`repograph trace install`** sets up instrumentation; **`repograph sync`** overlays traces when `.repograph/runtime/` has data.

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

Resources: `repograph://overview`, `.../pathways`, `.../communities`, `.../schema`.

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
