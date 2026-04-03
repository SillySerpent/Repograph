# RepoGraph Accuracy Contract

This document is the active accuracy contract for the current RepoGraph codebase. Treat code and real runtime behavior as primary; this file summarizes the guarantees the current implementation actually aims to provide.

Machine-readable contract version: `repograph.trust.contract.CONTRACT_VERSION`.

## Core guarantees

- Static indexing is the baseline behavior. Every sync rebuilds or updates the static graph from source files first.
- CLI, Python API, and MCP all sit on the same `RepoGraphService` implementation.
- `repograph sync --full` and `RepoGraph.sync(full=True)` use the same runtime-aware full-sync coordinator when `auto_dynamic_analysis` is enabled.
- The runtime coordinator can select one of several modes depending on settings, detected live targets, available inputs, and approval policy: `attach_live_python`, `managed_python_server`, `traced_tests`, `existing_inputs`, or `none`.
- `repograph sync --static-only` is the explicit CLI surface for a pure static rebuild.
- Existing runtime inputs can still be merged on eligible syncs:
  - `.repograph/runtime/*.jsonl` for runtime overlay
  - `coverage.json` at repo root for coverage overlay

## Optional-analysis contract

Runtime and coverage overlays are optional analyses layered on top of the static graph, not baseline guarantees.

- Runtime overlay is only meaningful when trace files exist and the overlay ran.
- Coverage overlay is only meaningful when `coverage.json` exists and the overlay ran.
- `Function.is_covered = false` does **not** prove a function is untested unless coverage overlay was actually applied for the current index.
- Blank or unset optional-analysis fields should be read as “no supporting input was applied”, not as evidence of absence.

RepoGraph surfaces optional-analysis readiness explicitly through:

- `.repograph/meta/health.json`
- `RepoGraphService.status()`
- `summary`, `report`, and CLI sync/status output
- MCP resource `repograph://overview`

Look at `health.analysis_readiness` and `health.dynamic_analysis` before treating runtime-derived or coverage-derived outputs as authoritative.

For the broadest validated local baseline when reproducing the current verified
suite of over **1.24k passing tests**, use the **Full local workstation**
install tier documented in [`SETUP.md`](SETUP.md). Install Node.js as well only
if you plan to run the optional Pyright quality gate.

## Runtime-analysis guarantees

When runtime analysis runs or existing runtime inputs are merged:

- matched functions can be marked with persisted runtime observation fields
- dead-code analysis can suppress stale dead flags for functions observed with a matching `source_hash`
- runtime findings, fallback metadata, attach decisions, and runtime-quality diagnostics may be exported
- runtime provenance is persisted into health/report surfaces

Runtime analysis does **not** guarantee:

- a complete dynamic call graph
- proof that unseen functions are unreachable
- proof that every resolved trace edge is semantically correct beyond the recorded trace match
- universal attach support for arbitrary live processes outside the currently supported target contract

## Coverage overlay guarantees

When `coverage.json` is present and the coverage overlay runs:

- functions receive `is_covered` based on executed lines intersecting the function body
- coverage data becomes queryable through the graph

Coverage overlay does **not** guarantee:

- branch coverage
- path coverage
- proof of production reachability
- meaningful results when `coverage.json` is stale relative to the indexed source tree

## Concurrency and failure contract

- Kuzu remains a single-writer store for `graph.db`.
- Concurrent readers are expected to be safe; sync/clean/write operations still require exclusive writer access.
- `meta/sync.lock` indicates an active sync.
- `health.json` with `status: failed` marks an aborted run.

## Documentation and examples

- Active docs under `docs/` describe current behavior.
- Archived material under `docs/archive/` is historical context only.
- If docs and code disagree, treat code plus health/status output as source of truth.
