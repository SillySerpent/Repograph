# Config Hygiene and Ownership

This document defines how to treat runtime configuration, test-only configuration,
and generated RepoGraph metadata without mixing concerns.

## Three-Layer Ownership Model

### 1) Runtime / Product Configuration (authoritative)

- Lives in repo-root config files and runtime config modules.
- Controls production behavior.
- Is the only configuration surface considered canonical for deployments.

### 2) Test Configuration (non-production)

- Lives in `tests/` fixtures and test helper code.
- Exists for tests, mocks, and local verification flows.
- Must not be treated as production configuration.

### 3) Generated RepoGraph Artifacts (derived, non-authoritative)

- Lives under `.repograph/meta/*.json`.
- Is generated output from analysis/export plugins.
- Never edit by hand; regenerate via `repograph sync`.

## `config_registry.json` Scope Policy

RepoGraph can build a config-key registry (`.repograph/meta/config_registry.json`)
from production files, optionally including test files.

- Default: `include_tests_config_registry=False` (production-safe baseline).
- Optional audit mode: include tests to inspect full config usage in all code.

### What `--include-tests-config-registry` does

- When omitted: test files are excluded from config registry extraction.
- When set: test files are included; output may include test-only keys.
- This flag affects config registry export only. It does not alter runtime code.

## Standard Commands

### Production-oriented sync (recommended default)

```bash
repograph sync --static-only
```

### Audit sync including test config usage

```bash
repograph sync --static-only --include-tests-config-registry
```

## CI Guidance (separate intent)

Keep production and audit views separate in CI:

- Main CI / PR guardrail:
  - `repograph sync --static-only`
- Optional audit job (nightly or opt-in):
  - `repograph sync --static-only --include-tests-config-registry`

This avoids polluting production config inventories with test-only keys while
still allowing deep audit coverage when needed.

## Generated Artifact Boundaries

- `.repograph/` is generated data and should remain ignored by git.
- `config_registry.json`, `event_topology.json`, `async_tasks.json` are reports,
  not source-of-truth config files.

## Troubleshooting Empty Meta Outputs

### `config_registry.json` is empty (`{}`)

This can be valid. Check:

- `.repograph/meta/config_registry_diagnostics.json`
- If status is `empty_valid` and `errors` is empty, exporter ran correctly but
  found no matching keys under current extraction scope.

### `event_topology.json` or `async_tasks.json` is empty (`[]`)

This usually means no matching patterns were detected in the current source
snapshot. It does not automatically indicate a pipeline failure.

## Lightweight Team Validation Step

After sync, quickly validate diagnostics:

```bash
python - <<'PY'
import json, pathlib
p = pathlib.Path(".repograph/meta/config_registry_diagnostics.json")
if not p.exists():
    raise SystemExit("missing diagnostics file")
d = json.loads(p.read_text(encoding="utf-8"))
print("status:", d.get("status"), "errors:", len(d.get("errors", [])))
PY
```

## Contributor Guidance

When adding new configuration usage:

- Put production keys in runtime/product config surfaces.
- Keep test-only config in `tests/`.
- Do not treat `.repograph/meta/*` as editable config.
- Document new production config keys in appropriate runtime docs.
