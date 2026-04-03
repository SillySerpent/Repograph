# RepoGraph

RepoGraph is a local repository-intelligence tool that builds and maintains a graph-backed model of a codebase for code understanding, architecture inspection, impact analysis, and AI-assisted context gathering.

RepoGraph is static-first, but `repograph sync --full` is the canonical full-power workflow. A full sync always rebuilds the static graph first. When `auto_dynamic_analysis` is enabled, RepoGraph then resolves the safest runtime path it can for the current repo: attaching to an eligible live traced Python server, launching a managed traced Python server, running traced tests, or merging existing runtime and coverage inputs when fresh execution is unavailable. `repograph sync --static-only` remains the explicit pure-static path when you want a rebuild with no automatic runtime execution or overlay merge.

> Verified test baseline: the checked-in suite currently contains over 1.24k tests, and the latest full-suite run is green.

## What RepoGraph Covers

- Build a repository-wide graph of files, folders, symbols, imports, calls, callback registrations, inheritance links, variable flow, and type-reference hints
- Score likely entry points and assemble pathway documents for important execution flows
- Classify dead code, detect duplicate symbols, surface event topology, and find async task spawn sites
- Show interface-to-implementation relationships, constructor dependencies, communities, and git co-change coupling
- Generate module summaries, config registries, invariants, doc-reference warnings, test-reachability maps, and full reports
- Run demand-side analyzers for private-surface access, config boundary reads, DB shortcuts, UI boundary paths, architecture conformance, class roles, config flow, module signals, and decomposition signals
- Merge runtime overlay, coverage overlay, observed runtime findings, and runtime-quality diagnostics into the same repository view

## Runtime And Dynamic Analysis

RepoGraph’s runtime-aware full sync is not a sidecar toy feature. On merged master, the full-sync path can:

- detect repo-scoped live traced Python servers and prompt before attaching in the CLI
- launch a managed traced Python server from configured settings, wait for readiness, and drive scenario URLs or a scenario-driver command
- auto-detect a traced test command and run it under the repo interpreter
- merge existing `.repograph/runtime/*.jsonl` and `coverage.json` inputs when fresh execution is skipped or unavailable
- persist runtime provenance, attach decisions, scenario activity, fallback behavior, and overlay readiness into `health.json`, `status`, `summary`, and `report`

Static analysis still remains the baseline. Runtime and coverage evidence augment the graph; they do not replace it.

## Language And Framework Coverage

- Parser plugins currently cover Python, JavaScript, and TypeScript
- Framework adapters currently cover Flask, FastAPI, React, and Next.js
- HTML files are also scanned for local `<script src>` links so browser-loaded JavaScript can be connected back into the graph
- Shell, HTML, and CSS files are still indexed as repository files and appear in structural outputs even when they are not part of the full symbol graph

## Quick Start

Repo-local bootstrap:

```bash
./setup.sh
./run.sh sync --full
./run.sh summary
```

That path gives you the safest interpreter behavior because `./setup.sh` prepares the repo-local `.venv`, and `./run.sh` always prefers `.venv/bin/python` when present.

If you prefer the CLI directly:

```bash
python -m pip install -e ".[dev,community]"
repograph sync --full
repograph summary
repograph report
```

If you want the broadest validated local environment and the best chance of
matching the current verified baseline of over **1.24k passing tests**, prefer
the **Full local workstation** tier instead:

```bash
python -m pip install -e ".[dev,community,mcp,templates,embeddings]"
```

Install Node.js as well if you plan to run the optional Pyright quality gate.

Requirements: Python 3.11+. `repograph init` is optional; it only creates the `.repograph/` layout ahead of time.

## Typical Workflow

The normal workflow is:

1. Run `repograph sync --full` to rebuild the graph and let RepoGraph resolve the best available runtime path for the repo.
2. Use `summary`, `report`, `modules`, `pathway`, `node`, `query`, and `impact` to inspect the repository from different angles.
3. Re-run `sync` as the codebase changes, or use `watch` during active development.

A routine exploration session looks like:

```bash
repograph sync --full
repograph summary
repograph modules --issues
repograph pathway list
repograph impact <symbol>
repograph report
```

If you explicitly want a pure static rebuild:

```bash
repograph sync --static-only
```

## Interfaces

### CLI

The CLI is the broadest day-to-day interface for local work.

- repository lifecycle: `init`, `sync`, `status`, `watch`, `clean`
- exploration: `summary`, `report`, `modules`, `node`, `query`, `impact`
- architecture: `config`, `config-registry`, `invariants`, `test-map`, `events`, `interfaces`, `deps`
- pathways: `pathway list`, `pathway show`, `pathway update`
- runtime diagnostics: `trace install`, `trace collect`, `trace report`, `trace clear`
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

`RepoGraph` is a thin facade over the shared `RepoGraphService`, so the API, CLI, and MCP server all sit on the same implementation layer. `RepoGraph.sync(full=True)` follows the same runtime-aware orchestration path as the CLI when `auto_dynamic_analysis` is enabled, and API callers can override attach behavior per call with `attach_policy`.

Surface details: [`docs/SURFACES.md`](docs/SURFACES.md)

### MCP Server

RepoGraph can also expose a curated MCP surface for AI tools:

```bash
repograph mcp /path/to/repo
```

The MCP surface is intentionally narrower than the CLI and Python API. It focuses on read/query workflows, observability access, and settings inspection rather than exposing every operational command.

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
- `run_full_pipeline_with_runtime_overlay()` adds runtime planning and execution on top of the full static rebuild path.
- Plugin hooks then run higher-level analyzers, evidence producers, dynamic analyzers, and exporters over the same store.
- Health, trust, runtime-analysis, and readiness metadata are persisted so `status`, `summary`, `report`, and MCP consumers can tell what kind of evidence actually backed a result.

In practice, that means the tool has a clean split:

- the pipeline builds and updates the graph
- the runtime layer augments it with observed evidence when available
- the service layer exposes the result through different user-facing surfaces
- plugins extend analysis and export behavior without changing the core entry points

## Documentation Map

- Start here: [`docs/README.md`](docs/README.md)
- Setup and install tiers: [`docs/SETUP.md`](docs/SETUP.md)
- CLI flags and examples: [`docs/CLI_REFERENCE.md`](docs/CLI_REFERENCE.md)
- API, CLI, and MCP boundaries: [`docs/SURFACES.md`](docs/SURFACES.md)
- Pipeline and runtime orchestration: [`docs/PIPELINE.md`](docs/PIPELINE.md)
- Accuracy and known limits: [`docs/ACCURACY.md`](docs/ACCURACY.md)
- Config ownership and generated artifact policy: [`docs/CONFIG_HYGIENE.md`](docs/CONFIG_HYGIENE.md)
- Contribution workflow: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Test layout and markers: [`tests/README.md`](tests/README.md)

## License

RepoGraph is licensed under **GNU AGPL v3.0**. See [`LICENSE`](LICENSE).

---

## Development Notes

RepoGraph is still under active development, so contributors should expect some internal details and interfaces to continue evolving. If docs and code disagree, treat the current code, `health.json`, CLI help, and `status` / `summary` / `report` output as source of truth.
