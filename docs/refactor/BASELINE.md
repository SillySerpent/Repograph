# Baseline

This workspace treats `meridian_v3` as the source of truth.

## RepoGraph baseline observations

- Meridian bundles RepoGraph under `tools/repograph`.
- Meridian currently relies on RepoGraph through Electron IPC at `src/main/ipc/repograph.ts`.
- Meridian depends on a small RepoGraph surface:
  - `python -m repograph init`
  - `python -m repograph sync --full`
  - `python -m repograph summary --json`
  - `python -m repograph modules --json`
  - `python -m repograph pathway show <name>`
  - `from repograph.api import RepoGraph` with `.pathways()` and `.dead_code()`

## Hygiene baseline

- archive junk was present (`.DS_Store`)
- no root `.gitignore`
- setup path was documented in README/CONTRIBUTING but not centralized in a dedicated setup doc
- no Meridian-specific contract test suite

## Immediate refactor scope

This milestone implements the safety-rail foundation only:
- workspace cleanup
- environment hardening
- setup/bootstrap scripts
- Meridian contract test scaffolding
- refactor tracking docs

No broad architectural moves are made in this milestone.
