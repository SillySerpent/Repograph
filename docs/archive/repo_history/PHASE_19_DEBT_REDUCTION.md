# Phase 19 — Debt-reduction pass

## Goal
Keep the post-refactor architecture intact while removing the last sources of “mid-refactor” presentation debt.

## Changes in this pass

### 1. Historical notes
Older phase notes (Phase 2–14) were originally archived under `docs/refactor/archive/`; that tree was later **removed** from the repo to avoid stale content. Use `docs/README.md`, `docs/refactor/PHASE_15`–`PHASE_19`, and `docs/SURFACES.md` for current truth.

### 2. Trust-critical failure reporting tightened
`warn_once(...)` in `repograph.utils.logging` is used by selected high-trust plugin-owned features so repeated best-effort failures do not flood the console:
- pathway building
- pathway-context generation/formatting
- doc-warning export
- agent-guide generation
- invariants export
- modules export
- meta artifact JSON reads

This keeps best-effort behavior while making degradation visible.

### 3. Canonical terminology tightened
Demand-side analyzer plugins now subclass `DemandAnalyzerPlugin` directly instead of relying on the older `AnalyzerPlugin` alias. The alias remains for compatibility, but the canonical package now reads more clearly.

## Non-goals
- no new architecture split
- no removal of compatibility facades that may still be imported externally
- no pipeline behavior changes beyond improved visibility into degraded plugin execution

## Result
The repo should present as a plugin-owned modular system with an explicit compatibility boundary. Historical phase snapshots under `docs/refactor/archive/` were removed later to avoid stale docs; see `docs/README.md`.
