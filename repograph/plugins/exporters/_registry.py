"""Exporter plugin registry — thin re-export of the existing registry."""
from repograph.plugins.exporters.registry import (
    get_registry,
    register_exporter,
    ensure_default_exporters_registered,
)
__all__ = ["get_registry", "register_exporter", "ensure_default_exporters_registered"]
