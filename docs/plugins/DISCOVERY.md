# Plugin discovery

Built-in RepoGraph plugins are registered by **ordered discovery** of
`repograph.plugins.<kind>.<name>.plugin:build_plugin`.

## Filesystem (primary)

For each plugin family, [`repograph/plugins/discovery.py`](../../repograph/plugins/discovery.py)
defines the **subpackage name** order (registration order can affect hook ordering when
manifest metadata ties). The loader imports `build_plugin` from each
`<kind>/<name>/plugin.py` and registers the result.

Adding a new **built-in** plugin:

1. Create `repograph/plugins/<kind>/<your_plugin>/plugin.py` with `build_plugin()`.
2. Append `<your_plugin>` to the corresponding `*_ORDER` tuple in `discovery.py`.
3. Add tests under `tests/` as described in [`repograph/plugins/README.md`](../../repograph/plugins/README.md).

## Entry points (optional, third-party)

Packaged extensions may register via setuptools **entry points** (group names are
reserved for future use; see `load_optional_entry_point_plugins` in `discovery.py`).
In-tree plugins use filesystem discovery only.

## Special cases

- **Tracer** `coverage_tracer` lives under `dynamic_analyzers/` for historical reasons;
  it is registered explicitly in `tracers/_registry.py`.
