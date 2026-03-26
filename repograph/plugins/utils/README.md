# Plugin utilities (not plugins)

## Responsibility

Shared helpers used by multiple plugins (e.g. parsing helpers, metadata I/O). **Not** a plugin kind — no `build_plugin()` registration here.

## Extending

Add small, pure modules imported by plugin packages. Avoid coupling to a single plugin family; prefer namespaced functions in `inspection.py`, `meta_io.py`, etc.

## Requirements

Keep imports one-way: plugins → utils. Do not import plugin packages from utils to avoid cycles.
