# Experimental pipeline phases (optional SPI)

## Responsibility

**Not** part of the main `PluginHookScheduler` hook graph. These implement `PipelinePhasePlugin` (see `repograph/core/plugin_framework/pipeline_phases.py`) for optional experimental pipeline steps. They register in `pipeline_phases/registry.py` and run only when `RunConfig.experimental_phase_plugins` is enabled.

## Extending

1. Add a package under `repograph/plugins/pipeline_phases/<name>/` with `plugin.py` exposing `build_plugin()`.
2. Implement the phase `run(...)` contract expected by `PipelinePhasePlugin`.
3. Register the phase in `registry.py` and document the flag in `docs/architecture/PLUGIN_PHASES_AND_HOOKS.md`.

## Example

See `repograph/plugins/pipeline_phases/no_op/plugin.py` (`NoOpPipelinePhase`).

## Requirements

[`docs/plugins/AUTHORING.md`](../../../docs/plugins/AUTHORING.md) (experimental section), `pipeline_phases.py`, registry module in this folder.
