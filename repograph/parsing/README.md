# Parsing infrastructure (`repograph.parsing`)

This package holds **shared parse-time utilities** used by the graph pipeline and
by language plugins. It is **not** where language parsers live.

| Module | Role |
|--------|------|
| `base.py` | `BaseParser` and tree-sitter helpers shared by all language parsers. |
| `symbol_table.py` | Cross-file symbol resolution during phases `p04`–`p08`. |
| `html_scanner.py` | HTML `<script>` scanning for dead-code and related analysis. |

**Language parsers** (Python, JavaScript, TypeScript) live under
[`repograph/plugins/parsers/`](../plugins/parsers/) and are registered via
[`repograph/plugins/parsers/registry.py`](../plugins/parsers/registry.py).

How this relates to plugins and the CLI/API/MCP surfaces is summarized in
[`docs/SURFACES.md`](../../docs/SURFACES.md) (Naming: parsing vs plugins).
