# Phase 17 — Plugin Ownership Closure

## Goal
Make plugin folders the **physical source of truth** for their feature logic, not
just the registration point.

## Rule enforced
For a plugin-owned feature, the owning plugin package now contains:
- the plugin definition
- the implementation
- feature-specific helpers
- feature-specific generators/formatters/scorers/traversal code

Anything outside the plugin package is now one of:
- core shared infrastructure
- generic cross-feature utilities
- compatibility wrappers for older import paths

## Work completed

### 1. Pathways moved under the pathways plugin package
Canonical implementations now live in:
- `repograph/plugins/static_analyzers/pathways/assembler.py`
- `repograph/plugins/static_analyzers/pathways/curator.py`
- `repograph/plugins/static_analyzers/pathways/pathway_bfs.py`
- `repograph/plugins/static_analyzers/pathways/scorer.py`
- `repograph/plugins/static_analyzers/pathways/descriptions.py`

Older top-level `repograph/pathways/*` and `repograph/context/*` shim modules
were **removed** once imports pointed at the plugin packages above.

### 2. Pathway-context generation moved under the exporter plugin package
Canonical implementations now live in:
- `repograph/plugins/exporters/pathway_contexts/budget.py`
- `repograph/plugins/exporters/pathway_contexts/formatter.py`
- `repograph/plugins/exporters/pathway_contexts/generator.py`

Older `repograph/context/*` shims were removed in favor of the exporter paths
above.

### 3. Agent-guide generation moved under the exporter plugin package
Canonical implementation now lives in:
- `repograph/plugins/exporters/agent_guide/generator.py`

The older `repograph/mcp/agent_guide.py` shim was removed; use the exporter
plugin package above.

## Why this matters
Before this pass, the codebase still implied that plugins owned features while
major feature logic remained elsewhere. That made the architecture look
mid-refactor.

After this pass, the physical package layout matches the intended design more
closely: plugin folders are the homes of the features they extend.

## Compatibility debt
Top-level pathway/context/agent-guide shim **directories are gone**; any
external code should import from `repograph.plugins.static_analyzers.pathways`,
`repograph.plugins.exporters.pathway_contexts`, or `repograph.plugins.exporters.agent_guide`
as appropriate.
