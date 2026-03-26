# Parsers (`kind: parser`)

## Responsibility

Turn raw source files into `ParsedFile` records: symbols, imports, call hints, and language-specific structure. Parsers run during the parse phase; each language maps to one registered plugin.

## Extending

1. Add a package `repograph/plugins/parsers/<language>/` with `plugin.py` exposing `build_plugin() -> ParserPlugin`.
2. Either subclass `ParserPlugin` and implement `parse_file`, or wrap an existing `BaseParser` with `ParserAdapter` (see `base.py`).
3. Declare `supported_languages()`, `manifest.languages`, `hooks=("on_file_parsed",)`, and capability tokens in `requires` / `produces`.
4. Append `<language>` to `PARSER_ORDER` in `repograph/plugins/discovery.py`.

## Example (sketch)

```python
# repograph/plugins/parsers/mylang/plugin.py
from repograph.core.plugin_framework import ParserPlugin, PluginManifest

class MyLangParser(ParserPlugin):
    manifest = PluginManifest(
        id="parser.mylang",
        name="MyLang parser",
        kind="parser",
        languages=("mylang",),
        requires=("files",),
        produces=("symbols", "imports"),
        hooks=("on_file_parsed",),
    )
    def parse_file(self, file_record): ...
def build_plugin(): return MyLangParser()
```

## Requirements

See [`docs/plugins/AUTHORING.md`](../../../docs/plugins/AUTHORING.md), [`docs/plugins/DISCOVERY.md`](../../../docs/plugins/DISCOVERY.md), and `repograph/core/plugin_framework/contracts.py` (`ParserPlugin`).

See also [`docs/SURFACES.md`](../../../docs/SURFACES.md) for **BaseParser** vs **ParserAdapter** vs **ParserPlugin**.
