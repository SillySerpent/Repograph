# Surfaces: Python API, CLI, and MCP

RepoGraph exposes one implementation layer, **`RepoGraphService`** (`repograph/services/repo_graph_service.py`), through three user-facing surfaces. They are related, but not feature-identical: the CLI and Python API are broad, while MCP is intentionally curated for agent workflows.

For the broadest validated local baseline across those surfaces, use the
**Full local workstation** install tier described in [`SETUP.md`](SETUP.md) if
you want the best chance of reproducing the current verified suite of over
**1.24k passing tests** locally. Install Node.js as well only if you plan to
run the optional Pyright quality gate.

## Entrypoint map

The installed console script is `repograph = repograph.entry:main`.

`repograph.entry` dispatches to:

- `repograph.surfaces.cli` for the Typer CLI
- `repograph.interactive.main` for `repograph menu`
- `setup-verify` helpers for editable-install verification

The surface entrypoints in the codebase are:

| Surface | Entry point |
|---|---|
| Python API | `repograph.surfaces.api.RepoGraph` |
| CLI | `repograph.surfaces.cli` |
| MCP | `repograph.surfaces.mcp.server.create_server` |

All three sit on top of the same `RepoGraphService`.

## Python API

- Entry point: [`repograph/surfaces/api.py`](../repograph/surfaces/api.py)
- `RepoGraph` delegates to `RepoGraphService`, so the public API tracks service methods such as `sync`, `pathways`, `dead_code`, `impact`, and `full_report`
- Best fit for scripts, tests, and applications embedding RepoGraph directly
- Read/query calls open an observability session automatically when none is active and keep it for the lifetime of the `RepoGraph` / `RepoGraphService` instance

### Full sync behavior in the API

`RepoGraph.sync(full=True)` now follows the same runtime-aware full-sync path as the CLI when `auto_dynamic_analysis` is enabled. That means a full API sync can:

- resolve a runtime plan through the same orchestration layer as the CLI
- reuse existing runtime/coverage inputs
- launch a managed traced runtime
- run traced tests
- attach to an eligible live traced Python target when the runtime contract and `attach_policy` allow it

Use `attach_policy="always"` or `attach_policy="never"` for unattended API callers that should not rely on a CLI confirmation prompt.

### Settings methods

`RepoGraph` also exposes settings methods that delegate to `repograph.settings`:

```python
rg = RepoGraph("/path/to/repo")
rg.list_config()
rg.describe_config("include_git")
rg.get_config("include_git")
rg.set_config("include_git", False)
rg.unset_config("include_git")
rg.reset_config()
```

## CLI

- Entry point: [`repograph/surfaces/cli/__init__.py`](../repograph/surfaces/cli/__init__.py)
- Typer app assembly: [`repograph/surfaces/cli/app.py`](../repograph/surfaces/cli/app.py)
- Commands are split across [`repograph/surfaces/cli/commands/`](../repograph/surfaces/cli/commands/)
- Output helpers live in [`repograph/surfaces/cli/output.py`](../repograph/surfaces/cli/output.py)

Stable day-to-day command families:

- sync and admin: `init`, `sync`, `status`, `watch`, `clean`, `doctor`, `test`
- exploration: `summary`, `report`, `modules`, `node`, `query`, `impact`
- architecture and evidence: `config`, `config-registry`, `invariants`, `test-map`, `events`, `interfaces`, `deps`
- pathways: `pathway list`, `pathway show`, `pathway update`
- runtime diagnostics: `trace install`, `trace collect`, `trace report`, `trace clear`
- integrations: `mcp`, `export`

### Full sync contract

`repograph sync --full` is the canonical full-power operator path. When `auto_dynamic_analysis` is enabled, it uses the runtime orchestration layer to choose among:

- attach to one safe repo-scoped live traced Python target
- launch a managed traced Python server from settings
- run a traced test command
- merge existing runtime and coverage inputs when fresh execution is skipped or unavailable
- complete statically while recording why runtime analysis did not run

`repograph sync --static-only` is the explicit static-only override.

### Trace subcommands

Start with `repograph sync --full`. `trace install`, `trace collect`, and `trace report` are secondary diagnostics for cases where you want manual instrumentation control, want to inspect raw trace payloads, or are debugging automatic runtime capture.

- `trace install` writes instrumentation under `.repograph/`
- `trace collect` inventories collected JSONL inputs, including live-session traces
- `trace report` inspects overlay findings without requiring a new full rebuild

Coverage overlay is also opportunistic: if `coverage.json` exists at the repo root when sync runs, RepoGraph can merge coverage evidence alongside runtime evidence.

## MCP server

- Factory: [`repograph/surfaces/mcp/server.py`](../repograph/surfaces/mcp/server.py)
- NL query engine: [`repograph/surfaces/mcp/nl_query.py`](../repograph/surfaces/mcp/nl_query.py)
- MCP intentionally exposes fewer tools than the CLI/API; there is no general `sync` or `full_report` tool by default
- Default transport is stdio; `repograph mcp --port <n>` switches to streamable HTTP

### MCP tools and resources

Current MCP tool families include:

- pathway and symbol reads: `list_pathways`, `get_pathway`, `get_node`, `search`
- impact and graph relations: `impact`, `get_dependents`, `get_dependencies`, `trace_variable`, `get_entry_points`, `get_dead_code`
- settings access: `get_config`, `describe_config`, `set_config`, `unset_config`
- observability access: `list_log_sessions`, `get_errors`, `get_log_subsystem`
- NL graph querying: `query_graph`

Current resources include:

- `repograph://overview`
- `repograph://pathways`
- `repograph://communities`
- `repograph://schema`
- `repograph://settings`

`impact` returns a stable MCP-normalized shape with `symbol`, `will_break`, `may_break`, `warnings`, and optional `error` / `ambiguous`.

## Naming: parsing vs plugins

| Name | Location | Role |
|---|---|---|
| `BaseParser` | `repograph/parsing/base.py` | Abstract tree-sitter-backed parser for one language; not a plugin |
| `ParserPlugin` | `repograph/core/plugin_framework/contracts.py` | Plugin contract with `parse_file`, manifest, and hooks |
| `ParserAdapter` | `repograph/plugins/parsers/base.py` | Wraps a `BaseParser` factory so it registers as a `ParserPlugin` |
| Language implementations | `repograph/plugins/parsers/<lang>/` | `build_plugin()` returns a `ParserAdapter` or custom `ParserPlugin` |

`parse_file` appears at multiple layers: the pipeline calls the parser registry’s `parse_file`, which delegates to the right `ParserPlugin.parse_file`, which uses `BaseParser.parse_file` internally for language-specific parsing.

## Diagnostics and logging

- `repograph doctor` lives in `repograph/diagnostics/env_doctor.py`
- Impact warnings such as `static_call_graph_only` are built in `repograph/diagnostics/impact_warnings.py`
- User-visible CLI sync output uses `repograph.utils.logging` for Rich-rendered messages
- Structured observability JSONL covers sync, CLI read commands, Python API reads, and MCP tool calls under `.repograph/logs/`

## Concurrency note

CLI, API, and MCP read surfaces open the existing graph without running schema DDL. Concurrent readers are expected to be safe with each other, but writes (`sync`, `clean`, config mutations that trigger writes) still require exclusive writer access to `.repograph/graph.db`.
