# Config Hygiene and Ownership

This document defines how to treat runtime configuration, test-only configuration,
and generated RepoGraph metadata without mixing concerns.

## Settings system overview

RepoGraph settings are resolved in a strict priority order (later wins):

1. **Defaults** — hardcoded in the `repograph/settings/` package (`Settings` dataclass).
2. **Root-level YAML** — `repograph.index.yaml` in the repo root (power-user overrides; optional).
3. **`.repograph/` YAML** — `.repograph/repograph.index.yaml` (project-level overrides; wins over root YAML).
4. **`settings.json`** — `.repograph/settings.json` (highest priority; written by CLI, API, and MCP).

The primary interface for persistent settings is the CLI/API/MCP. YAML is a secondary,
human-editable layer for static options like `exclude_dirs`, `sync_test_command`,
and managed-runtime orchestration settings.

### Managing settings via CLI

```bash
repograph config list              # show all settings and current values
repograph config get include_git   # read one setting
repograph config describe include_git  # show schema/default/lifecycle details
repograph config set include_git false  # persist to .repograph/settings.json
repograph config unset include_git      # remove one runtime override
repograph config reset             # clear overrides, refresh the settings document
```

### Managing settings via Python API

```python
from repograph.surfaces.api import RepoGraph
rg = RepoGraph("/path/to/repo")
rg.list_config()                          # → dict
rg.get_config("include_git")              # → True
rg.set_config("include_git", False)       # writes .repograph/settings.json
rg.reset_config()                         # clears overrides, keeps the settings document
```

Managed runtime example:

```python
rg.set_config("sync_runtime_server_command", ["python", "app.py"])
rg.set_config("sync_runtime_probe_url", "http://127.0.0.1:8000/health")
rg.set_config("sync_runtime_scenario_urls", ["/", "/health"])
rg.set_config("sync_runtime_scenario_driver_command", ["python", "tools/runtime_driver.py"])
```

Live-attach policy example for unattended API use:

```python
rg.set_config("sync_runtime_attach_policy", "never")
# or:
rg.sync(full=True, attach_policy="always")
```

### `repograph.index.yaml` — YAML overrides

`repograph.index.yaml` supports a subset of settings that are naturally expressed
as static project config. Run `repograph init` to write a commented-out placeholder.
`repograph init` also creates `.repograph/settings.json` as a generated settings
document so the runtime settings layer is visible without letting metadata
override defaults or YAML simply by existing.

Supported keys:

| Key | Type | Notes |
|-----|------|-------|
| `exclude_dirs` | list of strings | Extra directories to skip during indexing |
| `disable_auto_excludes` | bool | Disable automatic vendored-repograph exclusion |
| `sync_test_command` | list of strings | Override auto-detected pytest command |
| `sync_runtime_server_command` | list of strings | Optional Python server argv to run under trace during `sync --full` |
| `sync_runtime_probe_url` | string | HTTP readiness probe for the managed traced server |
| `sync_runtime_scenario_urls` | list of strings | Ordered HTTP URLs or path fragments to request after the probe succeeds |
| `sync_runtime_scenario_driver_command` | list of strings | Optional scenario-driver argv for richer POST/cookie/browser flows after readiness succeeds |
| `sync_runtime_ready_timeout` | integer | Seconds to wait for the managed traced server to become reachable |
| `sync_runtime_attach_policy` | `prompt`, `always`, or `never` | Whether `sync --full` prompts before live attach, attaches automatically, or always falls back |
| `doc_symbols_flag_unknown` | bool | Phase 15 symbol reference checking |

Unknown keys produce a warning; they are ignored (forward compatibility).

## Three-Layer Ownership Model

### 1) Runtime / Product Configuration (authoritative)

- Managed via CLI (`repograph config set/get/describe/unset/reset`), Python API, or MCP tools.
- Persisted under the `runtime_overrides` section in `.repograph/settings.json`.
- YAML in `.repograph/repograph.index.yaml` or repo-root `repograph.index.yaml` is read-only from a lifecycle perspective — it is never written back by the tool.

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
- The `repograph config-registry` command exposes this view.

## Standard Commands

### Canonical product sync

```bash
repograph sync --full
```

This is the normal operator path for RepoGraph as a whole. It keeps config
registry generation aligned with the rest of the full repository view while
still allowing runtime and coverage evidence when that workflow is enabled.

### Pure static config-focused sync

```bash
repograph sync --static-only
```

Use this when you intentionally want to inspect config-oriented outputs without
automatic runtime execution or overlay merge.

### Audit sync including test config usage

```bash
repograph sync --static-only --include-tests-config-registry
```

## CI Guidance (separate intent)

Keep the normal product view and the wider audit view separate in CI:

- Main CI / PR guardrail:
  - `repograph sync --full`
- Optional pure-static guardrail when you explicitly want no runtime execution:
  - `repograph sync --static-only`
- Optional audit job (nightly or opt-in):
  - `repograph sync --static-only --include-tests-config-registry`

This avoids polluting production config inventories with test-only keys while
still allowing deep audit coverage when needed.

## Generated Artifact Boundaries

- `.repograph/` is generated data and should remain ignored by git.
- `config_registry.json`, `event_topology.json`, `async_tasks.json` are reports,
  not source-of-truth config files.
- `settings.json` inside `.repograph/` is an exception: it is intentionally written
  by the tool as a self-describing settings document, and should typically be gitignored
  alongside the rest of `.repograph/`.

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
- Document new production config keys in the `repograph/settings/` package (the `Settings` dataclass and `INDEX_YAML_SCHEMA`).
