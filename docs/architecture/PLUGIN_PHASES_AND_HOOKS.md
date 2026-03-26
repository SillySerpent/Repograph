# Plugin hooks and experimental pipeline phases

## Hook catalog (`HookName`)

Lifecycle hooks are defined as literals in
[`repograph/core/plugin_framework/contracts.py`](../../repograph/core/plugin_framework/contracts.py)
(`HookName`). The runner and CLI dispatch these through
[`PluginHookScheduler`](../../repograph/core/plugin_framework/hooks.py).

Typical sync sequence:

1. `on_graph_built` — static analyzers (graph is complete).
2. `on_evidence` — evidence producers.
3. `on_export` — exporters (artefacts under `.repograph/`).
4. If runtime traces exist: `on_traces_collected`, then `on_traces_analyzed`.

Extending **hook names** requires updating `HookName`, plugin manifests, and
the hook scheduler’s dispatch logic (see `PluginHookScheduler` in
`repograph/core/plugin_framework/hooks.py`) when new hook semantics need new
dispatch paths.

## Experimental pipeline phases (`PipelinePhasePlugin`)

Optional code may run **after** the fixed graph-build phases (`p01`–`p13`) and
**before** plugin hooks when `RunConfig.experimental_phase_plugins` is `True`.

This is a **narrow SPI** for future insertions (metrics, validation) without
changing the numbered core phases. Implementations live under
`repograph/plugins/pipeline_phases/` and are listed in
[`registry.py`](../../repograph/plugins/pipeline_phases/registry.py).

Each phase object must provide:

- `phase_id: str` — stable identifier for logging.
- `run(store=..., parsed=..., repo_root=..., repograph_dir=..., config=...)` — side-effecting work.

**Default is off** — production syncs are unchanged unless the flag is enabled
by API callers.

## Safety

- Experimental phases run in **registry order**; avoid cycles by keeping the
  list small and ordered explicitly.
- Failures respect `RunConfig.strict` / `continue_on_error` like hook phases.
