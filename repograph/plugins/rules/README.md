# Rules (not plugins)

## Responsibility

Rule-pack configuration, severity overrides, and finding status persistence for demand-side analyzers and reporting. This package is **supporting infrastructure**: it is not a `PluginKind` and does not expose `build_plugin()`.

## Extending

- Adjust default packs in `config.py` (`DEFAULT_RULE_PACKS`, families).
- Load/save repo overrides via `.repograph/rule_packs.json` (see `get_rule_pack_config`, `save_rule_pack_overrides`).
- Use `apply_rule_pack_policy` / `summarize_rule_packs` from `demand_analyzers` when emitting findings.

## Requirements

Consumers call `get_rule_pack_config(service)` from analyzer plugins. See `demand_analyzers/README.md` and `docs/plugins/AUTHORING.md` for how findings integrate with manifests.
