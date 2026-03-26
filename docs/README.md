# RepoGraph documentation index

RepoGraph indexes a repository into a graph database and exposes pathways, call graphs, dead code, and related signals via **CLI**, **Python API**, and an optional **MCP** server.

## Start here

| Topic | Document |
|--------|----------|
| Install & optional extras | [`SETUP.md`](SETUP.md) |
| CLI commands & flags | [`CLI_REFERENCE.md`](CLI_REFERENCE.md) |
| Pipeline phases (p01–p14+) | [`PIPELINE.md`](PIPELINE.md) |
| Authoring plugins | [`plugins/AUTHORING.md`](plugins/AUTHORING.md) |
| Plugin discovery order | [`plugins/DISCOVERY.md`](plugins/DISCOVERY.md) |
| Hooks vs experimental phases | [`architecture/PLUGIN_PHASES_AND_HOOKS.md`](architecture/PLUGIN_PHASES_AND_HOOKS.md) |
| Accuracy expectations | [`ACCURACY.md`](ACCURACY.md), [`ACCURACY_CONTRACT.md`](ACCURACY_CONTRACT.md) |
| **API vs CLI vs MCP** (surfaces & naming) | [`SURFACES.md`](SURFACES.md) |
| Refactor milestones & integration boundary | [`refactor/INDEX.md`](refactor/INDEX.md), [`refactor/INTEGRATION_SURFACE.md`](refactor/INTEGRATION_SURFACE.md) |
| Agent workflow (humans & tools) | [`AGENT_USAGE.md`](AGENT_USAGE.md) |
| Running tests & pytest markers | [`../tests/README.md`](../tests/README.md) |

## For AI assistants

1. Read [`SURFACES.md`](SURFACES.md) so you know which **RepoGraphService** methods exist on each surface (CLI exposes most; MCP exposes a **subset**).
2. Plugin contracts live in `repograph/core/plugin_framework/contracts.py`; hooks in `hooks.py`.
3. Built-in plugins live under `repograph/plugins/` — see [`plugins/README.md`](../repograph/plugins/README.md).
4. After indexing, repo-local hints may appear under `.repograph/AGENT_GUIDE.md` (generated).

## Refactor / history

Historical phase-by-phase notes under `docs/refactor/archive/` were **removed** to avoid stale content. Current architecture notes are **`refactor/PHASE_15`–`PHASE_19`** and the index above.
