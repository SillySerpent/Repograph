# RepoGraph

RepoGraph is a local repository analysis project that builds and maintains a graph of a codebase. It is meant to be used against real repositories for code understanding, architecture inspection, impact analysis, and report generation.

RepoGraph has both a static-analysis pipeline and a dynamic-analysis path. A static sync builds the repository graph from the source tree. `repograph sync --full` always rebuilds the static graph, and when `auto_dynamic_analysis` is enabled it will also try to collect traced tests and merge runtime/coverage inputs into the same index.

## What RepoGraph Covers

- Build a repository-wide graph of files, folders, symbols, imports, calls, callback registrations, inheritance links, variable flow, and type-reference hints
- Score likely entry points and assemble pathway documents for important execution flows
- Classify dead code, detect duplicate symbols, surface event topology, and find async task spawn sites
- Show interface-to-implementation relationships, constructor dependencies, communities, and git co-change coupling
- Generate module summaries, config registries, invariants, doc-reference warnings, test-reachability maps, and full reports
- Run demand-side analyzers for private-surface access, config boundary reads, DB shortcuts, UI boundary paths, architecture conformance, class roles, config flow, module signals, and decomposition signals
- Run dynamic analysis from traced tests and merge runtime overlay, coverage overlay, observed runtime findings, and runtime-quality diagnostics into the repository view

## Language And Framework Coverage

- Parser plugins currently cover Python, JavaScript, and TypeScript
- Framework adapters currently cover Flask, FastAPI, React, and Next.js
- HTML files are also scanned for local `<script src>` links so browser-loaded JavaScript can be connected back into the graph
- Shell, HTML, and CSS files are still indexed as repository files and appear in structural outputs even when they are not part of the full symbol graph

## Quick Start

```bash
./setup.sh
./run.sh
```

That path is useful if you want a guided setup and runner. In an interactive
shell, `./setup.sh` now opens a repo-venv-backed subshell automatically after
setup succeeds, and `./run.sh` always prefers `.venv/bin/python` when present.

If you prefer the CLI directly:

```bash
python -m pip install -e .
repograph sync --full
repograph summary
```

If the repo has a local `.venv`, prefer `./run.sh ...` or activate that venv
before using bare `repograph ...` so full-sync runtime analysis runs under the
intended interpreter.

Requirements: Python 3.11+

`repograph init` is optional. It only creates the `.repograph/` layout ahead of time.

## How It Is Usually Used

The usual flow is:

1. Run `repograph sync --full` to build the graph and, when `auto_dynamic_analysis` is enabled, let RepoGraph choose a dynamic-analysis path. If exactly one repo-scoped Python server is already publishing a RepoGraph live trace session, the CLI prompts before attaching; unattended/API usage should preconfigure `sync_runtime_attach_policy` to `always` or `never`. Otherwise RepoGraph reports why attach was unavailable or ambiguous before falling back to a managed runtime or traced tests. If an approved live attach attempt later fails, RepoGraph records that failure explicitly and then tries the next eligible managed-runtime or traced-test path instead of silently pretending attach succeeded.
2. Use commands like `summary`, `modules`, `pathway`, `node`, `query`, and `impact` to inspect the repository from different angles.
3. Re-run `sync` as the codebase changes, or use `watch` during active development.

A simple exploration session might look like this:

```bash
repograph sync --full
repograph summary
repograph modules --issues
repograph pathway list
repograph pathway show <name>
repograph impact <symbol>
```

If you want a purely static rebuild, use:

```bash
repograph sync --static-only
```

## Interfaces

### CLI

The CLI is the broadest day-to-day interface for local work.

- repository lifecycle: `init`, `sync`, `status`, `watch`, `clean`
- exploration: `summary`, `report`, `modules`, `node`, `query`, `impact`
- architecture: `invariants`, `config`, `test-map`, `events`, `interfaces`, `deps`
- pathways: `pathway list`, `pathway show`, `pathway update`
- advanced runtime diagnostics: `trace install`, `trace collect`, `trace report`, `trace clear`
- integrations and diagnostics: `mcp`, `export`, `doctor`, `test`

Full command and flag reference: [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md)

`repograph query` is the richer hybrid search surface in the CLI. It combines keyword search, fuzzy name matching, pathway matching, and optional semantic ranking when embeddings are available.

### Python API

The Python API is useful for scripts, tests, and service integrations:

```python
from repograph.surfaces.api import RepoGraph

with RepoGraph("/path/to/repo") as rg:
    rg.sync(full=True)
    print(rg.pathways())
    print(rg.dead_code())
    print(rg.full_report())
```

`RepoGraph` is a thin facade over the shared `RepoGraphService`, so the API, CLI, and MCP server all sit on the same implementation layer.

`RepoGraph.sync(full=True)` follows the same full-power orchestration path as the CLI when `auto_dynamic_analysis` is enabled. That can include live attach, managed runtime execution, or traced tests depending on the runtime contract and `attach_policy`. If runtime traces or `coverage.json` already exist, sync can still merge those existing inputs when fresh execution is skipped or unavailable.

`RepoGraph.search()` is the lighter service-side search surface. For the richer hybrid search flow, use the CLI `repograph query` command.

Surface details: [`docs/SURFACES.md`](docs/SURFACES.md)

### MCP Server

RepoGraph can also expose a curated MCP surface for AI tools:

```bash
repograph mcp /path/to/repo
```

The MCP surface is intentionally narrower than the CLI and Python API. It focuses on read/query workflows rather than exposing every operational command.

### Interactive Menu

If you want guided terminal use instead of memorizing commands:

```bash
repograph menu
```

The menu provides command browsing, explanations, and run presets for the main workflows.

## Architecture Overview

RepoGraph is organized around one shared service layer and a pipeline that writes into a graph store.

- `RepoGraphService` is the central implementation used by the CLI, Python API, and MCP server.
- Core pipeline phases walk the repository, build file and folder nodes, parse supported languages, resolve imports and calls, detect callback registrations, track inheritance and variables, and write the graph incrementally into Kuzu through `GraphStore`.
- After the core graph is built, plugin hooks run higher-level analyzers, evidence producers, dynamic analyzers, and exporters over the same store.
- When runtime inputs exist, runtime and coverage overlays can be merged onto the static graph so the repository view includes both static structure and observed execution data.

In practice, that means the tool has a fairly clear split:

- the pipeline builds and updates the underlying graph
- the service layer exposes that graph through different user-facing surfaces
- plugins add analysis and export behavior without changing the core entry points

The built-in plugin families registered in [`repograph/plugins/discovery.py`](repograph/plugins/discovery.py) are:

- parsers: `python`, `javascript`, `typescript`
- framework adapters: `flask`, `fastapi`, `react`, `nextjs`
- sync-time analyzers: `pathways`, `dead_code`, `duplicates`, `event_topology`, `async_tasks`
- evidence producers: `declared_dependencies`, `runtime_overlay`
- dynamic analyzers: `runtime_overlay`, `coverage_overlay`, `runtime_quality`
- exporters: `docs_mirror`, `pathway_contexts`, `agent_guide`, `modules`, `pathways`, `summary`, `config_registry`, `invariants`, `event_topology`, `async_tasks`, `entry_points`, `doc_warnings`, `runtime_overlay_summary`, `observed_runtime_findings`, `report_surfaces`
- demand analyzers: `dead_code`, `private_surface_access`, `config_boundary_reads`, `db_shortcuts`, `ui_boundary_paths`, `duplicates`, `contract_rules`, `boundary_shortcuts`, `architecture_conformance`, `boundary_rules`, `class_roles`, `decomposition_signals`, `config_flow`, `module_component_signals`

If you want the internal details, start here:

- pipeline reference: [`docs/PIPELINE.md`](docs/PIPELINE.md)
- surface boundaries: [`docs/SURFACES.md`](docs/SURFACES.md)
- plugin authoring: [`docs/plugins/AUTHORING.md`](docs/plugins/AUTHORING.md)

## Documentation Map

- Start here: [`docs/README.md`](docs/README.md)
- Setup and install tiers: [`docs/SETUP.md`](docs/SETUP.md)
- CLI flags and examples: [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md)
- API, CLI, and MCP boundaries: [`docs/SURFACES.md`](docs/SURFACES.md)
- Pipeline and hooks: [`docs/PIPELINE.md`](docs/PIPELINE.md)
- Accuracy and known limits: [`docs/ACCURACY.md`](docs/ACCURACY.md)
- Config ownership and generated artifact policy: [`docs/CONFIG_HYGIENE.md`](docs/CONFIG_HYGIENE.md)

## License

RepoGraph is licensed under **GNU AGPL v3.0**.  
See [`LICENSE`](LICENSE).

---

## Development Notes

RepoGraph is still under active development, so contributors should expect some internal details and interfaces to continue evolving. If you want the most stable branch for regular use, use `master`; that branch is intended to be the safest default. Other branches may contain work in progress, experiments, or changes that are not ready to depend on yet.
